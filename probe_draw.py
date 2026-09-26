"""Temporary: runs the on-PC drawer's real model with a few variants and reports what it sees."""

import io
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import openvino as ov
from PIL import Image

import draw
from cliptok import ClipTokenizer
from engine import download

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
kit = Path(sys.argv[2])
kit.mkdir(parents=True, exist_ok=True)
lines = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


api = json.load(urllib.request.urlopen(f"https://huggingface.co/api/models/{draw.REPO}"))
say("FILES", [s["rfilename"] for s in api["siblings"]])
for extra in ["README.md", "scheduler/scheduler_config.json", "scheduler_config.json", "model_index.json",
              "unet/config.json", "config.json"]:
    if any(s["rfilename"] == extra for s in api["siblings"]):
        txt = urllib.request.urlopen(f"https://huggingface.co/{draw.REPO}/resolve/main/{extra}").read().decode()
        say("=====", extra, "\n", txt[:3000])
for name in draw.FILES:
    if not (kit / name).exists():
        download(f"https://huggingface.co/{draw.REPO}/resolve/main/{name}", kit / name, lambda d, t: None)

core = ov.Core()
models = {}
for m in ["text_encoder", "unet", "vae_decoder"]:
    c = core.compile_model(str(kit / f"{m}.xml"), "CPU")
    models[m] = c
    for p in c.inputs:
        say("IN ", m, list(p.get_names()), p.get_partial_shape(), p.get_element_type())
    for p in c.outputs:
        say("OUT", m, list(p.get_names()), p.get_partial_shape(), p.get_element_type())
te, unet, vae = models["text_encoder"], models["unet"], models["vae_decoder"]

tok = ClipTokenizer(kit / "vocab.json", kit / "merges.txt")
ids = tok.encode("cute frog wearing a gaming headset, high quality, detailed, clean digital illustration")
say("IDS", ids[:20])
tin = te.inputs[0]
arr = np.array([ids], dtype=np.int32 if tin.get_element_type() == ov.Type.i32 else np.int64)
res = te({tin: arr})
for p in te.outputs:
    v = res[p]
    say("TE", list(p.get_names()), v.shape, float(v.mean()), float(v.std()))
cond = res[te.outputs[0]]


def smooth(pixels):
    return float(np.abs(np.diff(pixels.astype(np.float32), axis=1)).mean())


def decode(x, tag, scale=0.18215):
    img = vae({vae.inputs[0]: (x / scale).astype(np.float32)})[vae.outputs[0]]
    say("VAE", tag, img.shape, float(img.min()), float(img.max()))
    img = img[0]
    if img.shape[0] == 3:
        img = img.transpose(1, 2, 0)
    pixels = (np.clip(img / 2 + 0.5, 0, 1) * 255).round().astype(np.uint8)
    say("SMOOTH", tag, smooth(pixels))
    Image.fromarray(pixels).save(out / f"{tag}.png")


decode(np.zeros((1, 4, 64, 64), np.float32), "vae-zeros")


def run(tag, steps, w, positional, int_t):
    rng = np.random.default_rng(1)
    x = rng.standard_normal((1, 4, 64, 64)).astype(np.float32)
    alphas = draw.alphas_cumprod()
    wemb = draw.guidance_embedding(w)
    for i, t in enumerate(steps):
        tv = np.array([t], dtype=np.int64 if int_t else np.float32)
        if positional:
            ins = unet.inputs
            feed = {ins[0]: x, ins[1]: tv, ins[2]: cond, ins[3]: wemb} if len(ins) == 4 else {ins[0]: x, ins[1]: tv, ins[2]: cond}
        else:
            feed = {}
            for p in unet.inputs:
                n = p.get_any_name()
                if "sample" in n:
                    feed[p] = x
                elif "timestep_cond" in n or n.startswith("w"):
                    feed[p] = wemb
                elif "timestep" in n:
                    feed[p] = tv
                elif "encoder_hidden_states" in n:
                    feed[p] = cond
        eps = unet(feed)[unet.outputs[0]]
        a = alphas[t]
        x0 = (x - np.sqrt(1 - a) * eps) / np.sqrt(a)
        t_prev = int(steps[i + 1]) if i + 1 < len(steps) else None
        say("STEP", tag, i, int(t), "x", round(float(x.std()), 3), "eps", round(float(eps.std()), 3),
            "x0", round(float(x0.std()), 3), "corr(x,eps)", round(float(np.corrcoef(x.ravel(), eps.ravel())[0, 1]), 3))
        x = draw.lcm_step(x, eps, int(t), t_prev, alphas, rng.standard_normal(x.shape).astype(np.float32)).astype(np.float32)
    decode(x, tag)


steps = draw.lcm_timesteps()
say("STEPS", steps)
for args in [("A-current", steps, draw.GUIDANCE, False, False),
             ("B-positional-int", steps, 8.0, True, True),
             ("C-w-no-minus", steps, 9.0, False, False),
             ("D-linspace", np.array([999, 759, 499, 259]), draw.GUIDANCE, False, True)]:
    try:
        run(*args)
    except Exception as e:
        say("ERR", args[0], repr(e))
(out / "probe.txt").write_text("\n".join(lines), encoding="utf-8")
