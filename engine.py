"""Flip's built-in brain.

The first time, it downloads llama.cpp (the program that runs AI models) and the
smartest model the PC's graphics card can handle. After that it just starts it.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

from paths import DATA

log = logging.getLogger("flip")

PORT = 8765
LLAMA_DIR = DATA / "llama"
MODEL_DIR = DATA / "models"
HEADERS = {"User-Agent": "Flip/1.0"}
QUANT = "Q4_K_M"
CONTEXT = "16384"

# (minimum GPU memory in GB, Hugging Face repo). The first one that fits is used.
MODELS = [
    (14, "unsloth/Qwen3-14B-GGUF"),
    (7, "unsloth/Qwen3-8B-GGUF"),
    (0, "unsloth/Qwen3-4B-Instruct-2507-GGUF"),
]
# Fast mode: a smaller brain that answers much quicker.
FAST = {
    "unsloth/Qwen3-14B-GGUF": "unsloth/Qwen3-4B-Instruct-2507-GGUF",
    "unsloth/Qwen3-8B-GGUF": "unsloth/Qwen3-4B-Instruct-2507-GGUF",
    "unsloth/Qwen3-4B-Instruct-2507-GGUF": "unsloth/Qwen3-1.7B-GGUF",
}


def short_name(repo):
    return repo.split("/")[-1].replace("-GGUF", "").replace("-Instruct-2507", "")


def gpu_memory_gb():
    """Biggest graphics card memory on this PC, read from the Windows registry."""
    if sys.platform != "win32":
        return 0.0
    import winreg

    best = 0
    base = r"SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return 0.0
    with root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            name = winreg.EnumKey(root, i)
            if not name.isdigit():
                continue
            try:
                with winreg.OpenKey(root, name) as key:
                    for value in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                        try:
                            size, _ = winreg.QueryValueEx(key, value)
                        except OSError:
                            continue
                        if isinstance(size, bytes):
                            size = int.from_bytes(size[:8], "little")
                        best = max(best, int(size))
                        break
            except OSError:
                continue
    return best / 1024 ** 3


def pick_model(vram_gb):
    return next(repo for min_gb, repo in MODELS if vram_gb >= min_gb)


def _get_json(url):
    headers = dict(HEADERS)
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"  # only set on the build server, avoids rate limits
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return json.load(r)


def model_download(repo):
    """(url, file name, size) of the Q4_K_M model file in a Hugging Face repo."""
    files = _get_json(f"https://huggingface.co/api/models/{repo}/tree/main")
    for f in files:
        path = f.get("path", "")
        if path.lower().endswith(".gguf") and QUANT.lower() in path.lower() and "/" not in path and "mmproj" not in path.lower():
            return f"https://huggingface.co/{repo}/resolve/main/{path}", path, f.get("size", 0)
    raise RuntimeError(f"no {QUANT} model file in {repo}")


def llama_download():
    """(url, size) of the newest llama.cpp Windows build (Vulkan: uses any GPU, falls back to CPU)."""
    releases = _get_json("https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10")
    for release in releases:  # the newest release sometimes doesn't have its files uploaded yet
        assets = release.get("assets", [])
        for kind in ("vulkan", "cpu"):
            for a in assets:
                n = a["name"].lower()
                if n.endswith(".zip") and "bin-win" in n and f"-{kind}-" in n and "x64" in n and not n.startswith("cudart"):
                    return a["browser_download_url"], a["size"]
    names = [a["name"] for r in releases[:2] for a in r.get("assets", [])]
    raise RuntimeError(f"couldn't find llama.cpp for Windows (saw: {names[:30]})")


def download(url, dest, on_progress):
    """Download with resume support, so a dropped connection doesn't start over."""
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = dict(HEADERS)
    if have:
        headers["Range"] = f"bytes={have}-"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        if have and r.status != 206:
            have = 0  # server ignored the resume request
        total = have + int(r.headers.get("Content-Length") or 0)
        with open(part, "ab" if have else "wb") as f:
            done = have
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                on_progress(done, total)
    part.replace(dest)


def _gb(n):
    return f"{n / 1e9:.1f}"


class Engine:
    def __init__(self, settings):
        self._s = settings
        self._proc = None
        self._lock = threading.Lock()
        self.status = {"state": "starting", "title": "waking up…", "detail": "", "progress": None}
        self.url = settings.get("llm_url") or f"http://127.0.0.1:{PORT}/v1"
        self.model_name = ""

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def set_fast(self, on):
        self._s["fast_mode"] = bool(on)
        if self._s.get("llm_url"):
            return
        self._set("loading", "switching brains…", "⚡ fast mode" if on else "🧠 smart mode")
        threading.Thread(target=lambda: (self.stop(), self._run()), daemon=True).start()

    def _set(self, state, title, detail="", progress=None):
        self.status = {"state": state, "title": title, "detail": detail, "progress": progress,
                       "model": self.model_name, "fast": bool(self._s.get("fast_mode"))}

    def _run(self):
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self._s.get("llm_url"):
                self.model_name = "your own server"
                self._set("ready", "ready")  # using the user's own AI server (LM Studio, Ollama…)
                return
            server = self._ensure_llama()
            repo = self._pick_repo()
            self.model_name = short_name(repo)
            model = self._ensure_model(repo)
            if self._healthy():
                if self._serving(model):
                    self._set("ready", "ready")
                    return
                self._kill_stray()  # a leftover brain from last time is running the wrong model
            self._launch(server, model)
        except Exception as e:
            log.exception("Brain setup failed")
            self._set("error", "my brain didn't load 😵", str(e))
        finally:
            self._lock.release()

    def _pick_repo(self):
        wanted = self._s.get("local_model", "auto")
        if wanted and wanted != "auto":
            main = wanted
        else:
            main = self._s.get("auto_model")
            if not main:
                vram = gpu_memory_gb()
                main = pick_model(vram)
                log.info("GPU memory %.1f GB, picked %s", vram, main)
                self._s["auto_model"] = main
        return FAST.get(main, main) if self._s.get("fast_mode") else main

    def _ensure_llama(self):
        found = list(LLAMA_DIR.rglob("llama-server.exe")) if LLAMA_DIR.exists() else []
        if found:
            return found[0]
        self._set("downloading", "downloading my brain engine ⚙️", "", 0)
        url, _ = llama_download()
        LLAMA_DIR.mkdir(parents=True, exist_ok=True)
        zpath = DATA / "llama.zip"
        download(url, zpath, lambda d, t: self._set("downloading", "downloading my brain engine ⚙️",
                                                    f"{_gb(d)} / {_gb(t)} GB", d / t if t else None))
        with zipfile.ZipFile(zpath) as z:
            z.extractall(LLAMA_DIR)
        zpath.unlink()
        found = list(LLAMA_DIR.rglob("llama-server.exe"))
        if not found:
            raise RuntimeError("llama-server.exe missing from the download")
        return found[0]

    def _ensure_model(self, repo):
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        index_file = MODEL_DIR / "models.json"
        try:
            index = json.loads(index_file.read_text())
        except (OSError, ValueError):
            index = {}
        try:  # older Flip versions kept a single model in model.json
            old = json.loads((MODEL_DIR / "model.json").read_text())
            index.setdefault(old["repo"], old["file"])
        except (OSError, ValueError, KeyError):
            pass
        name = index.get(repo)
        if name and (MODEL_DIR / name).exists():
            return MODEL_DIR / name
        title = "downloading my fast brain ⚡" if self._s.get("fast_mode") else "downloading my brain 🧠"
        self._set("downloading", title, "finding the best one for your PC…", None)
        url, name, _ = model_download(repo)
        download(url, MODEL_DIR / name, lambda d, t: self._set("downloading", title,
                                                              f"{_gb(d)} / {_gb(t)} GB", d / t if t else None))
        index[repo] = name
        index_file.write_text(json.dumps(index, indent=1))
        return MODEL_DIR / name

    def _launch(self, server, model):
        log_file = open(DATA / "brain.log", "ab")
        for gpu in (True, False):
            self._set("loading", "loading my brain into memory…", "almost there", None)
            args = [str(server), "-m", str(model), "--host", "127.0.0.1", "--port", str(PORT),
                    "-c", CONTEXT, "--reasoning", "off", "--no-webui"]
            if not gpu:
                args += ["-ngl", "0"]
            self._proc = subprocess.Popen(
                args, cwd=str(server.parent), stdout=log_file, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.time() + 600
            while time.time() < deadline and self._proc.poll() is None:
                if self._healthy():
                    self._set("ready", "ready")
                    return
                time.sleep(1)
            self.stop()
            log.warning("Brain server stopped (gpu=%s), exit code %s", gpu, self._proc.returncode)
        raise RuntimeError("the brain crashed while starting. Details are in brain.log in Flip's folder.")

    def _healthy(self):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def _serving(self, model):
        try:
            ids = [m["id"] for m in _get_json(f"http://127.0.0.1:{PORT}/v1/models").get("data", [])]
            return any(model.name in i or i in model.name for i in ids)
        except Exception:
            return False

    def _kill_stray(self):
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            time.sleep(1)

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
