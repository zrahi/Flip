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
    "voice": "en-US-BrianNeural",
    "voice_rate": "+12%",
    "voice_pitch": "+2Hz",
    "whisper_model": "base.en",
    "roblox_studio": True,
    "roblox_command": ["cmd.exe", "/c", "cd /d %LOCALAPPDATA%\\Roblox && .\\mcp.bat"],
}


def load_settings():
    path = DATA / "settings.json"
    settings = dict(DEFAULT_SETTINGS)
    try:
        settings.update(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    save_settings(settings)
    return settings


def save_settings(settings):
    (DATA / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")


def personality_file():
    path = DATA / "personality.txt"
    if not path.exists():
        shutil.copy(RES / "personality.txt", path)
    return path
