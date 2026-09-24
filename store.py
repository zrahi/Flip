"""Profiles, chats and long-term memory, saved as JSON files in Flip's folder.

Every profile has its own chats and memory: DATA/profiles/<id>/chats/ and memory.json.
"""

import hashlib
import json
import os
import threading
import time
import uuid

from paths import DATA

PROFILES = DATA / "profiles"
PROFILES.mkdir(exist_ok=True)
PROFILES_FILE = DATA / "profiles.json"
COLORS = ["#5ff0b8", "#ff5e87", "#6c5ce7", "#ffb84d", "#4dc3ff", "#c56cf0"]

_lock = threading.Lock()
CHATS = None        # set by use_profile()
MEMORY_FILE = None
current = None      # the profile that's logged in


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ---------- profiles ----------

def _hash(pin, salt):
    return hashlib.sha256((salt + pin).encode()).hexdigest()


def profiles():
    return _read(PROFILES_FILE, [])


def public_profiles():
    return [{"id": p["id"], "name": p["name"], "color": p["color"], "has_pin": bool(p.get("pin"))} for p in profiles()]


def create_profile(name, pin=""):
    name = " ".join(str(name).split())[:24]
    if not name:
        raise ValueError("pick a name")
    pin = str(pin or "").strip()
    if pin and (not pin.isdigit() or not 4 <= len(pin) <= 8):
        raise ValueError("PIN has to be 4 to 8 numbers")
    with _lock:
        all_ = profiles()
        if any(p["name"].lower() == name.lower() for p in all_):
            raise ValueError("that name's taken")
        salt = os.urandom(8).hex()
        prof = {"id": uuid.uuid4().hex[:10], "name": name, "color": COLORS[len(all_) % len(COLORS)],
                "salt": salt, "pin": _hash(pin, salt) if pin else None, "created": time.time()}
        all_.append(prof)
        _write(PROFILES_FILE, all_)
    return prof


def check_pin(profile_id, pin):
    prof = next((p for p in profiles() if p["id"] == profile_id), None)
    if prof is None:
        return None
    if prof.get("pin") and _hash(str(pin or ""), prof["salt"]) != prof["pin"]:
        return None
    return prof


def delete_profile(profile_id):
    import shutil

    with _lock:
        _write(PROFILES_FILE, [p for p in profiles() if p["id"] != profile_id])
    if str(profile_id).isalnum():
        shutil.rmtree(PROFILES / profile_id, ignore_errors=True)


def use_profile(prof):
    global CHATS, MEMORY_FILE, current
    folder = PROFILES / prof["id"]
    CHATS = folder / "chats"
    CHATS.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE = folder / "memory.json"
    current = prof


# ---------- chats ----------

def list_chats():
    chats = []
    for f in CHATS.glob("*.json"):
        c = _read(f, None)
        if c:
            chats.append({"id": c["id"], "title": c["title"], "updated": c["updated"]})
    return sorted(chats, key=lambda c: c["updated"], reverse=True)


def new_chat(chat_id=None):
    """A fresh chat. It only gets saved once there's a message in it."""
    now = time.time()
    return {"id": chat_id or uuid.uuid4().hex[:12], "title": "New chat", "created": now, "updated": now, "messages": []}


def load_chat(chat_id):
    if not str(chat_id).isalnum():
        return None
    return _read(CHATS / f"{chat_id}.json", None)


def save_chat(chat):
    with _lock:
        _write(CHATS / f"{chat['id']}.json", chat)


def delete_chat(chat_id):
    if not str(chat_id).isalnum():
        return
    (CHATS / f"{chat_id}.json").unlink(missing_ok=True)


def title_from(text):
    text = " ".join(text.split())
    return text if len(text) <= 40 else text[:38].rstrip() + "…"


# ---------- memory ----------

def memories():
    return _read(MEMORY_FILE, [])


def remember(text):
    text = " ".join(str(text).split())
    if not text:
        return None
    with _lock:
        mems = memories()
        if any(m["text"].lower() == text.lower() for m in mems):
            return None
        mem = {"id": uuid.uuid4().hex[:6], "text": text, "created": time.time()}
        mems.append(mem)
        _write(MEMORY_FILE, mems)
    return mem


def forget(mem_id):
    with _lock:
        mems = memories()
        left = [m for m in mems if m["id"] != mem_id]
        _write(MEMORY_FILE, left)
    return len(left) != len(mems)
