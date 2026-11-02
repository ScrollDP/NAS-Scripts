#!/usr/bin/env python3

import base64
import logging
import re
import ssl
import os

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin, urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError


# ============================================================
# CONFIGURATION
# ============================================================

HOST = os.environ.get(
    "MARKIZA_HOST",
    "127.0.0.1",
)

PORT = int(
    os.environ.get(
        "MARKIZA_PORT",
        "8763",
    )
)

DEFAULT_QUALITY = os.environ.get(
    "MARKIZA_QUALITY",
    "hq",
).lower()


# ============================================================
# CHANNEL CONFIGURATION
# ============================================================

CHANNELS = {
    "markiza": {
        "name": "Markíza",
        "page": "https://www.markiza.sk/live/1-markiza",
        "quality": os.environ.get(
            "MARKIZA_MARKIZA_QUALITY",
            DEFAULT_QUALITY,
        ).lower(),
    },

    "dajto": {
        "name": "Dajto",
        "page": "https://www.markiza.sk/live/2-dajto",
        "quality": os.environ.get(
            "MARKIZA_DAJTO_QUALITY",
            DEFAULT_QUALITY,
        ).lower(),
    },

    "doma": {
        "name": "Doma",
        "page": "https://www.markiza.sk/live/3-doma",
        "quality": os.environ.get(
            "MARKIZA_DOMA_QUALITY",
            DEFAULT_QUALITY,
        ).lower(),
    },

    "krimi": {
        "name": "Krimi",
        "page": "https://www.markiza.sk/live/22-krimi",
        "quality": os.environ.get(
            "MARKIZA_KRIMI_QUALITY",
            DEFAULT_QUALITY,
        ).lower(),
    },

    "klasik": {
        "name": "Klasik",
        "page": "https://www.markiza.sk/live/44-klasik",
        "quality": os.environ.get(
            "MARKIZA_KLASIK_QUALITY",
            DEFAULT_QUALITY,
        ).lower(),
    },
}


# ============================================================
# COMMON MARKÍZA SETTINGS
# ============================================================

MARKIZA_BASE = "https://www.markiza.sk/"
REFERER = "https://www.markiza.sk/"
ORIGIN = "https://www.markiza.sk"

USER_AGENT = "Mozilla/5.0"


QUALITIES = {
    "lq": "640x360",
    "mq": "768x432",
    "hq": "1024x576",
    "hd": "1280x720",
    "fullhd": "1920x1080",
}


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)

logger = logging.getLogger("markiza-proxy")


# ============================================================
# SSL
# ============================================================

UPSTREAM_SSL_CONTEXT = ssl.create_default_context()

UPSTREAM_SSL_CONTEXT.set_ciphers(
    "DEFAULT:@SECLEVEL=1"
)


# ============================================================
# HTTP GET
# ============================================================

def http_get(
    url,
    timeout=15,
    referer=None,
    origin=None,
):

    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": referer or REFERER,
            "Origin": origin or ORIGIN,
            "Accept": "*/*",
        },
    )

    with urlopen(
        req,
        timeout=timeout,
        context=UPSTREAM_SSL_CONTEXT,
    ) as response:

        return (
            response.read(),
            response.headers.get(
                "Content-Type",
                "",
            ),
        )


# ============================================================
# RESOLVE CURRENT STREAM
# ============================================================

def resolve_stream(channel_id):

    channel = CHANNELS.get(channel_id)

    if not channel:
        raise RuntimeError(
            f"Unknown channel: {channel_id}"
        )

    channel_name = channel["name"]
    channel_page = channel["page"]

    logger.info(
        "Fetching %s channel page: %s",
        channel_name,
        channel_page,
    )

    page_data, _ = http_get(
        channel_page
    )

    html = page_data.decode(
        "utf-8",
        errors="replace",
    )

    # --------------------------------------------------------
    # Preferred: player PageData source
    # --------------------------------------------------------

    match = re.search(
        r'"sources"\s*:\s*\[\s*\{\s*"src"\s*:\s*'
        r'"([^"]+\.m3u8(?:\?[^"]*)?)"',
        html,
    )

    if match:

        master = match.group(1)

        logger.info(
            "%s: resolved signed master URL",
            channel_name,
        )

        logger.info(
            "%s master: %s",
            channel_name,
            master,
        )

        return master

    # --------------------------------------------------------
    # Fallback: search entire page for m3u8
    # --------------------------------------------------------

    matches = re.findall(
        r'https?://[^"\']+\.m3u8(?:\?[^"\']*)?',
        html,
    )

    if matches:

        master = matches[0]

        logger.info(
            "%s: resolved master using fallback",
            channel_name,
        )

        logger.info(
            "%s master: %s",
            channel_name,
            master,
        )

        return master

    # --------------------------------------------------------
    # Diagnostic: search for embed URL
    # --------------------------------------------------------

    embed_matches = re.findall(
        r'https?://media\.cms\.markiza\.sk/embed/[^"\']+',
        html,
    )

    if embed_matches:

        embed_url = embed_matches[0]

        logger.info(
            "%s: found Markíza embed: %s",
            channel_name,
            embed_url,
        )

        embed_data, _ = http_get(
            embed_url
        )

        embed_html = embed_data.decode(
            "utf-8",
            errors="replace",
        )

        match = re.search(
            r'"sources"\s*:\s*\[\s*\{\s*"src"\s*:\s*'
            r'"([^"]+\.m3u8(?:\?[^"]*)?)"',
            embed_html,
        )

        if match:

            master = match.group(1)

            logger.info(
                "%s: resolved master from embed",
                channel_name,
            )

            logger.info(
                "%s master: %s",
                channel_name,
                master,
            )

            return master

    raise RuntimeError(
        f"No m3u8 URL found for {channel_name} "
        f"on {channel_page}"
    )


# ============================================================
# SELECT VARIANT
# ============================================================

def choose_variant(
    master_url,
    quality,
    channel_name,
):

    data, _ = http_get(
        master_url,
        referer="https://media.cms.markiza.sk/",
        origin="https://media.cms.markiza.sk",
    )

    text = data.decode(
        "utf-8",
        errors="replace",
    )

    # Already a media playlist.
    if "#EXT-X-STREAM-INF" not in text:

        return master_url

    target_resolution = QUALITIES.get(
        quality
    )

    lines = text.splitlines()

    selected_url = None
    selected_bandwidth = None

    current_inf = None

    variants = []

    for line in lines:

        line = line.strip()

        if line.startswith(
            "#EXT-X-STREAM-INF:"
        ):

            current_inf = line
            continue

        if (
            current_inf
            and line
            and not line.startswith("#")
        ):

            variant_url = urljoin(
                master_url,
                line,
            )

            resolution_match = re.search(
                r"RESOLUTION=(\d+x\d+)",
                current_inf,
            )

            bandwidth_match = re.search(
                r"BANDWIDTH=(\d+)",
                current_inf,
            )

            resolution = (
                resolution_match.group(1)
                if resolution_match
                else None
            )

            bandwidth = (
                int(bandwidth_match.group(1))
                if bandwidth_match
                else 0
            )

            variant = {
                "url": variant_url,
                "resolution": resolution,
                "bandwidth": bandwidth,
            }

            variants.append(
                variant
            )

            if resolution == target_resolution:

                selected_url = variant_url
                selected_bandwidth = bandwidth

            current_inf = None

    if not variants:

        raise RuntimeError(
            f"No variants found in {channel_name} "
            "master playlist"
        )

    # --------------------------------------------------------
    # Requested quality not available.
    # Fall back to highest bandwidth.
    # --------------------------------------------------------

    if selected_url is None:

        selected = max(
            variants,
            key=lambda x: x["bandwidth"],
        )

        selected_url = selected["url"]

        selected_bandwidth = (
            selected["bandwidth"]
        )

        logger.warning(
            "%s: requested quality %s (%s) "
            "not found; using %s",
            channel_name,
            quality,
            target_resolution,
            selected["resolution"],
        )

    logger.info(
        "%s: selected quality=%s bandwidth=%s",
        channel_name,
        quality,
        selected_bandwidth,
    )

    return selected_url


# ============================================================
# URL ENCODING
# ============================================================

def encode_url(url):

    return base64.urlsafe_b64encode(
        url.encode("utf-8")
    ).decode("ascii").rstrip("=")


def decode_url(value):

    padding = "=" * (
        -len(value) % 4
    )

    return base64.urlsafe_b64decode(
        value + padding
    ).decode("utf-8")


# ============================================================
# PROXY URL
# ============================================================

def proxy_url(url):

    encoded = encode_url(
        url
    )

    path = urlparse(
        url
    ).path.lower()

    if path.endswith(".m3u8"):

        return (
            "/p/"
            + encoded
            + ".m3u8"
        )

    if path.endswith(".ts"):

        return (
            "/p/"
            + encoded
            + ".ts"
        )

    if path.endswith(".m4s"):

        return (
            "/p/"
            + encoded
            + ".m4s"
        )

    if path.endswith(".mp4"):

        return (
            "/p/"
            + encoded
            + ".mp4"
        )

    return (
        "/p/"
        + encoded
    )


# ============================================================
# PLAYLIST REWRITING
# ============================================================

def rewrite_playlist(
    playlist,
    base_url,
):

    output = []

    uri_attribute_re = re.compile(
        r'URI="([^"]+)"'
    )

    for line in playlist.splitlines():

        # ----------------------------------------------------
        # URI="..." attributes
        # ----------------------------------------------------

        if 'URI="' in line:

            def replace_uri(match):

                original = match.group(1)

                absolute = urljoin(
                    base_url,
                    original,
                )

                return (
                    f'URI="{proxy_url(absolute)}"'
                )

            line = uri_attribute_re.sub(
                replace_uri,
                line,
            )

            output.append(
                line
            )

            continue

        # ----------------------------------------------------
        # Playlist URI line
        # ----------------------------------------------------

        if (
            line
            and not line.startswith("#")
        ):

            absolute = urljoin(
                base_url,
                line,
            )

            output.append(
                proxy_url(
                    absolute
                )
            )

            continue

        output.append(
            line
        )

    return (
        "\n".join(output)
        + "\n"
    )


# ============================================================
# HANDLER
# ============================================================

class Handler(
    BaseHTTPRequestHandler
):

    protocol_version = "HTTP/1.1"

    def log_message(
        self,
        fmt,
        *args,
    ):

        logger.info(
            "%s - %s",
            self.address_string(),
            fmt % args,
        )

    def send_text(
        self,
        status,
        text,
        content_type="text/plain",
    ):

        body = text.encode(
            "utf-8"
        )

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.send_header(
            "Cache-Control",
            "no-store, no-cache, must-revalidate",
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    # ========================================================
    # GET
    # ========================================================

    def do_GET(self):

        parsed = urlparse(
            self.path
        )

        path = parsed.path

        # ====================================================
        # HEALTH
        # ====================================================

        if path == "/health":

            self.send_text(
                200,
                "OK - Markíza proxy\n",
            )

            return

        # ====================================================
        # STATUS
        # ====================================================

        if path == "/status":

            lines = [
                "Markíza unified proxy",
                f"host={HOST}",
                f"port={PORT}",
                "",
            ]

            for channel_id, config in CHANNELS.items():

                lines.append(
                    f"{channel_id}: "
                    f"{config['name']} "
                    f"quality={config['quality']} "
                    f"page={config['page']}"
                )

            self.send_text(
                200,
                "\n".join(lines) + "\n",
            )

            return

        # ====================================================
        # ROOT
        # ====================================================

        if path == "/":

            lines = [
                "Markíza unified proxy",
                "",
                "Channels:",
            ]

            for channel_id, config in CHANNELS.items():

                lines.append(
                    f"/{channel_id} "
                    f"({config['name']})"
                )

            lines.extend([
                "",
                "/health",
                "/status",
            ])

            self.send_text(
                200,
                "\n".join(lines) + "\n",
            )

            return

        # ====================================================
        # CHANNEL
        # ====================================================

        if path.startswith("/"):

            channel_id = path[1:].strip("/").lower()

            if channel_id in CHANNELS:

                params = parse_qs(
                    parsed.query
                )

                configured_quality = (
                    CHANNELS[channel_id]["quality"]
                )

                quality = params.get(
                    "quality",
                    [configured_quality],
                )[0].lower()

                if quality not in QUALITIES:

                    self.send_text(
                        400,
                        f"Invalid quality: {quality}\n",
                    )

                    return

                channel_name = (
                    CHANNELS[channel_id]["name"]
                )

                try:

                    # ------------------------------------------------
                    # Resolve current signed master.
                    # ------------------------------------------------

                    master_url = resolve_stream(
                        channel_id
                    )

                    # ------------------------------------------------
                    # Select requested variant.
                    # ------------------------------------------------

                    variant_url = choose_variant(
                        master_url,
                        quality,
                        channel_name,
                    )

                    # ------------------------------------------------
                    # Redirect client to proxy playlist.
                    # ------------------------------------------------

                    proxy_playlist = proxy_url(
                        variant_url
                    )

                    self.send_response(
                        302
                    )

                    self.send_header(
                        "Location",
                        proxy_playlist,
                    )

                    self.send_header(
                        "Cache-Control",
                        "no-store",
                    )

                    self.send_header(
                        "Content-Length",
                        "0",
                    )

                    self.end_headers()

                except Exception as exc:

                    logger.exception(
                        "%s request failed",
                        channel_name,
                    )

                    self.send_text(
                        502,
                        f"{channel_name} resolver error: "
                        f"{exc}\n",
                    )

                return

        # ====================================================
        # CDN PROXY
        # ====================================================

        if path.startswith(
            "/p/"
        ):

            encoded = path[3:]

            # Remove artificial extension.
            for extension in (
                ".m3u8",
                ".ts",
                ".m4s",
                ".mp4",
            ):

                if encoded.endswith(
                    extension
                ):

                    encoded = encoded[
                        :-len(extension)
                    ]

                    break

            try:

                target_url = decode_url(
                    encoded
                )

            except Exception:

                self.send_text(
                    400,
                    "Invalid proxy URL\n",
                )

                return

            try:

                data, content_type = http_get(
                    target_url,
                    timeout=20,
                    referer="https://media.cms.markiza.sk/",
                    origin="https://media.cms.markiza.sk",
                )

                # ------------------------------------------------
                # Rewrite HLS playlists recursively.
                # ------------------------------------------------

                is_playlist = (
                    target_url.lower().endswith(
                        ".m3u8"
                    )
                    or data.startswith(
                        b"#EXTM3U"
                    )
                )

                if is_playlist:

                    text = data.decode(
                        "utf-8",
                        errors="replace",
                    )

                    text = rewrite_playlist(
                        text,
                        target_url,
                    )

                    data = text.encode(
                        "utf-8"
                    )

                    content_type = (
                        "application/vnd.apple.mpegurl"
                    )

                self.send_response(
                    200
                )

                self.send_header(
                    "Content-Type",
                    content_type
                    or "application/octet-stream",
                )

                self.send_header(
                    "Content-Length",
                    str(len(data)),
                )

                self.send_header(
                    "Cache-Control",
                    "no-store",
                )

                self.end_headers()

                self.wfile.write(
                    data
                )

            except HTTPError as exc:

                logger.error(
                    "CDN HTTP error %s for %s",
                    exc.code,
                    target_url,
                )

                self.send_text(
                    exc.code,
                    f"CDN HTTP error "
                    f"{exc.code}\n",
                )

            except Exception as exc:

                logger.exception(
                    "CDN proxy error"
                )

                self.send_text(
                    502,
                    f"CDN proxy error: "
                    f"{exc}\n",
                )

            return

        # ====================================================
        # NOT FOUND
        # ====================================================

        self.send_text(
            404,
            "Not found\n",
        )


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info(
        "Starting unified Markíza proxy "
        "on %s:%s",
        HOST,
        PORT,
    )

    for channel_id, config in CHANNELS.items():

        logger.info(
            "Channel %s: %s | quality=%s | %s",
            channel_id,
            config["name"],
            config["quality"],
            config["page"],
        )

    server = ThreadingHTTPServer(
        (
            HOST,
            PORT,
        ),
        Handler,
    )

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        pass

    finally:

        logger.info(
            "Stopping unified Markíza proxy"
        )

        server.server_close()


if __name__ == "__main__":

    main()
