"""What Flip keeps on the PC, cleaning up what isn't needed, and deleting everything."""

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from paths import DATA

log = logging.getLogger("flip")

# faster-whisper used to download its speech model into the shared Hugging Face cache.
OLD_SPEECH_CACHE = Path.home() / ".cache" / "huggingface" / "hub"


def _size(path):
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _old_speech_dirs():
    return list(OLD_SPEECH_CACHE.glob("models--Systran--faster-whisper-*")) if OLD_SPEECH_CACHE.is_dir() else []


def _running():
    try:
        return json.loads((DATA / "running.json").read_text())
    except (OSError, ValueError):
        return {}


def report():
    """Everything Flip stores, biggest first: [{"what", "gb", "in_use"}], plus the total."""
    from engine import LLAMA_DIRS, MODEL_DIR

    running = _running()
    items = []
    try:
        index = json.loads((MODEL_DIR / "models.json").read_text())
    except (OSError, ValueError):
        index = {}
    for repo, name in index.items():
        f = MODEL_DIR / name
        if f.exists():
            items.append({"what": f"brain: {repo.split('/')[-1].replace('-GGUF', '')}", "bytes": _size(f),
                          "in_use": name == running.get("model")})
    for kind, folder in LLAMA_DIRS.items():
        if folder.exists():
            items.append({"what": f"{'NVIDIA turbo' if kind == 'cuda' else 'Vulkan'} engine", "bytes": _size(folder),
                          "in_use": running.get("kind") in (kind, "cpu" if kind == "vulkan" else None)})
    speech = _size(DATA / "speech") + sum(_size(d) for d in _old_speech_dirs())
    if speech:
        items.append({"what": "ears (speech-to-text)", "bytes": speech, "in_use": True})
    leftovers = sum(_size(f) for f in _leftovers())
    if leftovers:
        items.append({"what": "unfinished downloads + old logs", "bytes": leftovers, "in_use": False})
    chats = _size(DATA / "accounts") + _size(DATA / "accounts.json")
    items.append({"what": "your chats, memory + accounts", "bytes": chats, "in_use": True})
    items.sort(key=lambda i: i["bytes"], reverse=True)
    total = sum(i["bytes"] for i in items)
    freeable = sum(i["bytes"] for i in items if not i["in_use"])
    return {"items": [{"what": i["what"], "gb": round(i["bytes"] / 1e9, 2), "in_use": i["in_use"]} for i in items],
            "total_gb": round(total / 1e9, 2), "freeable_gb": round(freeable / 1e9, 2)}


def _leftovers():
    found = list(DATA.glob("*.part")) + list(DATA.glob("*.zip")) + list((DATA / "models").glob("*.part"))
    for log_name in ("brain.log",):
        f = DATA / log_name
        if f.exists() and f.stat().st_size > 5_000_000:
            found.append(f)
    return found


def clean_up():
    """Deletes the brain and engine that aren't being used, unfinished downloads and big logs.
    Returns how many GB were freed."""
    from engine import LLAMA_DIRS, MODEL_DIR

    before = report()["total_gb"]
    running = _running()
    index_file = MODEL_DIR / "models.json"
    try:
        index = json.loads(index_file.read_text())
    except (OSError, ValueError):
        index = {}
    if running.get("model"):
        for repo, name in list(index.items()):
            if name != running["model"]:
                (MODEL_DIR / name).unlink(missing_ok=True)
                del index[repo]
        index_file.write_text(json.dumps(index, indent=1))
        (MODEL_DIR / "model.json").unlink(missing_ok=True)
    if running.get("kind") in LLAMA_DIRS:
        for kind, folder in LLAMA_DIRS.items():
            if kind != running["kind"]:
                shutil.rmtree(folder, ignore_errors=True)
    for f in _leftovers():
        try:
            if f.suffix == ".log":
                f.write_bytes(b"")
            else:
                f.unlink()
        except OSError:
            pass  # still open by the brain; it'll go next time
    for d in _old_speech_dirs():
        shutil.rmtree(d, ignore_errors=True)
    freed = round(max(0.0, before - report()["total_gb"]), 2)
    log.info("Cleaned up %.2f GB", freed)
    return freed


def delete_everything(delete_app):
    """After Flip closes, a small background command deletes Flip's folder (and the app itself if asked)."""
    if sys.platform != "win32":
        shutil.rmtree(DATA, ignore_errors=True)
        return
    targets = [f'rmdir /s /q "{DATA}"'] + [f'rmdir /s /q "{d}"' for d in _old_speech_dirs()]
    if delete_app and getattr(sys, "frozen", False):
        targets.append(f'del /f /q "{sys.executable}"')
    # wait a few seconds so Flip and its brain have fully closed, then delete
    script = "ping 127.0.0.1 -n 6 > nul & taskkill /F /IM llama-server.exe > nul 2>&1 & " + " & ".join(targets)
    subprocess.Popen(["cmd.exe", "/c", script], close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
    log.info("Deleting everything after Flip closes (app too: %s)", delete_app)
