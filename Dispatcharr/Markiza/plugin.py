#!/usr/bin/env python3

import json
import logging
import os
import signal
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote

class Plugin:
    name = "Markíza"
    version = "0.6.2"
    description = "TN Live and Markíza HLS proxies with XMLTV TV guide"
    author = "Scroll_DP"


    # ============================================================
    # Paths
    # ============================================================

    PLUGIN_DIR = os.path.dirname(
        os.path.abspath(__file__)
    )

    # ============================================================
    # TN LIVE
    # ============================================================

    PROXY_TN_LIVE_SCRIPT = os.path.join(
        PLUGIN_DIR,
        "proxy_tn_live.py",
    )

    PID_FILE = os.path.join(
        PLUGIN_DIR,
        "tnlive.pid",
    )

    LOG_FILE = os.path.join(
        PLUGIN_DIR,
        "tnlive.log",
    )

    LOCK_FILE = os.path.join(
        PLUGIN_DIR,
        "tnlive.lock",
    )

    PROXY_URL = "http://127.0.0.1:8765"

    # ============================================================
    # TN LIVE XMLTV
    # ============================================================

    PROXY_TN_LIVE_XMLTV_SCRIPT = os.path.join(
        PLUGIN_DIR,
        "proxy_tn_live_xmltv.py",
    )

    XMLTV_PID_FILE = os.path.join(
        PLUGIN_DIR,
        "tnlive_xmltv.pid",
    )

    XMLTV_LOG_FILE = os.path.join(
        PLUGIN_DIR,
        "tnlive_xmltv.log",
    )

    XMLTV_LOCK_FILE = os.path.join(
        PLUGIN_DIR,
        "tnlive_xmltv.lock",
    )

    XMLTV_URL = "http://127.0.0.1:8766"

    # ============================================================
    # MARKÍZA HLS
    #
    # One process handles all five channels:
    #
    #   /markiza
    #   /dajto
    #   /doma
    #   /krimi
    #   /klasik
    #
    # All use the same proxy on port 8763.
    # ============================================================

    PROXY_MARKIZA_SCRIPT = os.path.join(
        PLUGIN_DIR,
        "proxy_markiza.py",
    )

    MARKIZA_PID_FILE = os.path.join(
        PLUGIN_DIR,
        "markiza.pid",
    )

    MARKIZA_LOG_FILE = os.path.join(
        PLUGIN_DIR,
        "markiza.log",
    )

    MARKIZA_LOCK_FILE = os.path.join(
        PLUGIN_DIR,
        "markiza.lock",
    )

    MARKIZA_PROXY_URL = "http://127.0.0.1:8763"

    MARKIZA_PROXY_PORT = 8763

    MARKIZA_CHANNELS = (
        "markiza",
        "dajto",
        "krimi",
        "doma",
        "klasik",
    )

    # ============================================================
    # MARKÍZA XMLTV
    # ============================================================

    PROXY_MARKIZA_XMLTV_SCRIPT = os.path.join(
        PLUGIN_DIR,
        "proxy_markiza_xmltv.py",
    )

    MARKIZA_XMLTV_PID_FILE = os.path.join(
        PLUGIN_DIR,
        "markiza_xmltv.pid",
    )

    MARKIZA_XMLTV_LOG_FILE = os.path.join(
        PLUGIN_DIR,
        "markiza_xmltv.log",
    )

    MARKIZA_XMLTV_LOCK_FILE = os.path.join(
        PLUGIN_DIR,
        "markiza_xmltv.lock",
    )

    MARKIZA_XMLTV_URL = "http://127.0.0.1:8770"

    # ============================================================
    # Defaults
    # ============================================================

    DEFAULT_SETTINGS = {
        # --------------------------------------------------------
        # TN Live
        # --------------------------------------------------------

        "channel_id": "DsGMde5p69Z",
        "quality": "fullhd",

        # --------------------------------------------------------
        # TN Live XMLTV
        # --------------------------------------------------------

        "xmltv_api_url":
            "https://tnlive.sk/api/v1/tnlive/program?channel_id=48",

        "xmltv_channel_id": "tnlive",
        "xmltv_channel_name": "TN Live",
        "xmltv_port": 8766,
        "xmltv_refresh": 300,

        # --------------------------------------------------------
        # Markíza XMLTV
        # --------------------------------------------------------

        "markiza_xmltv_port": 8770,
        "markiza_xmltv_refresh": 300,

        # --------------------------------------------------------
        # Markíza HLS
        # --------------------------------------------------------

        "markiza_quality": "hq",
        "dajto_quality": "hq",
        "krimi_quality": "hq",
        "doma_quality": "hq",
        "klasik_quality": "hq",
    }

    VALID_QUALITIES = (
        "lq",
        "mq",
        "hq",
        "hd",
        "fullhd",
    )

    # ============================================================
    # Dispatcharr fields
    # ============================================================

    QUALITY_OPTIONS = [
        {
            "value": "lq",
            "label": "LQ - 640x360",
        },
        {
            "value": "mq",
            "label": "MQ - 768x432",
        },
        {
            "value": "hq",
            "label": "HQ - 1024x576",
        },
        {
            "value": "hd",
            "label": "HD - 1280x720",
        },
        {
            "value": "fullhd",
            "label": "Full HD - 1920x1080",
        },
    ]

    fields = [
        # ========================================================
        # TN LIVE
        # ========================================================

        {
            "id": "channel_id",
            "label": "TN Live API Video ID",
            "type": "string",
            "default": "DsGMde5p69Z",
        },

        {
            "id": "quality",
            "label": "TN Live Quality",
            "type": "select",
            "default": "fullhd",
            "options": QUALITY_OPTIONS,
        },

        # ========================================================
        # TN LIVE XMLTV
        # ========================================================

        {
            "id": "xmltv_api_url",
            "label": "XMLTV API URL",
            "type": "string",
            "default":
                "https://tnlive.sk/api/v1/tnlive/program?channel_id=48",
        },

        {
            "id": "xmltv_channel_id",
            "label": "XMLTV Channel ID",
            "type": "string",
            "default": "tnlive",
        },

        {
            "id": "xmltv_channel_name",
            "label": "XMLTV Channel Name",
            "type": "string",
            "default": "TN Live",
        },

        {
            "id": "xmltv_port",
            "label": "XMLTV Port",
            "type": "number",
            "default": 8766,
        },

        {
            "id": "xmltv_refresh",
            "label": "XMLTV Refresh",
            "type": "number",
            "default": 300,
        },

        # ========================================================
        # MARKÍZA XMLTV
        # ========================================================

        {
            "id": "markiza_xmltv_port",
            "label": "Markíza XMLTV Port",
            "type": "number",
            "default": 8770,
        },

        {
            "id": "markiza_xmltv_refresh",
            "label": "Markíza XMLTV Refresh",
            "type": "number",
            "default": 300,
        },

        # ========================================================
        # MARKÍZA CHANNEL QUALITIES
        # ========================================================

        {
            "id": "markiza_quality",
            "label": "Markíza Quality",
            "type": "select",
            "default": "hq",
            "options": QUALITY_OPTIONS,
        },

        {
            "id": "dajto_quality",
            "label": "Dajto Quality",
            "type": "select",
            "default": "hq",
            "options": QUALITY_OPTIONS,
        },

        {
            "id": "krimi_quality",
            "label": "Krimi Quality",
            "type": "select",
            "default": "hq",
            "options": QUALITY_OPTIONS,
        },

        {
            "id": "doma_quality",
            "label": "Doma Quality",
            "type": "select",
            "default": "hq",
            "options": QUALITY_OPTIONS,
        },

        {
            "id": "klasik_quality",
            "label": "Klasik Quality",
            "type": "select",
            "default": "hq",
            "options": QUALITY_OPTIONS,
        },

        # ========================================================
        # PORT INFORMATION
        # ========================================================

        {
            "id": "ports_info",
            "label": "Proxy Ports",
            "type": "info",
            "description": (
                "TN Live: 8765 | "
                "TN Live XMLTV: 8766 | "
                "Markíza HLS (5 channels): 8763 | "
                "Markíza XMLTV: 8770"
            ),
        },
    ]

    # ============================================================
    # Actions
    # ============================================================

    actions = [
        # ========================================================
        # GENERAL
        # ========================================================

        {
            "id": "apply",
            "label": "Apply Settings",
            "description":
                "Apply the current plugin settings.",
            "button_label": "Apply",
            "button_variant": "filled",
            "button_color": "blue",
        },

        # ========================================================
        # TN LIVE
        # ========================================================

        {
            "id": "test_resolver",
            "label": "Test TN Live Resolver",
            "description":
                "Resolve the current TN Live stream.",
            "button_label": "Test",
            "button_variant": "outline",
            "button_color": "blue",
        },

        {
            "id": "start_proxy",
            "label": "Start TN Live",
            "button_label": "Start",
            "button_variant": "outline",
            "button_color": "green",
        },

        {
            "id": "stop_proxy",
            "label": "Stop TN Live",
            "button_label": "Stop",
            "button_variant": "outline",
            "button_color": "red",
        },

        {
            "id": "restart_proxy",
            "label": "Restart TN Live",
            "button_label": "Restart",
            "button_variant": "outline",
            "button_color": "orange",
        },

        {
            "id": "proxy_status",
            "label": "TN Live Status",
            "button_label": "Status",
            "button_variant": "outline",
            "button_color": "blue",
        },

        # ========================================================
        # TN LIVE XMLTV
        # ========================================================

        {
            "id": "start_xmltv",
            "label": "Start XMLTV",
            "button_label": "Start",
            "button_variant": "outline",
            "button_color": "green",
        },

        {
            "id": "stop_xmltv",
            "label": "Stop XMLTV",
            "button_label": "Stop",
            "button_variant": "outline",
            "button_color": "red",
        },

        {
            "id": "restart_xmltv",
            "label": "Restart XMLTV",
            "button_label": "Restart",
            "button_variant": "outline",
            "button_color": "orange",
        },

        {
            "id": "xmltv_status",
            "label": "XMLTV Status",
            "button_label": "Status",
            "button_variant": "outline",
            "button_color": "blue",
        },

        {
            "id": "test_xmltv",
            "label": "Test XMLTV",
            "button_label": "Test",
            "button_variant": "outline",
            "button_color": "blue",
        },

        {
            "id": "refresh_xmltv",
            "label": "Refresh XMLTV",
            "button_label": "Refresh",
            "button_variant": "outline",
            "button_color": "blue",
        },

        # ========================================================
        # MARKÍZA HLS
        # ========================================================

        {
            "id": "start_markiza",
            "label": "Start Markíza HLS",
            "description":
                "Start the unified Markíza HLS proxy for all five channels.",
            "button_label": "Start",
            "button_variant": "outline",
            "button_color": "green",
        },

        {
            "id": "stop_markiza",
            "label": "Stop Markíza HLS",
            "description":
                "Stop the unified Markíza HLS proxy.",
            "button_label": "Stop",
            "button_variant": "outline",
            "button_color": "red",
        },

        {
            "id": "restart_markiza",
            "label": "Restart Markíza HLS",
            "description":
                "Restart the unified Markíza HLS proxy.",
            "button_label": "Restart",
            "button_variant": "outline",
            "button_color": "orange",
        },

        {
            "id": "markiza_status",
            "label": "Markíza HLS Status",
            "description":
                "Show the status of the unified Markíza HLS proxy.",
            "button_label": "Status",
            "button_variant": "outline",
            "button_color": "blue",
        },

        # ========================================================
        # MARKÍZA XMLTV
        # ========================================================

        {
            "id": "start_markiza_xmltv",
            "label": "Start Markíza XMLTV",
            "button_label": "Start",
            "button_variant": "outline",
            "button_color": "green",
        },

        {
            "id": "stop_markiza_xmltv",
            "label": "Stop Markíza XMLTV",
            "button_label": "Stop",
            "button_variant": "outline",
            "button_color": "red",
        },

        {
            "id": "restart_markiza_xmltv",
            "label": "Restart Markíza XMLTV",
            "button_label": "Restart",
            "button_variant": "outline",
            "button_color": "orange",
        },

        {
            "id": "markiza_xmltv_status",
            "label": "Markíza XMLTV Status",
            "button_label": "Status",
            "button_variant": "outline",
            "button_color": "blue",
        },

        {
            "id": "refresh_markiza_xmltv",
            "label": "Refresh Markíza XMLTV",
            "button_label": "Refresh",
            "button_variant": "outline",
            "button_color": "blue",
        },
    ]

    # ============================================================
    # Logging
    # ============================================================

    def _log(
        self,
        context,
        level,
        message,
    ):
        try:
            logger = logging.getLogger(
                f"plugin-markiza-{context}"
            )

            if not logger.handlers:
                handler = logging.StreamHandler()

                formatter = logging.Formatter(
                    "%(asctime)s [%(name)s] "
                    "%(levelname)s %(message)s"
                )

                handler.setFormatter(
                    formatter
                )

                logger.addHandler(
                    handler
                )

                logger.setLevel(
                    logging.INFO
                )

            getattr(
                logger,
                level,
                logger.info,
            )(message)

        except Exception:
            pass

    # ============================================================
    # Utility
    # ============================================================

    def _valid_quality(
        self,
        value,
        default="hq",
    ):
        value = str(
            value or default
        ).strip().lower()

        if value not in self.VALID_QUALITIES:
            return default

        return value

    def _settings_with_defaults(
        self,
        settings,
    ):
        result = dict(
            self.DEFAULT_SETTINGS
        )

        if isinstance(
            settings,
            dict,
        ):
            result.update(
                settings
            )

        # TN Live API video ID (string, not numeric channel ID).
        video_id = str(
            result.get("channel_id") or ""
        ).strip()

        # Migrate the old default saved by existing installations.
        if video_id in ("", "48"):
            video_id = "DsGMde5p69Z"

        result["channel_id"] = video_id

        result["quality"] = (
            self._valid_quality(
                result.get("quality"),
                "fullhd",
            )
        )

        for channel in self.MARKIZA_CHANNELS:
            key = f"{channel}_quality"

            result[key] = (
                self._valid_quality(
                    result.get(key),
                    "hq",
                )
            )

        try:
            result["xmltv_port"] = int(
                result.get(
                    "xmltv_port",
                    8766,
                )
            )
        except Exception:
            result["xmltv_port"] = 8766

        try:
            result["xmltv_refresh"] = int(
                result.get(
                    "xmltv_refresh",
                    300,
                )
            )
        except Exception:
            result["xmltv_refresh"] = 300

        try:
            result["markiza_xmltv_port"] = int(
                result.get(
                    "markiza_xmltv_port",
                    8770,
                )
            )
        except Exception:
            result["markiza_xmltv_port"] = 8770

        try:
            result["markiza_xmltv_refresh"] = int(
                result.get(
                    "markiza_xmltv_refresh",
                    300,
                )
            )
        except Exception:
            result["markiza_xmltv_refresh"] = 300

        return result

    # ============================================================
    # Process type detection
    # ============================================================

    def _is_non_web_process(self):
        try:
            cmdline = (
                " ".join(
                    open(
                        "/proc/self/cmdline",
                        "rb",
                    )
                    .read()
                    .decode(
                        errors="ignore"
                    )
                    .split("\x00")
                )
                .lower()
            )

            blocked = (
                "celery",
                "beat",
                "worker",
                "migrate",
                "migration",
                "manage.py shell",
            )

            return any(
                item in cmdline
                for item in blocked
            )

        except Exception:
            return False

    # ============================================================
    # Read plugin settings
    # ============================================================

    def _startup_settings(self):
        settings = {}

        try:
            from apps.plugins.models import PluginConfig

            keys = [
                getattr(
                    self,
                    "key",
                    None,
                ),
                "markizatnlive",
                "markiza_tnlive",
            ]

            config = None

            for key in keys:
                if not key:
                    continue

                config = (
                    PluginConfig.objects
                    .filter(
                        key=key
                    )
                    .first()
                )

                if config:
                    break

            if (
                config
                and isinstance(
                    config.settings,
                    dict,
                )
            ):
                settings.update(
                    config.settings
                )

        except Exception as exc:
            self._log(
                "plugin-markiza-startup",
                "warning",
                f"Could not read plugin settings: {exc}",
            )

        return self._settings_with_defaults(
            settings
        )

    # ============================================================
    # PID helpers
    # ============================================================

    def _read_pid(
        self,
        pid_file,
    ):
        try:
            if not os.path.exists(
                pid_file
            ):
                return None

            with open(
                pid_file,
                "r",
            ) as f:
                value = f.read().strip()

            if not value:
                return None

            return int(
                value
            )

        except Exception:
            return None

    def _pid_is_ours(
        self,
        pid,
        script,
    ):
        if not pid:
            return False

        try:
            if not os.path.exists(
                f"/proc/{pid}"
            ):
                return False

            with open(
                f"/proc/{pid}/cmdline",
                "rb",
            ) as f:
                cmdline = (
                    f.read()
                    .decode(
                        errors="ignore"
                    )
                    .replace(
                        "\x00",
                        " ",
                    )
                )

            return (
                os.path.basename(
                    script
                )
                in cmdline
            )

        except Exception:
            return False

    def _remove_pid(
        self,
        pid_file,
    ):
        try:
            if os.path.exists(
                pid_file
            ):
                os.remove(
                    pid_file
                )

        except Exception:
            pass

    # ============================================================
    # Process status
    # ============================================================

    def _process_status(
        self,
        pid_file,
        script,
        health_url=None,
    ):
        pid = self._read_pid(
            pid_file
        )

        running = False

        if pid:
            running = self._pid_is_ours(
                pid,
                script,
            )

        if not running:
            self._remove_pid(
                pid_file
            )

        result = {
            "running": running,
            "pid": (
                pid
                if running
                else None
            ),
            "script": script,
        }

        if health_url:
            result["health"] = (
                self._health_check(
                    health_url
                )
            )

        return result

    # ============================================================
    # Health check
    # ============================================================

    def _health_check(
        self,
        url,
    ):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent":
                        "Dispatcharr-Plugin",
                },
            )

            with urlopen(
                req,
                timeout=5,
            ) as response:

                body = (
                    response.read(
                        4096
                    )
                    .decode(
                        errors="replace"
                    )
                )

                return {
                    "ok": True,
                    "status": response.status,
                    "body": body,
                }

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }

    # ============================================================
    # Generic process start
    # ============================================================

    def _start_process(
        self,
        script,
        pid_file,
        log_file,
        lock_file,
        env=None,
        context="process",
    ):
        existing_pid = self._read_pid(
            pid_file
        )

        if (
            existing_pid
            and self._pid_is_ours(
                existing_pid,
                script,
            )
        ):
            self._log(
                context,
                "info",
                f"Already running with PID {existing_pid}",
            )

            return {
                "ok": True,
                "already_running": True,
                "pid": existing_pid,
            }

        self._remove_pid(
            pid_file
        )

        if not os.path.exists(
            script
        ):
            message = (
                f"Script does not exist: {script}"
            )

            self._log(
                context,
                "error",
                message,
            )

            return {
                "ok": False,
                "error": message,
            }

        try:
            os.makedirs(
                os.path.dirname(
                    log_file
                ),
                exist_ok=True,
            )

        except Exception:
            pass

        process_env = os.environ.copy()

        if env:
            process_env.update(
                {
                    str(k): str(v)
                    for k, v in env.items()
                }
            )

        try:
            log_handle = open(
                log_file,
                "ab",
            )

            process = subprocess.Popen(
                [
                    "python3",
                    script,
                ],
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env=process_env,
                start_new_session=True,
                close_fds=True,
            )

            log_handle.close()

            with open(
                pid_file,
                "w",
            ) as f:
                f.write(
                    str(
                        process.pid
                    )
                )

            try:
                with open(
                    lock_file,
                    "w",
                ) as f:
                    f.write(
                        str(
                            process.pid
                        )
                    )

            except Exception:
                pass

            self._log(
                context,
                "info",
                f"Started PID {process.pid}",
            )

            return {
                "ok": True,
                "pid": process.pid,
            }

        except Exception as exc:
            self._log(
                context,
                "error",
                f"Start failed: {exc}",
            )

            return {
                "ok": False,
                "error": str(exc),
            }

    # ============================================================
    # Generic process stop
    # ============================================================

    def _stop_process(
        self,
        pid_file,
        script,
        lock_file=None,
        context="process",
    ):
        pid = self._read_pid(
            pid_file
        )

        if not pid:
            self._remove_pid(
                pid_file
            )

            if lock_file:
                try:
                    os.remove(
                        lock_file
                    )
                except Exception:
                    pass

            return {
                "ok": True,
                "stopped": False,
                "message": "Not running",
            }

        if not self._pid_is_ours(
            pid,
            script,
        ):
            self._log(
                context,
                "warning",
                f"PID {pid} does not belong to {script}",
            )

            self._remove_pid(
                pid_file
            )

            return {
                "ok": False,
                "error":
                    "PID does not belong to plugin process",
            }

        try:
            os.kill(
                pid,
                signal.SIGTERM,
            )

        except ProcessLookupError:
            pass

        except Exception as exc:
            self._log(
                context,
                "warning",
                f"SIGTERM failed: {exc}",
            )

        for _ in range(20):
            if not os.path.exists(
                f"/proc/{pid}"
            ):
                break

            time.sleep(
                0.1
            )

        if os.path.exists(
            f"/proc/{pid}"
        ):
            try:
                os.kill(
                    pid,
                    signal.SIGKILL,
                )
            except Exception:
                pass

        self._remove_pid(
            pid_file
        )

        if lock_file:
            try:
                os.remove(
                    lock_file
                )
            except Exception:
                pass

        self._log(
            context,
            "info",
            f"Stopped PID {pid}",
        )

        return {
            "ok": True,
            "stopped": True,
            "pid": pid,
        }

    # ============================================================
    # TN LIVE
    # ============================================================

    def _start_proxy(
        self,
        settings,
        context="tnlive",
    ):
        settings = (
            self._settings_with_defaults(
                settings
            )
        )

        env = {
            "TN_CHANNEL_ID":
                settings["channel_id"],

            "TN_QUALITY":
                settings["quality"],
        }

        return self._start_process(
            self.PROXY_TN_LIVE_SCRIPT,
            self.PID_FILE,
            self.LOG_FILE,
            self.LOCK_FILE,
            env=env,
            context=context,
        )

    def _stop_proxy(
        self,
        context="tnlive",
    ):
        return self._stop_process(
            self.PID_FILE,
            self.PROXY_TN_LIVE_SCRIPT,
            self.LOCK_FILE,
            context=context,
        )

    def _proxy_status(self):
        return self._process_status(
            self.PID_FILE,
            self.PROXY_TN_LIVE_SCRIPT,
            self.PROXY_URL + "/health",
        )

    # ============================================================
    # TN LIVE resolver test
    # ============================================================

    def _test_resolver(
        self,
        settings,
    ):
        settings = (
            self._settings_with_defaults(
                settings
            )
        )

        channel_id = settings[
            "channel_id"
        ]

        quality = settings[
            "quality"
        ]

        url = (
            f"{self.PROXY_URL}/tnlive/"
            f"{quote(str(channel_id), safe='')}"
            f"?quality={quote(quality, safe='')}"
        )

        try:
            req = Request(
                url,
                headers={
                    "User-Agent":
                        "Dispatcharr-Plugin",
                },
            )

            with urlopen(
                req,
                timeout=15,
            ) as response:

                body = (
                    response.read(
                        8192
                    )
                    .decode(
                        errors="replace"
                    )
                )

                return {
                    "ok": True,
                    "url": url,
                    "status": response.status,
                    "body": body[:8192],
                }

        except HTTPError as exc:
            return {
                "ok": False,
                "url": url,
                "status": exc.code,
                "error": str(exc),
            }

        except URLError as exc:
            return {
                "ok": False,
                "url": url,
                "error": str(exc),
            }

        except Exception as exc:
            return {
                "ok": False,
                "url": url,
                "error": str(exc),
            }

    # ============================================================
    # TN LIVE XMLTV
    # ============================================================

    def _xmltv_environment(
        self,
        settings,
    ):
        settings = (
            self._settings_with_defaults(
                settings
            )
        )

        return {
            "XMLTV_API_URL":
                settings["xmltv_api_url"],

            "XMLTV_CHANNEL_ID":
                settings["xmltv_channel_id"],

            "XMLTV_CHANNEL_NAME":
                settings["xmltv_channel_name"],

            "XMLTV_PORT":
                settings["xmltv_port"],

            "XMLTV_REFRESH":
                settings["xmltv_refresh"],
        }

    def _start_xmltv(
        self,
        settings,
        context="xmltv",
    ):
        env = self._xmltv_environment(
            settings
        )

        return self._start_process(
            self.PROXY_TN_LIVE_XMLTV_SCRIPT,
            self.XMLTV_PID_FILE,
            self.XMLTV_LOG_FILE,
            self.XMLTV_LOCK_FILE,
            env=env,
            context=context,
        )

    def _stop_xmltv(
        self,
        context="xmltv",
    ):
        return self._stop_process(
            self.XMLTV_PID_FILE,
            self.PROXY_TN_LIVE_XMLTV_SCRIPT,
            self.XMLTV_LOCK_FILE,
            context=context,
        )

    def _xmltv_status(self):
        return self._process_status(
            self.XMLTV_PID_FILE,
            self.PROXY_TN_LIVE_XMLTV_SCRIPT,
            self.XMLTV_URL + "/health",
        )

    # ============================================================
    # TN LIVE XMLTV test
    # ============================================================

    def _test_xmltv(self):
        url = (
            self.XMLTV_URL
            + "/xmltv.xml"
        )

        try:
            req = Request(
                url,
                headers={
                    "User-Agent":
                        "Dispatcharr-Plugin",
                },
            )

            with urlopen(
                req,
                timeout=15,
            ) as response:

                body = (
                    response.read(
                        16384
                    )
                    .decode(
                        errors="replace"
                    )
                )

                return {
                    "ok": True,
                    "url": url,
                    "status": response.status,
                    "body": body[:16384],
                }

        except HTTPError as exc:
            return {
                "ok": False,
                "url": url,
                "status": exc.code,
                "error": str(exc),
            }

        except URLError as exc:
            return {
                "ok": False,
                "url": url,
                "error": str(exc),
            }

        except Exception as exc:
            return {
                "ok": False,
                "url": url,
                "error": str(exc),
            }

    # ============================================================
    # TN LIVE XMLTV refresh
    # ============================================================

    def _refresh_xmltv(self):
        return self._test_xmltv()

    # ============================================================
    # MARKÍZA HLS
    # ============================================================

    def _markiza_environment(
        self,
        settings,
    ):
        settings = (
            self._settings_with_defaults(
                settings
            )
        )

        return {
            "MARKIZA_HOST":
                "127.0.0.1",

            "MARKIZA_PORT":
                self.MARKIZA_PROXY_PORT,

            "MARKIZA_MARKIZA_QUALITY":
                settings["markiza_quality"],

            "MARKIZA_DAJTO_QUALITY":
                settings["dajto_quality"],

            "MARKIZA_KRIMI_QUALITY":
                settings["krimi_quality"],

            "MARKIZA_DOMA_QUALITY":
                settings["doma_quality"],

            "MARKIZA_KLASIK_QUALITY":
                settings["klasik_quality"],
        }

    def _start_markiza(
        self,
        settings,
        context="markiza",
    ):
        env = self._markiza_environment(
            settings
        )

        return self._start_process(
            self.PROXY_MARKIZA_SCRIPT,
            self.MARKIZA_PID_FILE,
            self.MARKIZA_LOG_FILE,
            self.MARKIZA_LOCK_FILE,
            env=env,
            context=context,
        )

    def _stop_markiza(
        self,
        context="markiza",
    ):
        return self._stop_process(
            self.MARKIZA_PID_FILE,
            self.PROXY_MARKIZA_SCRIPT,
            self.MARKIZA_LOCK_FILE,
            context=context,
        )

    def _markiza_status(self):
        return self._process_status(
            self.MARKIZA_PID_FILE,
            self.PROXY_MARKIZA_SCRIPT,
            self.MARKIZA_PROXY_URL + "/health",
        )

    # ============================================================
    # MARKÍZA XMLTV
    # ============================================================

    def _markiza_xmltv_environment(
        self,
        settings,
    ):
        settings = (
            self._settings_with_defaults(
                settings
            )
        )

        return {
            "MARKIZA_XMLTV_PORT":
                settings["markiza_xmltv_port"],

            "MARKIZA_XMLTV_REFRESH_SECONDS":
                settings["markiza_xmltv_refresh"],
        }

    def _start_markiza_xmltv(
        self,
        settings,
        context="markiza-xmltv",
    ):
        env = (
            self._markiza_xmltv_environment(
                settings
            )
        )

        return self._start_process(
            self.PROXY_MARKIZA_XMLTV_SCRIPT,
            self.MARKIZA_XMLTV_PID_FILE,
            self.MARKIZA_XMLTV_LOG_FILE,
            self.MARKIZA_XMLTV_LOCK_FILE,
            env=env,
            context=context,
        )

    def _stop_markiza_xmltv(
        self,
        context="markiza-xmltv",
    ):
        return self._stop_process(
            self.MARKIZA_XMLTV_PID_FILE,
            self.PROXY_MARKIZA_XMLTV_SCRIPT,
            self.MARKIZA_XMLTV_LOCK_FILE,
            context=context,
        )

    def _markiza_xmltv_status(self):
        return self._process_status(
            self.MARKIZA_XMLTV_PID_FILE,
            self.PROXY_MARKIZA_XMLTV_SCRIPT,
            self.MARKIZA_XMLTV_URL + "/health",
        )

    def _test_markiza_xmltv(self):
        url = (
            self.MARKIZA_XMLTV_URL
            + "/xmltv.xml"
        )

        try:
            req = Request(
                url,
                headers={
                    "User-Agent":
                        "Dispatcharr-Plugin",
                },
            )

            with urlopen(
                req,
                timeout=15,
            ) as response:

                body = (
                    response.read(
                        16384
                    )
                    .decode(
                        errors="replace"
                    )
                )

                return {
                    "ok": True,
                    "url": url,
                    "status": response.status,
                    "body": body[:16384],
                }

        except HTTPError as exc:
            return {
                "ok": False,
                "url": url,
                "status": exc.code,
                "error": str(exc),
            }

        except URLError as exc:
            return {
                "ok": False,
                "url": url,
                "error": str(exc),
            }

        except Exception as exc:
            return {
                "ok": False,
                "url": url,
                "error": str(exc),
            }

    def _refresh_markiza_xmltv(self):
        url = (
            self.MARKIZA_XMLTV_URL
            + "/refresh"
        )

        try:
            req = Request(
                url,
                method="GET",
                headers={
                    "User-Agent":
                        "Dispatcharr-Plugin",
                },
            )

            with urlopen(
                req,
                timeout=15,
            ) as response:

                body = (
                    response.read(
                        16384
                    )
                    .decode(
                        errors="replace"
                    )
                )

                return {
                    "ok": True,
                    "url": url,
                    "status": response.status,
                    "body": body[:16384],
                }

        except HTTPError as exc:
            return {
                "ok": False,
                "url": url,
                "status": exc.code,
                "error": str(exc),
            }

        except URLError as exc:
            return {
                "ok": False,
                "url": url,
                "error": str(exc),
            }

        except Exception as exc:
            return {
                "ok": False,
                "url": url,
                "error": str(exc),
            }

    # ============================================================
    # Auto-start
    # ============================================================

    def _auto_start(self):
        if self._is_non_web_process():
            self._log(
                "startup",
                "debug",
                "Skipping auto-start in non-web process",
            )

            return

        try:
            settings = (
                self._startup_settings()
            )

            # ----------------------------------------------------
            # TN Live
            # ----------------------------------------------------

            self._start_proxy(
                settings,
                context="tnlive-auto",
            )

            # ----------------------------------------------------
            # TN Live XMLTV
            # ----------------------------------------------------

            self._start_xmltv(
                settings,
                context="xmltv-auto",
            )

            # ----------------------------------------------------
            # Markíza HLS
            # ----------------------------------------------------

            self._start_markiza(
                settings,
                context="markiza-auto",
            )

            # ----------------------------------------------------
            # Markíza XMLTV
            # ----------------------------------------------------

            self._start_markiza_xmltv(
                settings,
                context="markiza-xmltv-auto",
            )

        except Exception as exc:
            self._log(
                "startup",
                "error",
                f"Auto-start failed: {exc}",
            )

    # ============================================================
    # Plugin init
    # ============================================================

    def __init__(self):
        self._auto_start()

    # ============================================================
    # Plugin shutdown
    # ============================================================

    def stop(self):
        try:
            self._stop_proxy(
                context="tnlive-stop"
            )
        except Exception:
            pass

        try:
            self._stop_xmltv(
                context="xmltv-stop"
            )
        except Exception:
            pass

        try:
            self._stop_markiza(
                context="markiza-stop"
            )
        except Exception:
            pass

        try:
            self._stop_markiza_xmltv(
                context="markiza-xmltv-stop"
            )
        except Exception:
            pass

    # ============================================================
    # Action dispatcher
    # ============================================================

    def run(
        self,
        action_id=None,
        params=None,
        context=None,
        **kwargs,
    ):
        params = params or {}
        context = context or {}

        settings = (
            context.get("settings")
            or {}
        )

        # Compatibility if settings are
        # passed through params.
        if (
            not settings
            and isinstance(
                params.get("settings"),
                dict,
            )
        ):
            settings = params[
                "settings"
            ]

        settings = (
            self._settings_with_defaults(
                settings
            )
        )

        action = action_id

        # ========================================================
        # APPLY
        # ========================================================

        if action == "apply":
            self._stop_proxy(
                context="tnlive-apply"
            )

            self._stop_xmltv(
                context="xmltv-apply"
            )

            self._stop_markiza(
                context="markiza-apply"
            )

            self._stop_markiza_xmltv(
                context="markiza-xmltv-apply"
            )

            time.sleep(
                0.5
            )

            return {
                "tnlive":
                    self._start_proxy(
                        settings,
                        context="tnlive-apply",
                    ),

                "xmltv":
                    self._start_xmltv(
                        settings,
                        context="xmltv-apply",
                    ),

                "markiza":
                    self._start_markiza(
                        settings,
                        context="markiza-apply",
                    ),

                "markiza_xmltv":
                    self._start_markiza_xmltv(
                        settings,
                        context="markiza-xmltv-apply",
                    ),
            }

        # ========================================================
        # TN LIVE
        # ========================================================

        if action == "test_resolver":
            return self._test_resolver(
                settings
            )

        if action == "start_proxy":
            return self._start_proxy(
                settings
            )

        if action == "stop_proxy":
            return self._stop_proxy()

        if action == "restart_proxy":
            self._stop_proxy()

            time.sleep(
                0.5
            )

            return self._start_proxy(
                settings
            )

        if action == "proxy_status":
            return self._proxy_status()

        # ========================================================
        # TN LIVE XMLTV
        # ========================================================

        if action == "start_xmltv":
            return self._start_xmltv(
                settings
            )

        if action == "stop_xmltv":
            return self._stop_xmltv()

        if action == "restart_xmltv":
            self._stop_xmltv()

            time.sleep(
                0.5
            )

            return self._start_xmltv(
                settings
            )

        if action == "xmltv_status":
            return self._xmltv_status()

        if action == "test_xmltv":
            return self._test_xmltv()

        if action == "refresh_xmltv":
            return self._refresh_xmltv()

        # ========================================================
        # MARKÍZA HLS
        # ========================================================

        if action == "start_markiza":
            return self._start_markiza(
                settings
            )

        if action == "stop_markiza":
            return self._stop_markiza()

        if action == "restart_markiza":
            self._stop_markiza()

            time.sleep(
                0.5
            )

            return self._start_markiza(
                settings
            )

        if action == "markiza_status":
            return self._markiza_status()

        # ========================================================
        # MARKÍZA XMLTV
        # ========================================================

        if action == "start_markiza_xmltv":
            return self._start_markiza_xmltv(
                settings
            )

        if action == "stop_markiza_xmltv":
            return self._stop_markiza_xmltv()

        if action == "restart_markiza_xmltv":
            self._stop_markiza_xmltv()

            time.sleep(
                0.5
            )

            return self._start_markiza_xmltv(
                settings
            )

        if action == "markiza_xmltv_status":
            return self._markiza_xmltv_status()

        if action == "refresh_markiza_xmltv":
            return self._refresh_markiza_xmltv()

        # ========================================================
        # UNKNOWN ACTION
        # ========================================================

        return {
            "ok": False,
            "error":
                f"Unknown action: {action}",
        }


    # ================================================================

    # Helper

    # ================================================================

    def json_loads(value):

    #Compatibility helper retained from the original plugin.



        if isinstance(
            value,
            bytes,
        ):
            value = value.decode(
                "utf-8",
                errors="replace",
            )

        if isinstance(
            value,
            str,
        ):
            return json.loads(
                value
            )

        return value
