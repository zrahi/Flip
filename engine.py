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
LLAMA_DIRS = {"vulkan": DATA / "llama", "cuda": DATA / "llama-cuda"}
MODEL_DIR = DATA / "models"
HEADERS = {"User-Agent": "Flip/1.0"}
# How much of the chat the brain can hold at once. Small enough that the whole brain fits on an
# 8 GB graphics card (if any of it spills onto the processor, replies get way slower).
CONTEXT = "8192"

# His brains can see (for screen sharing): Qwen3-VL, with a separate "eyes" file (mmproj).
# (minimum GPU memory in GB, Hugging Face repo). The first one that fits is used.
MODELS = [
    (7, "Qwen/Qwen3-VL-8B-Instruct-GGUF"),
    (0, "Qwen/Qwen3-VL-4B-Instruct-GGUF"),
]
# Fast mode: a smaller brain that answers much quicker.
FAST = {
    "Qwen/Qwen3-VL-8B-Instruct-GGUF": "Qwen/Qwen3-VL-4B-Instruct-GGUF",
    "Qwen/Qwen3-VL-4B-Instruct-GGUF": "Qwen/Qwen3-VL-2B-Instruct-GGUF",
}
QUANTS = ("Q4_K_M", "Q4_K_S", "Q4_0", "Q8_0")  # first one a repo has wins
EYES_QUANTS = ("Q8_0", "F16", "BF16")


def short_name(repo):
    return repo.split("/")[-1].replace("-GGUF", "").replace("-Instruct-2507", "").replace("-Instruct", "")


def gpu_info():
    """(memory in GB, name) of the biggest graphics card on this PC, read from the Windows registry."""
    if sys.platform != "win32":
        return 0.0, ""
    import winreg

    best, best_name = 0, ""
    base = r"SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return 0.0, ""
    with root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            name = winreg.EnumKey(root, i)
            if not name.isdigit():
                continue
            try:
                with winreg.OpenKey(root, name) as key:
                    size = 0
                    for value in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                        try:
                            size, _ = winreg.QueryValueEx(key, value)
                        except OSError:
                            continue
                        if isinstance(size, bytes):
                            size = int.from_bytes(size[:8], "little")
                        break
                    try:
                        desc = str(winreg.QueryValueEx(key, "DriverDesc")[0])
                    except OSError:
                        desc = ""
                    if int(size) > best:
                        best, best_name = int(size), desc
            except OSError:
                continue
    return best / 1024 ** 3, best_name


def gpu_memory_gb():
    return gpu_info()[0]


def pick_model(vram_gb):
    return next(repo for min_gb, repo in MODELS if vram_gb >= min_gb)


def _get_json(url):
    headers = dict(HEADERS)
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"  # only set on the build server, avoids rate limits
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return json.load(r)


def _repo_files(repo):
    return [f for f in _get_json(f"https://huggingface.co/api/models/{repo}/tree/main")
            if f.get("path", "").lower().endswith(".gguf") and "/" not in f.get("path", "")]


def model_download(repo):
    """(url, file name, size) of the brain file in a Hugging Face repo (Q4_K_M if it has one)."""
    files = [f for f in _repo_files(repo) if "mmproj" not in f["path"].lower()]
    for quant in QUANTS:
        for f in files:
            if quant.lower() in f["path"].lower():
                return f"https://huggingface.co/{repo}/resolve/main/{f['path']}", f["path"], f.get("size", 0)
    raise RuntimeError(f"no usable model file in {repo}")


def eyes_download(repo):
    """(url, file name, size) of the brain's eyes (the mmproj file that lets it see pictures), or None."""
    files = [f for f in _repo_files(repo) if "mmproj" in f["path"].lower()]
    for quant in EYES_QUANTS:
        for f in files:
            if quant.lower() in f["path"].lower():
                return f"https://huggingface.co/{repo}/resolve/main/{f['path']}", f["path"], f.get("size", 0)
    if files:
        f = files[0]
        return f"https://huggingface.co/{repo}/resolve/main/{f['path']}", f["path"], f.get("size", 0)
    return None


def llama_download(kind="vulkan"):
    """[(url, size), …] for the newest llama.cpp Windows build of this kind.
    vulkan: works on any graphics card (and falls back to the processor).
    cuda: NVIDIA only, fastest on NVIDIA; comes with a second zip of NVIDIA's runtime files."""
    releases = _get_json("https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10")
    for release in releases:  # the newest release sometimes doesn't have its files uploaded yet
        assets = [(a["name"].lower(), a) for a in release.get("assets", [])]
        if kind == "cuda":
            main = [a for n, a in assets if n.startswith("llama-") and "bin-win-cuda-12" in n and "x64" in n and n.endswith(".zip")]
            runtime = [a for n, a in assets if n.startswith("cudart-") and "cuda-12" in n and "x64" in n and n.endswith(".zip")]
            if main and runtime:
                return [(main[0]["browser_download_url"], main[0]["size"]),
                        (runtime[0]["browser_download_url"], runtime[0]["size"])]
            continue
        for want in (kind, "cpu"):
            for n, a in assets:
                if n.endswith(".zip") and "bin-win" in n and f"-{want}-" in n and "x64" in n and not n.startswith("cudart"):
                    return [(a["browser_download_url"], a["size"])]
    names = [a["name"] for r in releases[:2] for a in r.get("assets", [])]
    raise RuntimeError(f"couldn't find llama.cpp ({kind}) for Windows (saw: {names[:30]})")


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
        self.eyes = None
        self.on_ready = None

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
                       "model": self.model_name, "fast": bool(self._s.get("fast_mode")), "vision": bool(self.eyes),
                       "hardware": self.hardware() if state == "ready" and not self._s.get("llm_url") else ""}
        if state == "ready":
            log.info("Brain ready: %s on %s", self.model_name, self.status["hardware"] or "your own server")
            if self.on_ready:
                threading.Thread(target=self.on_ready, daemon=True).start()

    def _run(self):
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self._s.get("llm_url"):
                self.model_name = "your own server"
                self._set("ready", "ready")  # using the user's own AI server (LM Studio, Ollama…)
                return
            repo = self._pick_repo()
            self.model_name = short_name(repo)
            kinds = self._engine_kinds()
            model = self._ensure_model(repo)
            if self._healthy():
                if self._running() == {"kind": kinds[0], "model": model.name} and self._serving(model):
                    self._set("ready", "ready")
                    return
                self._kill_stray()  # a leftover brain from last time is running something else
            self._launch(kinds, model)
        except Exception as e:
            log.exception("Brain setup failed")
            self._set("error", "my brain didn't load 😵", str(e))
        finally:
            self._lock.release()

    def _engine_kinds(self):
        """Which llama.cpp builds to try, best first."""
        wanted = self._s.get("llama_backend", "auto")
        if wanted in ("vulkan", "cuda"):
            return [wanted] + (["vulkan"] if wanted == "cuda" else [])
        _, name = gpu_info()
        return ["cuda", "vulkan"] if "nvidia" in name.lower() else ["vulkan"]

    def _running(self):
        try:
            return json.loads((DATA / "running.json").read_text())
        except (OSError, ValueError):
            return {}

    def _pick_repo(self):
        wanted = self._s.get("local_model", "auto")
        if wanted and wanted != "auto":
            main = wanted
        else:
            main = self._s.get("auto_model")
            if main not in {r for _, r in MODELS}:  # not set yet, or a brain from an older version
                vram = gpu_memory_gb()
                main = pick_model(vram)
                log.info("GPU memory %.1f GB, picked %s", vram, main)
                self._s["auto_model"] = main
        return FAST.get(main, main) if self._s.get("fast_mode") else main

    def _ensure_llama(self, kind):
        folder = LLAMA_DIRS[kind]
        found = list(folder.rglob("llama-server.exe")) if (folder / ".complete").exists() or kind == "vulkan" and folder.exists() else []
        if found:
            return found[0]
        title = "downloading the NVIDIA turbo engine ⚡" if kind == "cuda" else "downloading my brain engine ⚙️"
        self._set("downloading", title, "", 0)
        parts = llama_download(kind)
        folder.mkdir(parents=True, exist_ok=True)
        total = sum(size for _, size in parts)
        done_before = 0
        for i, (url, size) in enumerate(parts):
            zpath = DATA / f"llama-{kind}-{i}.zip"
            download(url, zpath, lambda d, t, b=done_before: self._set(
                "downloading", title, f"{_gb(b + d)} / {_gb(total)} GB", (b + d) / total if total else None))
            with zipfile.ZipFile(zpath) as z:
                z.extractall(folder)
            zpath.unlink()
            done_before += size
        found = list(folder.rglob("llama-server.exe"))
        if not found:
            raise RuntimeError("llama-server.exe missing from the download")
        (folder / ".complete").write_text("ok")
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
        title = "downloading my fast brain ⚡" if self._s.get("fast_mode") else "downloading my brain 🧠"
        name = index.get(repo)
        if not (name and (MODEL_DIR / name).exists()):
            self._set("downloading", title, "finding the best one for your PC…", None)
            url, name, _ = model_download(repo)
            download(url, MODEL_DIR / name, lambda d, t: self._set("downloading", title,
                                                                  f"{_gb(d)} / {_gb(t)} GB", d / t if t else None))
            index[repo] = name
            index_file.write_text(json.dumps(index, indent=1))
        # the brain's eyes, so it can see shared screens (only some brains have them)
        self.eyes = None
        eyes = index.get(repo + "#eyes")
        if eyes and (MODEL_DIR / eyes).exists():
            self.eyes = MODEL_DIR / eyes
        elif repo + "#eyes" not in index or eyes:
            found = eyes_download(repo)
            if found:
                url, eyes_name, _ = found
                eyes = f"{short_name(repo)}-{eyes_name}"
                self._set("downloading", "downloading my eyes 👀", "so I can see your screen", None)
                download(url, MODEL_DIR / eyes, lambda d, t: self._set("downloading", "downloading my eyes 👀",
                                                                      f"{_gb(d)} / {_gb(t)} GB", d / t if t else None))
                self.eyes = MODEL_DIR / eyes
            index[repo + "#eyes"] = eyes or ""
            index_file.write_text(json.dumps(index, indent=1))
        return MODEL_DIR / name

    def _forget_old_brains(self):
        """Brains from older Flip versions (that can't see) get deleted once the new one works."""
        if self._s.get("local_model", "auto") != "auto":
            return
        current = {r for _, r in MODELS} | set(FAST.values())
        index_file = MODEL_DIR / "models.json"
        try:
            index = json.loads(index_file.read_text())
        except (OSError, ValueError):
            return
        for key, name in list(index.items()):
            if key.split("#")[0] not in current:
                if name:
                    (MODEL_DIR / name).unlink(missing_ok=True)
                del index[key]
                log.info("Deleted old brain file %s", name)
        index_file.write_text(json.dumps(index, indent=1))
        (MODEL_DIR / "model.json").unlink(missing_ok=True)

    def _launch(self, kinds, model):
        log_file = open(DATA / "brain.log", "ab")
        # Try the fastest engine on the graphics card first, then the next one, then the processor only.
        attempts = [(kind, True) for kind in kinds] + [(kinds[-1], False)]
        for kind, gpu in attempts:
            try:
                server = self._ensure_llama(kind)
            except Exception:
                log.exception("Couldn't get the %s engine", kind)
                continue
            self._set("loading", "loading my brain into memory…", "almost there", None)
            args = [str(server), "-m", str(model), "--host", "127.0.0.1", "--port", str(PORT),
                    *(["--mmproj", str(self.eyes)] if self.eyes else []),
                    "-c", CONTEXT, "--reasoning", "off", "--no-webui",
                    # one conversation slot: every message lands where the last one was, so the brain
                    # reuses what it already read instead of starting over
                    "-np", "1"]
            if not gpu:
                args += ["-ngl", "0"]
            self._proc = subprocess.Popen(
                args, cwd=str(server.parent), stdout=log_file, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.time() + 600
            while time.time() < deadline and self._proc.poll() is None:
                if self._healthy():
                    more_gpu_tries = gpu and (kind, gpu) != attempts[-2]
                    if more_gpu_tries and self.hardware().startswith("CPU"):
                        log.warning("The %s engine ended up on the processor; trying the next one", kind)
                        break  # this engine couldn't use the graphics card, try the next one
                    (DATA / "running.json").write_text(json.dumps({"kind": kind if gpu else "cpu", "model": model.name}))
                    self._set("ready", "ready")
                    self._forget_old_brains()
                    return
                time.sleep(1)
            self.stop()
            log.warning("Brain server stopped (%s, gpu=%s), exit code %s", kind, gpu, self._proc.returncode)
        raise RuntimeError("the brain crashed while starting. Details are in brain.log in Flip's folder.")

    def hardware(self):
        """What brain.log says about where the brain runs: "GPU (NVIDIA …, 37/37 layers)" or "CPU"."""
        import re

        try:
            text = (DATA / "brain.log").read_text(encoding="utf-8", errors="ignore")[-200_000:]
        except OSError:
            return ""
        text = text[text.rfind("load_model: loading model"):] if "load_model: loading model" in text else text
        layers = re.findall(r"offloaded (\d+)/(\d+) layers to GPU", text)
        device = re.findall(r"using device (\w+) \(([^)]+)\)", text) or re.findall(r"ggml_vulkan: 0 = ([^|\n]+)", text)
        name = (device[-1][1] if device and isinstance(device[-1], tuple) else (device[-1] if device else "")).strip()
        if layers and int(layers[-1][0]) > 0:
            done, total = layers[-1]
            return f"GPU{' (' + name + ')' if name else ''}, {done}/{total} layers"
        return "CPU only (slow: no graphics card found, or it doesn't have enough memory)"

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
