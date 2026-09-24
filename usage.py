"""Keeps count of what Flip does each day (messages, tokens, tools, think mode, and later images,
videos and searches), so limits or credits can be added cleanly if a paid provider is ever used.
Stays on this PC in usage.json; nothing is sent anywhere."""

import json
import logging
import threading
import time

from paths import DATA

log = logging.getLogger("flip")

FILE = DATA / "usage.json"
KEEP_DAYS = 60
_lock = threading.Lock()


def _load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record(tool=None, kind=None, **counts):
    """record(chat=1, read_tokens=900) or record(tool="math") or record(image=1)…"""
    day = time.strftime("%Y-%m-%d")
    with _lock:
        data = _load()
        today = data.setdefault(day, {})
        for k, v in counts.items():
            today[k] = today.get(k, 0) + int(v or 0)
        if tool:
            tools = today.setdefault("tools", {})
            tools[tool] = tools.get(tool, 0) + 1
        if kind:
            kinds = today.setdefault("kinds", {})
            kinds[kind] = kinds.get(kind, 0) + 1
        for old in sorted(data)[:-KEEP_DAYS]:
            del data[old]
        try:
            FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError:
            log.exception("Couldn't save usage")


def today():
    return _load().get(time.strftime("%Y-%m-%d"), {})


def allowed(what):
    """Room for daily limits on expensive things (image/video/search providers). Everything Flip does
    today runs free on this PC, so there's no limit yet."""
    return True
