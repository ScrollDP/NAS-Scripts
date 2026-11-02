#!/usr/bin/env python3

import html
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.sax.saxutils import escape as xml_escape

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


# ============================================================
# Configuration
# ============================================================

HOST = os.environ.get(
    "MARKIZA_XMLTV_HOST",
    "0.0.0.0",
)

PORT = int(
    os.environ.get(
        "MARKIZA_XMLTV_PORT",
        "8770",
    )
)

REFRESH_SECONDS = int(
    os.environ.get(
        "MARKIZA_XMLTV_REFRESH_SECONDS",
        "300",
    )
)

HTTP_TIMEOUT = int(
    os.environ.get(
        "MARKIZA_XMLTV_HTTP_TIMEOUT",
        "20",
    )
)

USER_AGENT = os.environ.get(
    "MARKIZA_XMLTV_USER_AGENT",
    "Markiza-XMLTV-Proxy/1.0",
)

TIMEZONE_NAME = os.environ.get(
    "MARKIZA_XMLTV_TIMEZONE",
    "Europe/Bratislava",
)


# ============================================================
# Channels
# ============================================================

CHANNELS = {
    "markiza": {
        "name": "Markíza",
        "url": os.environ.get(
            "MARKIZA_XMLTV_MARKIZA_URL",
            "https://www.markiza.sk/live/1-markiza",
        ),
    },

    "dajto": {
        "name": "Dajto",
        "url": os.environ.get(
            "MARKIZA_XMLTV_DAJTO_URL",
            "https://www.markiza.sk/live/2-dajto",
        ),
    },

    "doma": {
        "name": "Doma",
        "url": os.environ.get(
            "MARKIZA_XMLTV_DOMA_URL",
            "https://www.markiza.sk/live/3-doma",
        ),
    },

    "krimi": {
        "name": "Krimi",
        "url": os.environ.get(
            "MARKIZA_XMLTV_KRIMI_URL",
            "https://www.markiza.sk/live/22-krimi",
        ),
    },

    "klasik": {
        "name": "Klasik",
        "url": os.environ.get(
            "MARKIZA_XMLTV_KLASIK_URL",
            "https://www.markiza.sk/live/44-klasik",
        ),
    },
}


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

log = logging.getLogger("markiza-xmltv")


# ============================================================
# Timezone
# ============================================================

LOCAL_TZ = None

if ZoneInfo is not None:
    try:
        LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)
    except Exception:
        log.warning(
            "Unable to load timezone %s",
            TIMEZONE_NAME,
        )


# ============================================================
# Helpers
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def parse_hhmm(value):
    if not value:
        return None

    value = clean_text(value)

    match = re.fullmatch(
        r"(\d{1,2}):(\d{2})",
        value,
    )

    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))

    if hour > 23 or minute > 59:
        return None

    return hour, minute


def parse_iso_datetime(value):
    if not value:
        return None

    value = clean_text(value)

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_playtime(value):
    """
    Example:

    2026-09-16T20:30:00+02:00 2026-09-16T23:35:00+02:00
    """

    if not value:
        return None, None

    parts = re.split(
        r"\s+",
        value.strip(),
    )

    if len(parts) < 2:
        return None, None

    start = parse_iso_datetime(parts[0])
    end = parse_iso_datetime(parts[1])

    return start, end


def format_xmltv_datetime(dt):
    if dt is None:
        return None

    if dt.tzinfo is None:
        if LOCAL_TZ is not None:
            dt = dt.replace(tzinfo=LOCAL_TZ)

    return dt.strftime(
        "%Y%m%d%H%M%S %z"
    )


def normalize_title(value):
    value = clean_text(value)

    if not value:
        return "Neznámy program"

    return value


# ============================================================
# HTML Parser
# ============================================================

class MarkizaLiveParser(HTMLParser):

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.tag_stack = []

        self.in_carousel = False
        self.carousel_depth = 0

        self.current = None
        self.live_box_depth = 0

        self.capture_title = False
        self.title_buffer = []

        self.capture_start = False
        self.start_buffer = []

        self.capture_end = False
        self.end_buffer = []

        self.programs = []

    # --------------------------------------------------------
    # Attributes
    # --------------------------------------------------------

    @staticmethod
    def attrs_dict(attrs):
        return dict(attrs)

    @staticmethod
    def classes(attrs):
        attrs_dict = dict(attrs)

        return set(
            attrs_dict.get(
                "class",
                "",
            ).split()
        )

    # --------------------------------------------------------
    # Start tag
    # --------------------------------------------------------

    def handle_starttag(
        self,
        tag,
        attrs,
    ):
        attrs_dict = self.attrs_dict(attrs)
        classes = self.classes(attrs)

        self.tag_stack.append(tag)

        # ----------------------------------------------------
        # Enter live playlist
        # ----------------------------------------------------

        if (
            tag == "div"
            and "js-playlist-live-carousel" in classes
        ):
            self.in_carousel = True
            self.carousel_depth = 1
            return

        # ----------------------------------------------------
        # Nested div inside carousel
        # ----------------------------------------------------

        if (
            self.in_carousel
            and tag == "div"
            and self.current is None
        ):
            self.carousel_depth += 1

        # ----------------------------------------------------
        # New live box
        # ----------------------------------------------------

        if (
            self.in_carousel
            and tag == "div"
            and "c-live-box" in classes
        ):
            if self.current is not None:
                self.finish_current()

            self.current = {
                "title": "",
                "time_start": None,
                "time_end": None,
                "playtime": None,
            }

            self.live_box_depth = 1

            return

        # ----------------------------------------------------
        # Nested div inside live box
        # ----------------------------------------------------

        if (
            self.current is not None
            and tag == "div"
            and self.live_box_depth > 0
        ):
            self.live_box_depth += 1

        # ----------------------------------------------------
        # Exact start/end interval
        # ----------------------------------------------------

        if (
            self.current is not None
            and tag == "div"
            and "c-progress-bar" in classes
        ):
            playtime = attrs_dict.get(
                "data-playtime"
            )

            if playtime:
                self.current[
                    "playtime"
                ] = clean_text(playtime)

        # ----------------------------------------------------
        # Title
        # ----------------------------------------------------

        if (
            self.current is not None
            and tag in (
                "h2",
                "h3",
                "h4",
            )
            and "title" in classes
        ):
            self.capture_title = True
            self.title_buffer = []

        # ----------------------------------------------------
        # Start time
        # ----------------------------------------------------

        if (
            self.current is not None
            and tag == "time"
            and "time-start" in classes
        ):
            value = attrs_dict.get(
                "datetime"
            )

            if value:
                self.current[
                    "time_start"
                ] = clean_text(value)

            self.capture_start = True
            self.start_buffer = []

        # ----------------------------------------------------
        # End time
        # ----------------------------------------------------

        if (
            self.current is not None
            and tag == "time"
            and "time-end" in classes
        ):
            value = attrs_dict.get(
                "datetime"
            )

            if value:
                self.current[
                    "time_end"
                ] = clean_text(value)

            self.capture_end = True
            self.end_buffer = []

    # --------------------------------------------------------
    # End tag
    # --------------------------------------------------------

    def handle_endtag(self, tag):

        # ----------------------------------------------------
        # Title
        # ----------------------------------------------------

        if (
            tag in (
                "h2",
                "h3",
                "h4",
            )
            and self.capture_title
        ):
            title = clean_text(
                "".join(
                    self.title_buffer
                )
            )

            if self.current is not None:
                self.current[
                    "title"
                ] = title

            self.capture_title = False
            self.title_buffer = []

        # ----------------------------------------------------
        # Start time
        # ----------------------------------------------------

        if (
            tag == "time"
            and self.capture_start
        ):
            value = clean_text(
                "".join(
                    self.start_buffer
                )
            )

            if self.current is not None:
                if not self.current[
                    "time_start"
                ]:
                    self.current[
                        "time_start"
                    ] = value

            self.capture_start = False
            self.start_buffer = []

        # ----------------------------------------------------
        # End time
        # ----------------------------------------------------

        if (
            tag == "time"
            and self.capture_end
        ):
            value = clean_text(
                "".join(
                    self.end_buffer
                )
            )

            if self.current is not None:
                if not self.current[
                    "time_end"
                ]:
                    self.current[
                        "time_end"
                    ] = value

            self.capture_end = False
            self.end_buffer = []

        # ----------------------------------------------------
        # Live box
        # ----------------------------------------------------

        if (
            self.current is not None
            and tag == "div"
            and self.live_box_depth > 0
        ):
            self.live_box_depth -= 1

            if self.live_box_depth == 0:
                self.finish_current()

        # ----------------------------------------------------
        # Carousel nesting
        # ----------------------------------------------------

        if (
            self.in_carousel
            and tag == "div"
            and self.current is None
        ):
            self.carousel_depth -= 1

            if self.carousel_depth <= 0:
                self.in_carousel = False
                self.carousel_depth = 0

        # ----------------------------------------------------
        # Tag stack
        # ----------------------------------------------------

        if self.tag_stack:
            self.tag_stack.pop()

    # --------------------------------------------------------
    # Text
    # --------------------------------------------------------

    def handle_data(self, data):

        if self.capture_title:
            self.title_buffer.append(data)

        if self.capture_start:
            self.start_buffer.append(data)

        if self.capture_end:
            self.end_buffer.append(data)

    # --------------------------------------------------------
    # Finish program
    # --------------------------------------------------------

    def finish_current(self):

        if self.current is None:
            return

        program = {
            "title": normalize_title(
                self.current.get(
                    "title"
                )
            ),
            "time_start":
                self.current.get(
                    "time_start"
                ),
            "time_end":
                self.current.get(
                    "time_end"
                ),
            "playtime":
                self.current.get(
                    "playtime"
                ),
        }

        if (
            program["time_start"]
            or program["playtime"]
        ):
            self.programs.append(
                program
            )

        self.current = None
        self.live_box_depth = 0

    # --------------------------------------------------------
    # Close
    # --------------------------------------------------------

    def close(self):

        if self.current is not None:
            self.finish_current()

        super().close()


# ============================================================
# Extract playlist
# ============================================================

def extract_playlist(html_text):

    parser = MarkizaLiveParser()

    try:
        parser.feed(html_text)
        parser.close()
    except Exception:
        log.exception(
            "HTML parser error"
        )

    result = []

    seen = set()

    for program in parser.programs:

        key = (
            program.get(
                "title",
                "",
            ),
            program.get(
                "time_start",
                "",
            ),
            program.get(
                "time_end",
                "",
            ),
            program.get(
                "playtime",
                "",
            ),
        )

        if key in seen:
            continue

        seen.add(key)

        result.append(
            program
        )

    return result


# ============================================================
# Fetch HTML
# ============================================================

def fetch_url(url):

    request = Request(
        url,
        headers={
            "User-Agent":
                USER_AGENT,

            "Accept":
                (
                    "text/html,"
                    "application/xhtml+xml,"
                    "application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),

            "Accept-Language":
                "sk-SK,sk;q=0.9,en;q=0.7",

            "Cache-Control":
                "no-cache",
        },
    )

    with urlopen(
        request,
        timeout=HTTP_TIMEOUT,
    ) as response:

        raw = response.read()

        charset = (
            response.headers.get_content_charset()
        )

        if not charset:
            charset = "utf-8"

        return raw.decode(
            charset,
            errors="replace",
        )


# ============================================================
# Convert Markíza times into absolute datetimes
# ============================================================

def build_program_times(programs):

    if not programs:
        return []

    # --------------------------------------------------------
    # Find an exact ISO anchor.
    #
    # Usually this is the current program:
    #
    # data-playtime="
    # 2026-09-16T20:30:00+02:00
    # 2026-09-16T23:35:00+02:00"
    # --------------------------------------------------------

    anchor_start = None

    for program in programs:

        start, end = parse_playtime(
            program.get(
                "playtime"
            )
        )

        if start is not None:
            anchor_start = start
            break

    # --------------------------------------------------------
    # If there is no ISO anchor, use current local time.
    # --------------------------------------------------------

    if anchor_start is None:

        if LOCAL_TZ is not None:
            anchor_start = datetime.now(
                LOCAL_TZ
            )
        else:
            anchor_start = (
                datetime.now().astimezone()
            )

    current_date = anchor_start.date()

    previous_start = None

    result = []

    # --------------------------------------------------------
    # Walk programmes in page order.
    # --------------------------------------------------------

    for program in programs:

        title = normalize_title(
            program.get(
                "title"
            )
        )

        # ----------------------------------------------------
        # Exact ISO current programme
        # ----------------------------------------------------

        exact_start, exact_end = (
            parse_playtime(
                program.get(
                    "playtime"
                )
            )
        )

        if exact_start is not None:

            start = exact_start
            end = exact_end

            current_date = (
                start.date()
            )

            previous_start = start

            result.append(
                {
                    "title": title,
                    "start": start,
                    "end": end,
                }
            )

            continue

        # ----------------------------------------------------
        # HH:MM start
        # ----------------------------------------------------

        hm = parse_hhmm(
            program.get(
                "time_start"
            )
        )

        if hm is None:
            log.warning(
                "Skipping program without valid start: %s",
                title,
            )
            continue

        hour, minute = hm

        tz = None

        if previous_start is not None:
            tz = previous_start.tzinfo

        elif LOCAL_TZ is not None:
            tz = LOCAL_TZ

        else:
            tz = anchor_start.tzinfo

        candidate = datetime(
            current_date.year,
            current_date.month,
            current_date.day,
            hour,
            minute,
            tzinfo=tz,
        )

        # ----------------------------------------------------
        # MIDNIGHT TRANSITION
        #
        # Example:
        #
        # 23:35
        # 00:30
        # 01:20
        #
        # 00:30 <= 23:35, therefore next calendar day.
        # ----------------------------------------------------

        if (
            previous_start is not None
            and candidate <= previous_start
        ):
            candidate += timedelta(
                days=1
            )

            current_date = (
                candidate.date()
            )

        start = candidate

        # ----------------------------------------------------
        # Explicit end time
        # ----------------------------------------------------

        end = None

        end_hm = parse_hhmm(
            program.get(
                "time_end"
            )
        )

        if end_hm is not None:

            end_hour, end_minute = end_hm

            end_candidate = datetime(
                start.year,
                start.month,
                start.day,
                end_hour,
                end_minute,
                tzinfo=start.tzinfo,
            )

            # End crosses midnight.
            if end_candidate <= start:
                end_candidate += timedelta(
                    days=1
                )

            end = end_candidate

        result.append(
            {
                "title": title,
                "start": start,
                "end": end,
            }
        )

        previous_start = start

    # --------------------------------------------------------
    # Infer missing end from next start.
    # --------------------------------------------------------

    for index in range(
        len(result) - 1
    ):

        current = result[index]
        following = result[index + 1]

        if current["end"] is None:

            next_start = following[
                "start"
            ]

            if (
                next_start
                > current["start"]
            ):
                current["end"] = (
                    next_start
                )

    return result


# ============================================================
# XMLTV
# ============================================================

def add_text(
    parent,
    tag,
    text,
    lang=None,
):

    element = SubElement(
        parent,
        tag,
    )

    element.text = (
        text
        if text is not None
        else ""
    )

    if lang:
        element.set(
            "lang",
            lang,
        )

    return element


def generate_xmltv(channel_data):

    tv = Element(
        "tv",
        {
            "generator-info-name":
                "Markiza XMLTV Proxy",
        },
    )

    # --------------------------------------------------------
    # Channels
    # --------------------------------------------------------

    for channel_id, config in (
        CHANNELS.items()
    ):

        channel = SubElement(
            tv,
            "channel",
            {
                "id": channel_id,
            },
        )

        add_text(
            channel,
            "display-name",
            config["name"],
        )

    # --------------------------------------------------------
    # Programmes
    # --------------------------------------------------------

    for channel_id in CHANNELS:

        source = channel_data.get(
            channel_id
        )

        if not source:
            continue

        programs = source.get(
            "programs",
            [],
        )

        for program in programs:

            start = program.get(
                "start"
            )

            end = program.get(
                "end"
            )

            if start is None:
                continue

            attributes = {
                "channel":
                    channel_id,

                "start":
                    format_xmltv_datetime(
                        start
                    ),
            }

            if end is not None:

                attributes[
                    "stop"
                ] = format_xmltv_datetime(
                    end
                )

            programme = SubElement(
                tv,
                "programme",
                attributes,
            )

            add_text(
                programme,
                "title",
                program.get(
                    "title",
                    "Neznámy program",
                ),
                lang="sk",
            )

    return tostring(
        tv,
        encoding="utf-8",
        xml_declaration=True,
    )


# ============================================================
# Service
# ============================================================

class XMLTVService:

    def __init__(self):

        self.lock = (
            threading.RLock()
        )

        self.xml = None

        self.channel_data = {}

        self.last_refresh = None
        self.last_success = None
        self.last_error = None

        self.refreshing = False

        self.channel_status = {}

        for channel_id in CHANNELS:

            self.channel_status[
                channel_id
            ] = {
                "last_success":
                    None,

                "last_error":
                    None,

                "program_count":
                    0,
            }

    # --------------------------------------------------------
    # One channel
    # --------------------------------------------------------

    def refresh_channel(
        self,
        channel_id,
        config,
    ):

        log.info(
            "Fetching %s: %s",
            config["name"],
            config["url"],
        )

        try:

            html_text = fetch_url(
                config["url"]
            )

            raw_programs = (
                extract_playlist(
                    html_text
                )
            )

            if not raw_programs:

                raise RuntimeError(
                    "No programs found"
                )

            programs = (
                build_program_times(
                    raw_programs
                )
            )

            if not programs:

                raise RuntimeError(
                    "No valid programs"
                )

            now = time.time()

            self.channel_status[
                channel_id
            ] = {
                "last_success":
                    now,

                "last_error":
                    None,

                "program_count":
                    len(programs),
            }

            log.info(
                "%s: %d programs",
                config["name"],
                len(programs),
            )

            for program in programs:

                start = program.get(
                    "start"
                )

                end = program.get(
                    "end"
                )

                log.info(
                    "%s: %s -> %s | %s",
                    config["name"],
                    start,
                    end,
                    program["title"],
                )

            return {
                "name":
                    config["name"],

                "programs":
                    programs,
            }

        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:

            error = str(exc)

            previous = (
                self.channel_status[
                    channel_id
                ]
            )

            self.channel_status[
                channel_id
            ] = {
                "last_success":
                    previous.get(
                        "last_success"
                    ),

                "last_error":
                    error,

                "program_count":
                    previous.get(
                        "program_count",
                        0,
                    ),
            }

            log.error(
                "%s failed: %s",
                config["name"],
                error,
            )

            return None

        except Exception as exc:

            error = str(exc)

            previous = (
                self.channel_status[
                    channel_id
                ]
            )

            self.channel_status[
                channel_id
            ] = {
                "last_success":
                    previous.get(
                        "last_success"
                    ),

                "last_error":
                    error,

                "program_count":
                    previous.get(
                        "program_count",
                        0,
                    ),
            }

            log.exception(
                "%s failed",
                config["name"],
            )

            return None

    # --------------------------------------------------------
    # Refresh everything
    # --------------------------------------------------------

    def refresh(self):

        with self.lock:

            if self.refreshing:

                log.warning(
                    "Refresh already running"
                )

                return False

            self.refreshing = True

        try:

            log.info(
                "Starting Markíza XMLTV refresh"
            )

            successful = {}

            for channel_id, config in (
                CHANNELS.items()
            ):

                result = (
                    self.refresh_channel(
                        channel_id,
                        config,
                    )
                )

                if result is not None:

                    successful[
                        channel_id
                    ] = result

            # ------------------------------------------------
            # Preserve previously working channels if one
            # request temporarily fails.
            # ------------------------------------------------

            with self.lock:

                merged = dict(
                    self.channel_data
                )

                merged.update(
                    successful
                )

                self.channel_data = (
                    merged
                )

                if merged:

                    self.xml = (
                        generate_xmltv(
                            merged
                        )
                    )

                    self.last_success = (
                        time.time()
                    )

                    self.last_error = None

                else:

                    self.last_error = (
                        "All channels failed"
                    )

                self.last_refresh = (
                    time.time()
                )

            log.info(
                "Refresh complete: %d/%d channels",
                len(successful),
                len(CHANNELS),
            )

            return bool(successful)

        finally:

            with self.lock:
                self.refreshing = False

    # --------------------------------------------------------
    # Background refresh
    # --------------------------------------------------------

    def refresh_loop(self):

        while True:

            try:
                self.refresh()

            except Exception:

                log.exception(
                    "Background refresh failed"
                )

            time.sleep(
                REFRESH_SECONDS
            )

    # --------------------------------------------------------
    # Status
    # --------------------------------------------------------

    def status(self):

        with self.lock:

            channels = {}

            for channel_id, value in (
                self.channel_status.items()
            ):

                channels[
                    channel_id
                ] = dict(value)

            return {
                "service":
                    "Markiza XMLTV Proxy",

                "host":
                    HOST,

                "port":
                    PORT,

                "timezone":
                    TIMEZONE_NAME,

                "refresh_seconds":
                    REFRESH_SECONDS,

                "ready":
                    self.xml is not None,

                "last_refresh":
                    self.last_refresh,

                "last_success":
                    self.last_success,

                "last_error":
                    self.last_error,

                "channels":
                    channels,
            }


service = XMLTVService()


# ============================================================
# HTTP Handler
# ============================================================

class Handler(
    BaseHTTPRequestHandler
):

    server_version = (
        "MarkizaXMLTV/1.0"
    )

    # --------------------------------------------------------
    # Logging
    # --------------------------------------------------------

    def log_message(
        self,
        format_string,
        *args,
    ):

        log.info(
            "%s - %s",
            self.address_string(),
            format_string % args,
        )

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    def send_json(
        self,
        data,
        status=200,
    ):

        body = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")

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

    # --------------------------------------------------------
    # XML
    # --------------------------------------------------------

    def send_xml(
        self,
        body,
        status=200,
    ):

        self.send_response(
            status
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
            "no-cache",
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
        # XMLTV
        # ----------------------------------------------------

        if path in (
            "/xmltv.xml",
            "/xmltv",
        ):

            with service.lock:
                body = service.xml

            if body is None:

                self.send_json(
                    {
                        "error":
                            "XMLTV not ready",
                    },
                    status=503,
                )

                return

            self.send_xml(
                body
            )

            return

        # ----------------------------------------------------
        # Health
        # ----------------------------------------------------

        if path == "/health":

            with service.lock:

                ready = (
                    service.xml
                    is not None
                )

            if ready:

                self.send_json(
                    {
                        "status":
                            "ok",

                        "ready":
                            True,
                    }
                )

            else:

                self.send_json(
                    {
                        "status":
                            "starting",

                        "ready":
                            False,
                    },
                    status=503,
                )

            return

        # ----------------------------------------------------
        # Status
        # ----------------------------------------------------

        if path == "/status":

            self.send_json(
                service.status()
            )

            return

        # ----------------------------------------------------
        # Manual refresh
        # ----------------------------------------------------

        if path == "/refresh":

            success = (
                service.refresh()
            )

            self.send_json(
                {
                    "success":
                        success,

                    "status":
                        service.status(),
                }
            )

            return

        # ----------------------------------------------------
        # Debug parsed data
        # ----------------------------------------------------

        if path == "/programs":

            with service.lock:

                output = {}

                for channel_id, data in (
                    service.channel_data.items()
                ):

                    output[
                        channel_id
                    ] = {
                        "name":
                            data["name"],

                        "programs": [
                            {
                                "title":
                                    p["title"],

                                "start":
                                    (
                                        p["start"].isoformat()
                                        if p["start"]
                                        else None
                                    ),

                                "end":
                                    (
                                        p["end"].isoformat()
                                        if p["end"]
                                        else None
                                    ),
                            }

                            for p in data[
                                "programs"
                            ]
                        ],
                    }

            self.send_json(
                output
            )

            return

        # ----------------------------------------------------
        # Root
        # ----------------------------------------------------

        if path == "/":

            self.send_json(
                {
                    "service":
                        "Markiza XMLTV Proxy",

                    "xmltv":
                        "/xmltv.xml",

                    "health":
                        "/health",

                    "status":
                        "/status",

                    "programs":
                        "/programs",

                    "refresh":
                        "/refresh",

                    "port":
                        PORT,

                    "channels": {
                        channel_id:
                            config["name"]
                        for (
                            channel_id,
                            config
                        ) in CHANNELS.items()
                    },
                }
            )

            return

        # ----------------------------------------------------
        # 404
        # ----------------------------------------------------

        self.send_json(
            {
                "error":
                    "not found",
            },
            status=404,
        )


# ============================================================
# Main
# ============================================================

def main():

    log.info(
        "Starting Markíza XMLTV proxy"
    )

    log.info(
        "Listen: %s:%d",
        HOST,
        PORT,
    )

    log.info(
        "Refresh: %d seconds",
        REFRESH_SECONDS,
    )

    log.info(
        "Timezone: %s",
        TIMEZONE_NAME,
    )

    for channel_id, config in (
        CHANNELS.items()
    ):

        log.info(
            "Channel %s: %s",
            channel_id,
            config["url"],
        )

    # --------------------------------------------------------
    # Initial refresh
    # --------------------------------------------------------

    try:

        service.refresh()

    except Exception:

        log.exception(
            "Initial refresh failed"
        )

    # --------------------------------------------------------
    # Background refresh
    # --------------------------------------------------------

    thread = threading.Thread(
        target=service.refresh_loop,
        name="markiza-xmltv-refresh",
        daemon=True,
    )

    thread.start()

    # --------------------------------------------------------
    # HTTP server
    # --------------------------------------------------------

    server = ThreadingHTTPServer(
        (
            HOST,
            PORT,
        ),
        Handler,
    )

    log.info(
        "HTTP server listening on %s:%d",
        HOST,
        PORT,
    )

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        log.info(
            "Stopping"
        )

    finally:

        server.server_close()


if __name__ == "__main__":
    main()
