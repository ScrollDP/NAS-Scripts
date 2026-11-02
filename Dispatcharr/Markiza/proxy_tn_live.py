#!/usr/bin/env python3

import base64
import json
import logging
import re
import sys
import time
import ssl
import threading

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


HOST = "127.0.0.1"
PORT = 8765

TN_API = "https://tnlive.cms.markiza.sk/api/v2/video/detail"
EMBED_BASE = "https://media.cms.markiza.sk/embed/"
TN_VIDEO_IDS = {
    48: "DsGMde5p69Z",
}

REFERER = "https://tnlive.sk/"
ORIGIN = "https://tnlive.sk"
USER_AGENT = "Mozilla/5.0"

QUALITIES = {
    "lq": "640x360",
    "mq": "768x432",
    "hq": "1024x576",
    "hd": "1280x720",
    "fullhd": "1920x1080",
    "auto": "auto",
}
# Cache the signed CDN variant URL, but NOT the HLS playlist.
# The playlist itself is fetched fresh for every client request.
STREAM_CACHE_TTL = 3600

STREAM_CACHE = {}
STREAM_CACHE_LOCK = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MarkizaTNLive] %(levelname)s %(message)s",
)

logger = logging.getLogger("markiza-tnlive")
# Markiza's key endpoint uses legacy DH parameters that
# Python 3.13/OpenSSL rejects at the default security level.
# Lower the security level only for this upstream connection.
UPSTREAM_SSL_CONTEXT = ssl.create_default_context()
UPSTREAM_SSL_CONTEXT.set_ciphers("DEFAULT:@SECLEVEL=1")


def http_get(url, timeout=15):
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
            "Origin": ORIGIN,
            "Accept": "*/*",
        },
    )

    with urlopen(
        req,
        timeout=timeout,
        context=UPSTREAM_SSL_CONTEXT,
    ) as response:
        return response.read(), response.headers.get("Content-Type", "")


def normalize_video_id(video_id):
    """Accept the new Markiza video ID and the old numeric alias."""
    value = str(video_id).strip()
    if not value:
        raise ValueError("TN Live video ID is empty")
    # Backward compatibility for existing Dispatcharr settings/URLs.
    if value.isdigit() and int(value) in TN_VIDEO_IDS:
        value = TN_VIDEO_IDS[int(value)]
    return value


def resolve_stream(video_id):
    """Resolve the current master HLS URL from Markiza's Video Detail API."""
    video_id = normalize_video_id(video_id)
    api_url = f"{TN_API}?{urlencode({'id': video_id})}"
    logger.info("Resolving Markiza Video Detail API for video ID %s", video_id)

    data, _ = http_get(api_url)
    info = json.loads(data.decode("utf-8"))

    if (info.get("geo") or {}).get("is_blocked", False):
        raise RuntimeError("Stream is geo-blocked")

    streams = info.get("streams") or {}
    master_url = streams.get("hls")
    if not master_url:
        raise RuntimeError(
            "Video Detail API returned no HLS stream "
            f"(video ID {video_id}; keys: {', '.join(sorted(info.keys()))})"
        )

    logger.info("Resolved HLS master playlist for video ID %s", video_id)
    return master_url


def choose_variant_url(master_url, playlist_text, quality="fullhd"):
    variants = []
    lines = playlist_text.splitlines()

    for i, line in enumerate(lines):
        line = line.strip()

        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue

        attrs = line.split(":", 1)[1]
        resolution = None
        bandwidth = 0

        for attr in attrs.split(","):
            key, sep, value = attr.partition("=")
            if not sep:
                continue

            if key == "RESOLUTION":
                resolution = value
            elif key == "BANDWIDTH":
                try:
                    bandwidth = int(value)
                except ValueError:
                    pass

        uri = next(
            (candidate.strip()
             for candidate in lines[i + 1:]
             if candidate.strip()
             and not candidate.strip().startswith("#")),
            None,
        )

        if uri:
            variants.append({
                "url": urljoin(master_url, uri),
                "resolution": resolution,
                "bandwidth": bandwidth,
            })

    if not variants:
        return master_url

    preferred = {
        "lq": "640x360",
        "mq": "768x432",
        "hq": "1024x576",
        "hd": "1280x720",
        "fullhd": "1920x1080",
    }

    target = preferred.get(quality.lower())

    for variant in variants:
        if variant["resolution"] == target:
            return variant["url"]

    return max(variants, key=lambda variant: variant["bandwidth"])["url"]

def get_variant_url(channel_id, quality, force_refresh=False):
    """Return a cached signed HLS URL, resolving the master playlist as needed."""
    video_id = normalize_video_id(channel_id)
    if quality not in QUALITIES:
        raise ValueError(f"Unsupported quality: {quality}")

    cache_key = (video_id, quality)
    now = time.monotonic()

    if not force_refresh:
        with STREAM_CACHE_LOCK:
            cached = STREAM_CACHE.get(cache_key)
            if cached:
                variant_url, cached_at = cached
                age = now - cached_at
                if age < STREAM_CACHE_TTL:
                    logger.info(
                        "Using cached variant video_id=%s quality=%s age=%.1fs",
                        video_id, quality, age,
                    )
                    return variant_url

    logger.info("Resolving new variant video_id=%s quality=%s", video_id, quality)
    master_url = resolve_stream(video_id)

    if quality == "auto":
        variant_url = master_url
    else:
        # Read the real master playlist: rendition URLs are relative to it and
        # may include CDN query parameters/signatures that must be preserved.
        playlist_data, _ = http_get(master_url, timeout=20)
        playlist_text = playlist_data.decode("utf-8", errors="replace")
        variant_url = choose_variant_url(master_url, playlist_text, quality)

    with STREAM_CACHE_LOCK:
        STREAM_CACHE[cache_key] = (variant_url, time.monotonic())

    logger.info("Cached variant video_id=%s quality=%s", video_id, quality)
    return variant_url

def invalidate_variant(channel_id, quality):
    """Remove a cached variant URL."""
    video_id = normalize_video_id(channel_id)
    cache_key = (video_id, quality)
    with STREAM_CACHE_LOCK:
        if cache_key in STREAM_CACHE:
            del STREAM_CACHE[cache_key]
            logger.info("Invalidated variant video_id=%s quality=%s", video_id, quality)


def encode_url(url):
    return base64.urlsafe_b64encode(
        url.encode("utf-8")
    ).decode("ascii").rstrip("=")


def decode_url(value):
    padding = "=" * (-len(value) % 4)

    return base64.urlsafe_b64decode(
        value + padding
    ).decode("utf-8")


def proxy_url(url):
    encoded = encode_url(url)

    path = urlparse(url).path.lower()

    if path.endswith(".m3u8"):
        return "/p/" + encoded + ".m3u8"

    if path.endswith(".ts"):
        return "/p/" + encoded + ".ts"

    if path.endswith(".m4s"):
        return "/p/" + encoded + ".m4s"

    if path.endswith(".mp4"):
        return "/p/" + encoded + ".mp4"

    return "/p/" + encoded


def rewrite_playlist(playlist, base_url):
    """
    Rewrite every HLS URI so the client talks to our proxy.

    Handles:
      - media segments
      - nested playlists
      - EXT-X-KEY
      - EXT-X-MAP
      - other URI= attributes
    """

    output = []

    uri_attribute_re = re.compile(
        r'URI="([^"]+)"'
    )

    for line in playlist.splitlines():

        # URI="..." attributes such as EXT-X-KEY and EXT-X-MAP.
        if "URI=\"" in line:

            def replace_uri(match):
                original = match.group(1)
                absolute = urljoin(base_url, original)
                return f'URI="{proxy_url(absolute)}"'

            line = uri_attribute_re.sub(
                replace_uri,
                line,
            )

            output.append(line)
            continue

        # Playlist URI line.
        if line and not line.startswith("#"):
            absolute = urljoin(base_url, line)
            output.append(proxy_url(absolute))
            continue

        output.append(line)

    return "\n".join(output) + "\n"


def parse_channel_path(path):
    """Parse /tnlive/<video-id>, retaining support for legacy /tnlive/48."""
    match = re.fullmatch(r"/tnlive/([^/]+)", path)
    if not match:
        return None
    try:
        return normalize_video_id(match.group(1))
    except ValueError:
        return None


class Handler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        logger.info(
            "%s - %s",
            self.address_string(),
            fmt % args,
        )

    def send_text(self, status, text, content_type="text/plain"):
        body = text.encode("utf-8")

        self.send_response(status)

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

        self.wfile.write(body)

    def do_GET(self):

        parsed = urlparse(self.path)
        path = parsed.path

        # ---------------------------------------------------------
        # Health check
        # ---------------------------------------------------------

        if path == "/health":
            self.send_text(
                200,
                "OK\n",
            )
            return

        # ---------------------------------------------------------
        # Resolve and serve TN Live
        # ---------------------------------------------------------

        channel_id = parse_channel_path(path)

        if channel_id is not None:

            params = parse_qs(parsed.query)

            quality = params.get(
                "quality",
                ["fullhd"],
            )[0].lower()

            if quality not in QUALITIES:
                self.send_text(
                    400,
                    f"Invalid quality: {quality}\n",
                )
                return

            try:
                variant_url = get_variant_url(
                    channel_id,
                    quality,
                )

                try:

                    data, _ = http_get(
                        variant_url,
                        timeout=20,
                    )

                except HTTPError as exc:

                    if exc.code != 403:
                        raise

                    logger.warning(
                        "Cached variant returned HTTP 403; "
                        "refreshing channel=%s quality=%s",
                        channel_id,
                        quality,
                    )

                    invalidate_variant(
                        channel_id,
                        quality,
                    )

                    variant_url = get_variant_url(
                        channel_id,
                        quality,
                        force_refresh=True,
                    )

                    data, _ = http_get(
                        variant_url,
                        timeout=20,
                    )

                playlist = data.decode(
                    "utf-8",
                    errors="replace",
                )

                rewritten = rewrite_playlist(
                    playlist,
                    variant_url,
                )

                self.send_text(
                    200,
                    rewritten,
                    "application/vnd.apple.mpegurl",
                )

            except Exception as exc:
                logger.exception(
                    "TN Live request failed"
                )

                self.send_text(
                    502,
                    f"TN Live resolver error: {exc}\n",
                )

            return

        # ---------------------------------------------------------
        # Proxy CDN resources
        # ---------------------------------------------------------

        if path.startswith("/p/"):

            encoded = path[3:]

            # We append a real media extension to the local proxy URL
            # so FFmpeg's HLS demuxer recognizes the resource.
            for extension in (
                ".m3u8",
                ".ts",
                ".m4s",
                ".mp4",
            ):
                if encoded.endswith(extension):
                    encoded = encoded[:-len(extension)]
                    break

            try:
                target_url = decode_url(encoded)

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
                )

                # If this is an HLS playlist, rewrite its URLs.
                is_playlist = (
                    target_url.lower().endswith(".m3u8")
                    or data.startswith(b"#EXTM3U")
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

                self.send_response(200)

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

                self.wfile.write(data)

            except HTTPError as exc:

                logger.error(
                    "CDN HTTP error %s for %s",
                    exc.code,
                    target_url,
                )

                self.send_text(
                    exc.code,
                    f"CDN HTTP error {exc.code}\n",
                )

            except Exception as exc:

                logger.exception(
                    "CDN proxy error"
                )

                self.send_text(
                    502,
                    f"CDN proxy error: {exc}\n",
                )

            return

        self.send_text(
            404,
            "Not found\n",
        )


def main():
    logger.info(
        "Starting Markiza TN Live proxy on %s:%s",
        HOST,
        PORT,
    )

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Handler,
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        logger.info("Stopping proxy")
        server.server_close()


if __name__ == "__main__":
    main()
