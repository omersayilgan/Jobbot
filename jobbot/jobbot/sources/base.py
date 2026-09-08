"""Shared HTTP helpers for every ATS adapter."""
from __future__ import annotations

import html
import re
import time

import requests

_SESSION = requests.Session()
_LAST_CALL: dict[str, float] = {}


def get(url: str, cfg: dict, *, params: dict | None = None,
        accept: str = "application/json", host_delay: float = 0.0):
    """GET with a shared session, timeout, UA and optional per-host throttling."""
    fetch = cfg.get("fetch", {})
    if host_delay:
        host = url.split("/")[2] if "//" in url else url
        elapsed = time.time() - _LAST_CALL.get(host, 0.0)
        if elapsed < host_delay:
            time.sleep(host_delay - elapsed)
        _LAST_CALL[host] = time.time()

    return _SESSION.get(
        url,
        params=params,
        timeout=fetch.get("request_timeout", 20),
        headers={
            "User-Agent": fetch.get("user_agent", "jobbot/1.0"),
            "Accept": accept,
        },
    )


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


def strip_html(raw: str | None) -> str:
    """ATS descriptions arrive as HTML (often double-escaped). Flatten to text."""
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", text, flags=re.I)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()
