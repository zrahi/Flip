"""Accounts, profiles, chats and long-term memory, saved as JSON files in Flip's folder.

DATA/accounts.json                           usernames + scrambled passwords
DATA/accounts/<account>/profiles.json        the profiles inside that account
DATA/accounts/<account>/<profile>/chats/     that profile's chats
DATA/accounts/<account>/<profile>/memory.json
"""

import hashlib
import hmac
import json
import os
import re
import shutil
import threading
import time
import uuid

from paths import DATA

ACCOUNTS_FILE = DATA / "accounts.json"
ACCOUNTS = DATA / "accounts"
ACCOUNTS.mkdir(exist_ok=True)
COLORS = ["#5ff0b8", "#ff5e87", "#6c5ce7", "#ffb84d", "#4dc3ff", "#c56cf0"]
MAX_TRIES = 5          # wrong passwords before a lockout
LOCKOUT_SEC = 60

_lock = threading.Lock()
_tries = {}            # username -> (wrong attempts, locked until)
account = None         # the account that's logged in
PROFILES_FILE = None   # set by use_account()
current = None         # the profile that's chatting
CHATS = None           # set by use_profile()
MEMORY_FILE = None


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _hash(secret, salt):
    """Scrambles a password/PIN so it can be checked but never read back."""
    return hashlib.pbkdf2_hmac("sha256", str(secret).encode(), bytes.fromhex(salt), 200_000).hex()


def _matches(secret, salt, stored):
    return hmac.compare_digest(_hash(secret, salt), stored)


# ---------- accounts ----------

def accounts():
    return _read(ACCOUNTS_FILE, [])


def get_account(account_id):
    return next((a for a in accounts() if a["id"] == account_id), None)


def create_account(username, password):
    username = str(username).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.]{3,20}", username):
        raise ValueError("username: 3-20 letters, numbers, _ or .")
    if len(str(password)) < 6:
        raise ValueError("password needs at least 6 characters")
    with _lock:
        all_ = accounts()
        if any(a["username"].lower() == username.lower() for a in all_):
            raise ValueError("that username's taken")
        salt = os.urandom(16).hex()
        acct = {"id": uuid.uuid4().hex[:10], "username": username, "salt": salt,
                "password": _hash(password, salt), "created": time.time()}
        all_.append(acct)
        _write(ACCOUNTS_FILE, all_)
    return acct


def login(username, password):
    """Returns the account, or raises ValueError with a message to show."""
    key = str(username).strip().lower()
    count, until = _tries.get(key, (0, 0))
    if time.time() < until:
        raise ValueError(f"too many wrong tries, wait {int(until - time.time()) + 1}s ⏳")
    acct = next((a for a in accounts() if a["username"].lower() == key), None)
    if acct and _matches(password, acct["salt"], acct["password"]):
        _tries.pop(key, None)
        return acct
    count += 1
    _tries[key] = (0, time.time() + LOCKOUT_SEC) if count >= MAX_TRIES else (count, 0)
    raise ValueError("wrong username or password 🙅")


def change_password(acct_id, old, new):
    with _lock:
        all_ = accounts()
        acct = next((a for a in all_ if a["id"] == acct_id), None)
        if not acct or not _matches(old, acct["salt"], acct["password"]):
            raise ValueError("current password is wrong 🙅")
        if len(str(new)) < 6:
            raise ValueError("new password needs at least 6 characters")
        acct["salt"] = os.urandom(16).hex()
        acct["password"] = _hash(new, acct["salt"])
        _write(ACCOUNTS_FILE, all_)


def use_account(acct):
    global account, PROFILES_FILE, current, CHATS, MEMORY_FILE
    folder = ACCOUNTS / acct["id"]
    folder.mkdir(parents=True, exist_ok=True)
    account = acct
    PROFILES_FILE = folder / "profiles.json"
    current = CHATS = MEMORY_FILE = None


def log_out():
    global account, PROFILES_FILE, current, CHATS, MEMORY_FILE
    account = PROFILES_FILE = current = CHATS = MEMORY_FILE = None


# ---------- profiles (inside the logged-in account) ----------

def profiles():
    return _read(PROFILES_FILE, []) if PROFILES_FILE else []


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
        salt = os.urandom(16).hex()
        prof = {"id": uuid.uuid4().hex[:10], "name": name, "color": COLORS[len(all_) % len(COLORS)],
                "salt": salt, "pin": _hash(pin, salt) if pin else None, "created": time.time()}
        all_.append(prof)
        _write(PROFILES_FILE, all_)
    return prof


def check_pin(profile_id, pin):
    prof = next((p for p in profiles() if p["id"] == profile_id), None)
    if prof is None:
        return None
    if prof.get("pin") and not _matches(str(pin or ""), prof["salt"], prof["pin"]):
        return None
    return prof


def delete_profile(profile_id):
    with _lock:
        _write(PROFILES_FILE, [p for p in profiles() if p["id"] != profile_id])
    if str(profile_id).isalnum():
        shutil.rmtree(ACCOUNTS / account["id"] / profile_id, ignore_errors=True)


def use_profile(prof):
    global CHATS, MEMORY_FILE, current
    folder = ACCOUNTS / account["id"] / prof["id"]
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
            chats.append({"id": c["id"], "title": c["title"], "updated": c["updated"], "pinned": c.get("pinned", False)})
    return sorted(chats, key=lambda c: c["updated"], reverse=True)


def update_chat(chat_id, title=None, pinned=None):
    chat = load_chat(chat_id)
    if chat is None:
        return None
    if title is not None and title.strip():
        chat["title"] = title.strip()[:60]
    if pinned is not None:
        chat["pinned"] = bool(pinned)
    save_chat(chat)
    return chat


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
