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
    for key, name in index.items():
        f = MODEL_DIR / name if name else None
        if f and f.exists():
            repo, _, eyes = key.partition("#")
            label = repo.split('/')[-1].replace('-GGUF', '')
            in_use = (index.get(repo) if eyes else name) == running.get("model")
            items.append({"what": f"{'eyes for ' if eyes else 'brain: '}{label}", "bytes": _size(f), "in_use": in_use})
    for kind, folder in LLAMA_DIRS.items():
        if folder.exists():
            items.append({"what": f"{'NVIDIA turbo' if kind == 'cuda' else 'Vulkan'} engine", "bytes": _size(folder),
                          "in_use": running.get("kind") in (kind, "cpu" if kind == "vulkan" else None)})
    speech = _size(DATA / "speech") + sum(_size(d) for d in _old_speech_dirs())
    if speech:
        items.append({"what": "ears (speech-to-text)", "bytes": speech, "in_use": True})
    if (DATA / "voice").exists():
        items.append({"what": "his voice", "bytes": _size(DATA / "voice"), "in_use": True})
    leftovers = sum(_size(f) for f in _leftovers() + _browser_leftovers())
    if leftovers:
        items.append({"what": "caches, leftovers + old logs", "bytes": leftovers, "in_use": False})
    if (DATA / "media").exists():
        items.append({"what": "pictures, videos + files in chats", "bytes": _size(DATA / "media"), "in_use": True})
    chats = _size(DATA / "accounts") + _size(DATA / "accounts.json")
    items.append({"what": "your chats, memory + accounts", "bytes": chats, "in_use": True})
    items.sort(key=lambda i: i["bytes"], reverse=True)
    total = sum(i["bytes"] for i in items)
    freeable = sum(i["bytes"] for i in items if not i["in_use"])
    return {"items": [{"what": i["what"], "gb": round(i["bytes"] / 1e9, 2), "in_use": i["in_use"]} for i in items],
            "total_gb": round(total / 1e9, 2), "freeable_gb": round(freeable / 1e9, 2)}


def _old_temp_copies():
    """The old single-file Flip.exe unpacked itself into Temp on every start (~0.4 GB each time), and
    copies stayed behind when it was closed hard. Only Flip's own folders are touched."""
    import tempfile

    current = getattr(sys, "_MEIPASS", None)
    found = []
    for d in Path(tempfile.gettempdir()).glob("_MEI*"):
        if str(d) != current and (d / "flip.ico").exists() and (d / "ui" / "pet.js").exists():
            found.append(d)
    return found


def _browser_leftovers(claim=False):
    """Older versions gave the chat window's browser (WebView2) a fresh temp folder every start, deleted
    only when Flip closed cleanly: after a crash, an update or a hard shutdown it stayed (often 50-200 MB
    each). Now it lives in Flip's folder (see app.main). claim: rename each first, since Windows won't
    rename a folder a running app still has open, so one that's in use (another app's) is left alone."""
    import tempfile

    found = []
    for d in Path(tempfile.gettempdir()).glob("tmp*"):
        try:
            if not (d / "EBWebView").is_dir():
                continue
            if claim and not d.name.endswith("-flipold"):
                d = d.rename(d.with_name(d.name + "-flipold"))
            found.append(d)
        except OSError:
            pass  # in use
    return found


def _remove_browser_leftovers():
    for d in _browser_leftovers(claim=True):
        shutil.rmtree(d, ignore_errors=True)


def _old_speech_models():
    """Speech-to-text models older versions used (the current ones are kept by voice.py)."""
    from voice import BACKUP_EARS, CAPTION_EARS, EARS, SPEECH_MODELS

    return [DATA / "speech" / n for n in SPEECH_MODELS
            if n not in (EARS, BACKUP_EARS, CAPTION_EARS) and (DATA / "speech" / n).is_dir()]


def _leftovers():
    found = (list(DATA.glob("*.part")) + list(DATA.glob("*.zip")) + list((DATA / "models").glob("*.part"))
             + list((DATA / "update").glob("*")) + list(DATA.glob("playtest-*.json")) + list((DATA / "tmp").glob("*"))
             + _old_temp_copies() + _old_speech_models())
    for log_name in ("brain.log", "flip.log"):
        f = DATA / log_name
        if f.exists() and f.stat().st_size > 5_000_000:
            found.append(f)
    return found


def _remove_leftovers():
    for f in _leftovers():
        try:
            if f.is_dir():
                shutil.rmtree(f, ignore_errors=True)
            elif f.suffix == ".log":
                f.write_bytes(b"")
            else:
                f.unlink()
        except OSError:
            pass  # still in use; it'll go next time


def tidy_on_start():
    """Runs every time Flip starts: removes leftovers nobody needs (not half-finished downloads:
    those get resumed)."""
    try:
        for d in _old_temp_copies() + _old_speech_dirs():
            shutil.rmtree(d, ignore_errors=True)
        for f in (DATA / "update").glob("*"):
            f.unlink(missing_ok=True)
        _remove_browser_leftovers()
    except Exception:
        log.exception("Tidy-up failed")


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
        for key, name in list(index.items()):
            repo = key.partition("#")[0]
            if index.get(repo) != running["model"]:
                if name:
                    (MODEL_DIR / name).unlink(missing_ok=True)
                del index[key]
        index_file.write_text(json.dumps(index, indent=1))
        (MODEL_DIR / "model.json").unlink(missing_ok=True)
    if running.get("kind") in LLAMA_DIRS:
        for kind, folder in LLAMA_DIRS.items():
            if kind != running["kind"]:
                shutil.rmtree(folder, ignore_errors=True)
    _remove_leftovers()
    _remove_browser_leftovers()
    for d in _old_speech_dirs():
        shutil.rmtree(d, ignore_errors=True)
    freed = round(max(0.0, before - report()["total_gb"]), 2)
    log.info("Cleaned up %.2f GB", freed)
    return freed


def delete_everything(delete_app):
    """After Flip closes, a small background command deletes Flip's folder (and uninstalls the app if asked)."""
    if sys.platform != "win32":
        shutil.rmtree(DATA, ignore_errors=True)
        return
    old = _old_speech_dirs() + _old_temp_copies() + _browser_leftovers(claim=True)
    targets = [f'rmdir /s /q "{DATA}"'] + [f'rmdir /s /q "{d}"' for d in old]
    if delete_app and getattr(sys, "frozen", False):
        uninstaller = Path(sys.executable).parent / "unins000.exe"
        if uninstaller.exists():  # installed with FlipSetup: use the real uninstaller
            targets.append(f'"{uninstaller}" /VERYSILENT /SUPPRESSMSGBOXES')
        else:
            targets.append(f'del /f /q "{sys.executable}"')
    # wait a few seconds so Flip and its brain have fully closed, then delete
    script = "ping 127.0.0.1 -n 6 > nul & taskkill /F /IM llama-server.exe > nul 2>&1 & " + " & ".join(targets)
    subprocess.Popen(["cmd.exe", "/c", script], close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
    log.info("Deleting everything after Flip closes (app too: %s)", delete_app)
