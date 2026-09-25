"""Where Flip's files live.

RES  = files bundled inside Flip.exe (the UI, the default personality, the icon).
DATA = Flip's own folder on the PC (%LOCALAPPDATA%/Flip): settings, chats, memory, brain.
"""

import json
import os
import shutil
import sys
from pathlib import Path

RES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DATA = Path(os.environ.get("FLIP_HOME") or Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local/share") / "Flip")
DATA.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS = {
    "name": "Flip",
    "llm_url": "",
    "local_model": "auto",
    "voice": "am_fenrir",
    "voice_style": "cute",
    "talk_speed": 1.25,
    "mic": None,
    "fast_mode": False,
    "brain_size": "smart",
    "whisper_model": "small.en",
    "roblox_studio": False,
    "roblox_command": ["cmd.exe", "/c", "cd /d %LOCALAPPDATA%\\Roblox && .\\mcp.bat"],
}


def load_settings():
    path = DATA / "settings.json"
    settings = dict(DEFAULT_SETTINGS)
    try:
        settings.update(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    settings.setdefault("version", 1)
    if settings["version"] < 2:  # v2: cute voice by default, set by voice_style
        settings["voice_style"] = "cute"
        settings.pop("voice_pitch", None)
        settings.pop("voice_rate", None)
    if settings["version"] < 3:  # v3: he's a Valorant buddy now; Roblox Studio is opt-in; his own voice
        settings["roblox_studio"] = False
        settings["voice"] = "am_fenrir"
        settings["voice_style"] = "cute"
        if settings.get("whisper_model") in (None, "base.en"):
            settings["whisper_model"] = "small.en"
    if settings["version"] < 4:  # v4: he talks quicker by default (the old "normal" was slow)
        old = float(settings.get("talk_speed") or 1.0)
        settings["talk_speed"] = 1.25 if old <= 1.0 else 1.4 if old <= 1.2 else 1.6
    settings["version"] = 4
    save_settings(settings)
    return settings


def save_settings(settings):
    (DATA / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")


# Built-in personalities from older versions. If the user's copy still matches one of these (they never
# edited it), it gets replaced with the current one.
OLD_PERSONALITIES = {"983d810d0cc7a85b4706fc91bf2319939159c5b6db68aa6a71b26f04f314f527", "43d7f08c483b5c903222d1296314c0d7992e135ce2153128ff6f84ccd40db0b5", "090aa848a946667765efac095a60f25dafae3c31b2a33bf7535e25c21de2e75b", "0b50b6e2053d1440abca7f95a61ff34d86195f3511ba27d238f8a53f9ba9e81c", "5972ed76d7f743c21d5b2aa53f2604ba223b31e514d0757a896a8231d54c4d02", "abef6351e80dae97bb00812ddda0568e0c4c60265c1c0d33ac409472316e8314", "d8461125a4037efd6146eb2656a6e3f58ebe5f2ff4e00009611c478131998f99"}


def personality_file():
    import hashlib

    path = DATA / "personality.txt"
    if path.exists():
        current = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if current in OLD_PERSONALITIES:
            path.unlink()
    if not path.exists():
        shutil.copy(RES / "personality.txt", path)
    return path
