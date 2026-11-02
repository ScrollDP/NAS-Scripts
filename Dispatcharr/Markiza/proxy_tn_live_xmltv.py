#!/usr/bin/env python3
import json
import logging
import os
import signal
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree.ElementTree import Element, SubElement, tostring


# ============================================================
# Configuration
# ============================================================

HOST = os.environ.get(
    "TN_XMLTV_HOST",
    "0.0.0.0",
)

PORT = int(
    os.environ.get(
        "TN_XMLTV_PORT",
        "8766",
    )
)

API_URL = os.environ.get(
    "TN_XMLTV_API_URL",
    "https://tnlive.cms.markiza.sk/api/v1/tnlive/program?channel_id=48",
).strip()

CHANNEL_ID = os.environ.get(
    "TN_XMLTV_CHANNEL_ID",
    "tnlive",
).strip()

CHANNEL_NAME = os.environ.get(
    "TN_XMLTV_CHANNEL_NAME",
    "TN Live",
).strip()

REFRESH_SECONDS = int(
    os.environ.get(
        "TN_XMLTV_REFRESH_SECONDS",
        "900",
    )
)

HTTP_TIMEOUT = int(
    os.environ.get(
        "TN_XMLTV_HTTP_TIMEOUT",
        "20",
    )
)

USER_AGENT = os.environ.get(
    "TN_XMLTV_USER_AGENT",
    "TNLive-XMLTV-Proxy/1.0",
)


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s %(levelname)s "
        "%(message)s"
    ),
)

logger = logging.getLogger(
    "tnlive-xmltv"
)


# ============================================================
# Application state
# ============================================================

class State:
    def __init__(self):
        self.lock = threading.RLock()

        self.xmltv = None

        self.program_count = 0

        self.last_refresh = None
        self.last_success = None
        self.last_error = None

        self.refreshing = False

        self.stop_event = threading.Event()


state = State()


# ============================================================
# Utility functions
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    )


def iso_now():
    return utc_now().isoformat()


def parse_datetime(value):
    """
    Parse the ISO-8601 timestamps returned by TN Live.

    Examples:
        2026-09-14T10:00:00+02:00
        2026-09-14T16:59:30+02:00
    """

    if not value:
        return None

    value = str(value).strip()

    try:
        dt = datetime.fromisoformat(
            value
        )
    except ValueError:
        logger.warning(
            "Unable to parse datetime: %s",
            value,
        )
        return None

    if dt.tzinfo is None:
        # The API should normally return an offset.
        # Treat a missing timezone as local/UTC rather
        # than producing an invalid XMLTV timestamp.
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt


def xmltv_time(dt):
    """
    XMLTV convention:

        YYYYMMDDHHMMSS +0000

    Always convert to UTC.
    """

    if dt is None:
        return ""

    dt = dt.astimezone(
        timezone.utc
    )

    return dt.strftime(
        "%Y%m%d%H%M%S +0000"
    )


def xml_escape_text(value):
    """
    ElementTree performs XML escaping for element text,
    but normalize values here to strings.
    """

    if value is None:
        return ""

    return str(value).strip()


# ============================================================
# TN Live API
# ============================================================

def fetch_api():
    logger.info(
        "Fetching TN Live program API: %s",
        API_URL,
    )

    request = Request(
        API_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    with urlopen(
        request,
        timeout=HTTP_TIMEOUT,
    ) as response:

        if response.status != 200:
            raise RuntimeError(
                f"TN Live API returned HTTP "
                f"{response.status}"
            )

        body = response.read()

    if not body:
        raise RuntimeError(
            "TN Live API returned an empty response"
        )

    try:
        payload = json.loads(
            body.decode(
                "utf-8",
                errors="replace",
            )
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid JSON from TN Live API: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            "TN Live API response is not a JSON object"
        )

    programs = payload.get(
        "program"
    )

    if not isinstance(
        programs,
        list,
    ):
        raise RuntimeError(
            "TN Live API response does not contain "
            "program[]"
        )

    return payload, programs

# ============================================================
# XMLTV generation
# ============================================================

def generate_xmltv(
    payload,
    programs,
):
    """
    Convert TN Live API data directly into XMLTV.

    Behaviour:

    - Include currentProgram when it is NOT already present
      in program[].
    - Include every programme from program[].
    - Do not remove history.
    - Do not remove filler.
    - Do not remove overlaps.
    - Do not truncate.
    - Do not deduplicate program[].
    - Do not otherwise modify the API schedule.

    This is important because TN Live currently returns the
    currently running programme in currentProgram, while the
    next scheduled programme begins in program[].
    """

    root = Element(
        "tv",
        {
            "generator-info-name":
                "TN Live XMLTV Proxy",
            "generator-info-url":
                "https://tnlive.sk/",
        },
    )

    # --------------------------------------------------------
    # Channel
    # --------------------------------------------------------

    channel = SubElement(
        root,
        "channel",
        {
            "id": CHANNEL_ID,
        },
    )

    display_name = SubElement(
        channel,
        "display-name",
        {
            "lang": "sk",
        },
    )

    display_name.text = CHANNEL_NAME

    # --------------------------------------------------------
    # Current programme
    # --------------------------------------------------------

    current_program = payload.get(
        "currentProgram"
    )

    # --------------------------------------------------------
    # Channel icon
    # --------------------------------------------------------

    icon_url = ""

    if isinstance(
        current_program,
        dict,
    ):
        icon_url = str(
            current_program.get(
                "channelImage",
                "",
            )
            or ""
        ).strip()

    if not icon_url:

        for program in programs:

            if not isinstance(
                program,
                dict,
            ):
                continue

            icon_url = str(
                program.get(
                    "channelImage",
                    "",
                )
                or ""
            ).strip()

            if icon_url:
                break

    if icon_url:

        SubElement(
            channel,
            "icon",
            {
                "src": icon_url,
            },
        )

    # --------------------------------------------------------
    # Determine whether currentProgram is already in
    # program[].
    #
    # Normally the API uses the programme ID for this.
    # --------------------------------------------------------

    current_program_id = None

    if isinstance(
        current_program,
        dict,
    ):
        current_program_id = (
            current_program.get("id")
        )

    current_program_already_present = False

    if current_program_id is not None:

        for program in programs:

            if not isinstance(
                program,
                dict,
            ):
                continue

            if (
                program.get("id")
                == current_program_id
            ):
                current_program_already_present = True
                break

    # --------------------------------------------------------
    # Helper for writing one programme
    # --------------------------------------------------------

    def write_programme(
        program,
        live=False,
    ):

        if not isinstance(
            program,
            dict,
        ):
            return False

        title = xml_escape_text(
            program.get("title")
        )

        start = parse_datetime(
            program.get("timeFrom")
        )

        stop = parse_datetime(
            program.get("timeTo")
        )

        if start is None or stop is None:

            logger.warning(
                "Skipping programme with invalid "
                "datetime: %r",
                program,
            )

            return False

        if stop <= start:

            logger.warning(
                "Skipping programme with invalid "
                "interval: %s -> %s (%s)",
                start,
                stop,
                title,
            )

            return False

        programme_element = SubElement(
            root,
            "programme",
            {
                "channel": CHANNEL_ID,
                "start": xmltv_time(start),
                "stop": xmltv_time(stop),
            },
        )

        # ----------------------------------------------------
        # Title
        # ----------------------------------------------------

        title_element = SubElement(
            programme_element,
            "title",
            {
                "lang": "sk",
            },
        )

        title_element.text = title

        # ----------------------------------------------------
        # Description
        # ----------------------------------------------------

        desc = (
            program.get("description")
            or program.get("desc")
            or CHANNEL_NAME
        )

        desc_element = SubElement(
            programme_element,
            "desc",
            {
                "lang": "sk",
            },
        )

        desc_element.text = (
            xml_escape_text(desc)
        )

        # ----------------------------------------------------
        # Category
        # ----------------------------------------------------

        category = (
            program.get("category")
            or program.get("genre")
        )

        if category:

            category_element = SubElement(
                programme_element,
                "category",
                {
                    "lang": "sk",
                },
            )

            category_element.text = (
                xml_escape_text(category)
            )

        # ----------------------------------------------------
        # Live marker
        # ----------------------------------------------------

        if live:

            live_element = SubElement(
                programme_element,
                "live",
            )

            live_element.text = "yes"

        return True

    # --------------------------------------------------------
    # Write currentProgram if it is NOT already in program[]
    #
    # This is currently necessary for TN Live because the API
    # returns the active programme separately from program[].
    # --------------------------------------------------------

    written = 0

    if (
        isinstance(
            current_program,
            dict,
        )
        and not current_program_already_present
    ):

        if write_programme(
            current_program,
            live=True,
        ):

            written += 1

            logger.info(
                "Added currentProgram separately: "
                "id=%s title=%s",
                current_program.get("id"),
                current_program.get("title"),
            )

    # --------------------------------------------------------
    # Write EVERY programme from program[]
    # --------------------------------------------------------

    for program in programs:

        if not isinstance(
            program,
            dict,
        ):
            continue

        is_current = (
            isinstance(
                current_program,
                dict,
            )
            and current_program.get("id")
            == program.get("id")
        )

        if write_programme(
            program,
            live=is_current,
        ):

            written += 1

    # --------------------------------------------------------
    # Serialize
    # --------------------------------------------------------

    xml = tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
    )

    logger.info(
        "XMLTV generated: %d programmes, %d bytes",
        written,
        len(xml),
    )

    return xml, written

# ============================================================
# Refresh XMLTV
# ============================================================

def refresh_xmltv():
    """
    Fetch the TN Live API and regenerate the XMLTV cache.

    The API's program[] list is passed directly to
    generate_xmltv().

    No programme filtering, deduplication, overlap removal,
    filler removal, history removal, or truncation is done.
    """

    with state.lock:

        if state.refreshing:
            logger.info(
                "XMLTV refresh already in progress"
            )

            return {
                "status": "busy",
                "program_count":
                    state.program_count,
            }

        state.refreshing = True
        state.last_refresh = iso_now()

    try:

        payload, programs = fetch_api()

        xmltv, program_count = generate_xmltv(
            payload,
            programs,
        )

        with state.lock:

            state.xmltv = xmltv

            state.program_count = (
                program_count
            )

            state.last_success = (
                iso_now()
            )

            state.last_error = None

            state.refreshing = False

        logger.info(
            "XMLTV refresh successful: "
            "%d programmes, %d bytes",
            program_count,
            len(xmltv),
        )

        return {
            "status": "ok",
            "program_count":
                program_count,
            "bytes":
                len(xmltv),
            "last_success":
                state.last_success,
        }

    except Exception as exc:

        logger.exception(
            "XMLTV refresh failed: %s",
            exc,
        )

        with state.lock:

            state.last_error = str(
                exc
            )

            state.refreshing = False

        return {
            "status": "error",
            "message":
                str(exc),
            "program_count":
                state.program_count,
            "cache_ready":
                state.xmltv is not None,
        }

# ============================================================
# Background refresh thread
# ============================================================

def refresh_loop():

    logger.info(
        "XMLTV background refresh thread started "
        "(interval=%s seconds)",
        REFRESH_SECONDS,
    )

    while not state.stop_event.is_set():

        # Wait for the configured interval.
        if state.stop_event.wait(
            REFRESH_SECONDS
        ):
            break

        if state.stop_event.is_set():
            break

        refresh_xmltv()

    logger.info(
        "XMLTV background refresh thread stopped"
    )


# ============================================================
# HTTP server
# ============================================================

class RequestHandler(
    BaseHTTPRequestHandler
):

    server_version = (
        "TNLiveXMLTV/1.0"
    )

    def log_message(
        self,
        format_string,
        *args,
    ):
        logger.info(
            "%s - %s",
            self.address_string(),
            format_string % args,
        )

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------

    def _send_json(
        self,
        status,
        payload,
    ):

        body = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ).encode(
            "utf-8"
        )

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.send_header(
            "Cache-Control",
            "no-cache",
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    def _send_xmltv(
        self,
        body,
    ):

        self.send_response(
            200
        )

        self.send_header(
            "Content-Type",
            "application/xml; charset=utf-8",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.send_header(
            "Cache-Control",
            "no-cache, no-store, must-revalidate",
        )

        self.send_header(
            "Pragma",
            "no-cache",
        )

        self.send_header(
            "Expires",
            "0",
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    def do_GET(self):

        path = self.path.split(
            "?",
            1,
        )[0]

        # ----------------------------------------------------
        # Health
        # ----------------------------------------------------

        if path == "/health":

            with state.lock:

                ready = (
                    state.xmltv is not None
                )

                payload = {
                    "status":
                        "ok"
                        if ready
                        else "starting",
                    "ready": ready,
                    "program_count":
                        state.program_count,
                    "last_success":
                        state.last_success,
                    "last_error":
                        state.last_error,
                }

            self._send_json(
                200 if ready else 503,
                payload,
            )

            return

        # ----------------------------------------------------
        # Status
        # ----------------------------------------------------

        if path == "/status":

            with state.lock:

                payload = {
                    "status": "ok",
                    "api_url": API_URL,
                    "channel_id": CHANNEL_ID,
                    "channel_name": CHANNEL_NAME,
                    "host": HOST,
                    "port": PORT,
                    "refresh_seconds":
                        REFRESH_SECONDS,
                    "http_timeout":
                        HTTP_TIMEOUT,
                    "program_count":
                        state.program_count,
                    "cache_ready":
                        state.xmltv is not None,
                    "cache_bytes":
                        len(state.xmltv)
                        if state.xmltv
                        else 0,
                    "last_refresh":
                        state.last_refresh,
                    "last_success":
                        state.last_success,
                    "last_error":
                        state.last_error,
                    "refreshing":
                        state.refreshing,
                }

            self._send_json(
                200,
                payload,
            )

            return

        # ----------------------------------------------------
        # XMLTV
        # ----------------------------------------------------

        if path in (
            "/xmltv.xml",
            "/xmltv",
        ):

            with state.lock:
                xmltv = state.xmltv

            if xmltv is None:

                self._send_json(
                    503,
                    {
                        "status": "error",
                        "message": (
                            "XMLTV cache is not ready"
                        ),
                    },
                )

                return

            self._send_xmltv(
                xmltv
            )

            return

        # ----------------------------------------------------
        # Manual refresh
        # ----------------------------------------------------

        if path == "/refresh":

            result = refresh_xmltv()

            self._send_json(
                200
                if result.get(
                    "status"
                ) == "ok"
                else 500,
                result,
            )

            return

        # ----------------------------------------------------
        # Root
        # ----------------------------------------------------

        if path == "/":

            self._send_json(
                200,
                {
                    "status": "ok",
                    "service":
                        "TN Live XMLTV Proxy",
                    "xmltv":
                        "/xmltv.xml",
                    "health":
                        "/health",
                    "status_endpoint":
                        "/status",
                    "refresh":
                        "/refresh",
                },
            )

            return

        # ----------------------------------------------------
        # Not found
        # ----------------------------------------------------

        self._send_json(
            404,
            {
                "status": "error",
                "message": "Not found",
            },
        )


# ============================================================
# Shutdown
# ============================================================

http_server = None


def shutdown_handler(
    signum,
    frame,
):
    logger.info(
        "Received signal %s, shutting down",
        signum,
    )

    state.stop_event.set()

    if http_server is not None:
        threading.Thread(
            target=http_server.shutdown,
            daemon=True,
        ).start()


# ============================================================
# Main
# ============================================================

def main():

    global http_server

    logger.info(
        "Starting TN Live XMLTV Proxy"
    )

    logger.info(
        "Listen: %s:%s",
        HOST,
        PORT,
    )

    logger.info(
        "API: %s",
        API_URL,
    )

    logger.info(
        "Channel: %s (%s)",
        CHANNEL_NAME,
        CHANNEL_ID,
    )

    logger.info(
        "Refresh interval: %s seconds",
        REFRESH_SECONDS,
    )

    # --------------------------------------------------------
    # Validate configuration
    # --------------------------------------------------------

    if not API_URL:
        raise RuntimeError(
            "TN_XMLTV_API_URL is empty"
        )

    if not CHANNEL_ID:
        raise RuntimeError(
            "TN_XMLTV_CHANNEL_ID is empty"
        )

    if not CHANNEL_NAME:
        raise RuntimeError(
            "TN_XMLTV_CHANNEL_NAME is empty"
        )

    if PORT < 1 or PORT > 65535:
        raise RuntimeError(
            f"Invalid port: {PORT}"
        )

    if REFRESH_SECONDS < 10:
        raise RuntimeError(
            "TN_XMLTV_REFRESH_SECONDS must "
            "be at least 10"
        )

    # --------------------------------------------------------
    # Signal handlers
    # --------------------------------------------------------

    signal.signal(
        signal.SIGTERM,
        shutdown_handler,
    )

    signal.signal(
        signal.SIGINT,
        shutdown_handler,
    )

    # --------------------------------------------------------
    # Initial API fetch
    #
    # Important:
    # The HTTP server starts only after the first fetch
    # attempt. If the API is temporarily unavailable, the
    # server still starts and /health reports 503 until a
    # successful refresh occurs.
    # --------------------------------------------------------

    refresh_result = refresh_xmltv()

    if refresh_result.get(
        "status"
    ) != "ok":

        logger.warning(
            "Initial XMLTV refresh failed. "
            "The HTTP server will remain available "
            "and retry in the background."
        )

    # --------------------------------------------------------
    # Background refresh
    # --------------------------------------------------------

    refresh_thread = threading.Thread(
        target=refresh_loop,
        name="xmltv-refresh",
        daemon=True,
    )

    refresh_thread.start()

    # --------------------------------------------------------
    # HTTP server
    # --------------------------------------------------------

    try:

        http_server = ThreadingHTTPServer(
            (
                HOST,
                PORT,
            ),
            RequestHandler,
        )

        http_server.daemon_threads = True

        logger.info(
            "XMLTV HTTP server listening on "
            "http://%s:%s",
            HOST,
            PORT,
        )

        http_server.serve_forever(
            poll_interval=0.5
        )

    except OSError as exc:

        logger.exception(
            "Unable to start HTTP server: %s",
            exc,
        )

        raise

    finally:

        state.stop_event.set()

        if http_server is not None:

            try:
                http_server.server_close()
            except Exception:
                pass

        logger.info(
            "TN Live XMLTV Proxy stopped"
        )


if __name__ == "__main__":
    main()
