"""Chats and long-term memory, saved as JSON files in Flip's folder."""

import json
import threading
import time
import uuid

from paths import DATA

CHATS = DATA / "chats"
CHATS.mkdir(exist_ok=True)
MEMORY_FILE = DATA / "memory.json"

_lock = threading.Lock()


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


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
