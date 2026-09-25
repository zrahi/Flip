"""A global shortcut that starts or ends a voice call from anywhere, even mid-game (default Ctrl+Alt+V).

It uses Windows' own hotkey registration (RegisterHotKey, like Discord's push-to-talk), so it never
touches the game. Change it in settings.json ("voice_hotkey", e.g. "ctrl+shift+f9"); "" turns it off.
"""

import ctypes
import logging
import re
import sys
import threading

log = logging.getLogger("flip")

MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
NAMED = {"space": 0x20, "tab": 0x09, "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
         "pause": 0x13, "backquote": 0xC0, "`": 0xC0}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312


def parse(combo):
    """"ctrl+alt+v" → (modifier flags, virtual key code). Raises ValueError for something it can't use."""
    mods, key = 0, None
    for part in (p.strip().lower() for p in str(combo).split("+") if p.strip()):
        if part in MODIFIERS:
            mods |= MODIFIERS[part]
        elif len(part) == 1 and part.isalnum():
            key = ord(part.upper())
        elif re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", part):
            key = 0x70 + int(part[1:]) - 1
        elif part in NAMED:
            key = NAMED[part]
        else:
            raise ValueError(f"unknown key {part!r}")
    if key is None:
        raise ValueError("no key in the shortcut")
    if not mods and not 0x70 <= key <= 0x87:
        raise ValueError("a letter on its own would stop working everywhere else; add ctrl, alt or shift")
    return mods, key


def pretty(combo):
    return "+".join(p.strip().capitalize() if len(p.strip()) > 1 else p.strip().upper() for p in str(combo).split("+"))


def start(combo, on_press):
    """Listens for the shortcut on its own thread. Returns False if it can't (not Windows, or a bad combo)."""
    if sys.platform != "win32" or not combo:
        return False
    try:
        mods, key = parse(combo)
    except ValueError as e:
        log.warning("Voice shortcut %r not used: %s", combo, e)
        return False

    def loop():
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, key):
            log.warning("Couldn't set up the voice shortcut %s (another app already uses it?)", combo)
            return
        log.info("Voice shortcut ready: %s", combo)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    on_press()
                except Exception:
                    log.exception("Voice shortcut failed")
        user32.UnregisterHotKey(None, 1)

    threading.Thread(target=loop, daemon=True).start()
    return True
