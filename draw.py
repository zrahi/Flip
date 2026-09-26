"""Draws pictures on this PC: Stable Diffusion 1.5 LCM (DreamShaper) in Intel's OpenVINO format, made to run on
a processor. The model (~2 GB) is downloaded for each picture and deleted right after it's drawn, so it never
takes up space. 4 steps, 512x512."""

import logging
import shutil
import time
import uuid

import numpy as np

from paths import DATA

log = logging.getLogger("flip")

REPO = "Intel/sd-1.5-lcm-openvino"
FILES = ["text_encoder.xml", "text_encoder.bin", "unet.xml", "unet.bin", "vae_decoder.xml", "vae_decoder.bin",
         "vocab.json", "merges.txt"]
HOME = DATA / "tmp" / "drawer"
STEPS = 4
GUIDANCE = 8.0
SIZE = 512
# Always part of the picture's description: modest, and no watermark-like text.
STYLE = "high quality, detailed, clean digital illustration"


class Stopped(Exception):
    pass


def available():
    try:
        import openvino  # noqa: F401
        return True
    except Exception:
        return False


# Rough sizes (MB), so the progress bar moves evenly across the files.
SIZES = {"text_encoder.bin": 246, "unet.bin": 1719, "vae_decoder.bin": 99}


def _download(folder, on_status, stop):
    from engine import download

    total = sum(SIZES.get(f, 1) for f in FILES)
    before = 0
    for name in FILES:
        def progress(done, size, before=before):
            if stop is not None and stop.is_set():
                raise Stopped()
            on_status(f"getting my drawing kit… {min(99, int(100 * (before + done / 1e6) / total))}%")
        download(f"https://huggingface.co/{REPO}/resolve/main/{name}", folder / name, progress)
        before += SIZES.get(name, 1)


# ---------- LCM sampling (the math the diffusers LCM pipeline does, without torch) ----------

def lcm_timesteps(steps=STEPS, original=50, train=1000):
    c = train // original
    origin = np.arange(1, original + 1) * c - 1
    return origin[::-1][:: original // steps][:steps]


def alphas_cumprod(train=1000, start=0.00085, end=0.012):
    betas = np.linspace(start ** 0.5, end ** 0.5, train, dtype=np.float64) ** 2
    return np.cumprod(1.0 - betas)


def guidance_embedding(w, dim=256):
    w = (w - 1.0) * 1000.0
    half = dim // 2
    freq = np.exp(np.arange(half) * -(np.log(10000.0) / (half - 1)))
    emb = w * freq
    return np.concatenate([np.sin(emb), np.cos(emb)])[None, :].astype(np.float32)


def lcm_step(x, eps, t, t_prev, alphas, noise):
    """One LCM step: the predicted clean picture blended with the boundary condition, then (unless it's the
    last step) noised back to the next timestep."""
    a_t = alphas[t]
    x0 = (x - np.sqrt(1 - a_t) * eps) / np.sqrt(a_t)
    scaled = t * 10.0
    c_skip = 0.25 / (scaled ** 2 + 0.25)
    c_out = scaled / np.sqrt(scaled ** 2 + 0.25)
    denoised = c_out * x0 + c_skip * x
    if t_prev is None:
        return denoised
    a_prev = alphas[t_prev]
    return np.sqrt(a_prev) * denoised + np.sqrt(1 - a_prev) * noise


def _inputs(compiled):
    return {i.get_any_name(): i for i in compiled.inputs}


def draw(prompt, on_status=lambda s: None, stop=None, seed=None):
    """PNG bytes of prompt, drawn here. The model is downloaded first and deleted as soon as the picture is
    drawn (it's in memory by then, and saved into the chat right after)."""
    import openvino as ov
    from PIL import Image
    import io

    from cliptok import ClipTokenizer

    folder = HOME / uuid.uuid4().hex[:8]
    folder.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        _download(folder, on_status, stop)
        log.info("Drawing kit downloaded in %.0fs", time.time() - started)
        on_status("warming up my pencils ✏️")
        core = ov.Core()
        tok = ClipTokenizer(folder / "vocab.json", folder / "merges.txt")
        text_encoder = core.compile_model(str(folder / "text_encoder.xml"), "CPU")
        unet = core.compile_model(str(folder / "unet.xml"), "CPU")
        vae = core.compile_model(str(folder / "vae_decoder.xml"), "CPU")

        ids = np.array([tok.encode(f"{prompt}, {STYLE}")], dtype=np.int64)
        tin = text_encoder.inputs[0]
        if "i32" in str(tin.get_element_type()):
            ids = ids.astype(np.int32)
        cond = text_encoder({tin: ids})[text_encoder.outputs[0]]

        rng = np.random.default_rng(seed)
        x = rng.standard_normal((1, 4, SIZE // 8, SIZE // 8)).astype(np.float32)
        alphas = alphas_cumprod()
        steps = lcm_timesteps()
        names = _inputs(unet)
        w_emb = guidance_embedding(GUIDANCE)
        for i, t in enumerate(steps):
            if stop is not None and stop.is_set():
                raise Stopped()
            on_status(f"drawing… {i + 1}/{len(steps)} 🎨")
            feed = {}
            for name, port in names.items():
                if "sample" in name:
                    feed[port] = x
                elif "timestep_cond" in name or name.startswith("w"):
                    feed[port] = w_emb
                elif "timestep" in name:
                    shape = port.get_partial_shape()
                    feed[port] = np.array([t] if shape.rank.get_length() else t, dtype=np.float32 if "f" in str(
                        port.get_element_type()) else np.int64)
                elif "encoder_hidden_states" in name:
                    feed[port] = cond
            eps = unet(feed)[unet.outputs[0]]
            t_prev = int(steps[i + 1]) if i + 1 < len(steps) else None
            x = lcm_step(x, eps, int(t), t_prev, alphas,
                         rng.standard_normal(x.shape).astype(np.float32)).astype(np.float32)
        image = vae({vae.inputs[0]: (x / 0.18215).astype(np.float32)})[vae.outputs[0]]
        pixels = (np.clip(image[0].transpose(1, 2, 0) / 2 + 0.5, 0, 1) * 255).round().astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(pixels).save(buf, "PNG")
        log.info("Drew %r on this PC in %.0fs", prompt[:80], time.time() - started)
        return buf.getvalue()
    finally:
        shutil.rmtree(folder, ignore_errors=True)  # the whole kit goes: nothing stays on the PC
        if HOME.exists() and not any(HOME.iterdir()):
            HOME.rmdir()
