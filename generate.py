"""Making pictures and videos: free, no account, no key, nothing to install.

Pictures: Pollinations makes them with FLUX in a few seconds. If it's down, a free Hugging Face demo of
FLUX does it. Videos: free Hugging Face demos of Wan 2.2 (one of the best open video models) running
on shared GPUs. With a picture (theirs, or one painted first) it animates that; otherwise it films the
prompt straight away. Shared GPUs have a daily limit per person: when it's used up, Flip says so and
offers websites with free daily video credits instead.

The demos are called through gradio_client, which reads each demo's inputs itself (pick_endpoint), so a
demo that renames or reorders its settings still works. Only the finished picture or video is kept.
"""

import logging
import random
import re
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import draw
from paths import DATA

log = logging.getLogger("flip")

POLLINATIONS = "https://image.pollinations.ai/prompt/"
IMAGE_SPACES = ["black-forest-labs/FLUX.1-schnell"]
TEXT_TO_VIDEO = ["zerogpu-aoti/wan2-2-fp8da-aoti", "Lightricks/ltx-video-distilled"]
PICTURE_TO_VIDEO = ["zerogpu-aoti/wan2-2-fp8da-aoti-faster", "Lightricks/ltx-video-distilled"]
# Free daily video credits on the web, for when the free GPUs' daily limit is used up.
WEBSITES = [("Google Flow", "https://labs.google/fx/tools/flow"), ("Kling", "https://app.klingai.com/global/")]
TMP = DATA / "tmp" / "made"
EXTENSIONS = {"video": {".mp4", ".webm", ".mov", ".mkv"}, "image": {".png", ".jpg", ".jpeg", ".webp"}}
VIDEO_STYLE = ", cinematic, smooth natural motion, detailed, sharp focus"
TOKEN = None  # an optional Hugging Face token (settings.json "hf_token") gives more free GPU time

NOT_OK = re.compile(r"\b(nudes?|naked|nsfw|porn\w*|sex|sexy|sexual|hentai|boobs?|tits|dick|penis|vagina|genitals?|"
                    r"undress\w*|lingerie|onlyfans|explicit|erotic\w*|fetish\w*|gore|gory|beheading|deepfake)\b", re.I)


class MakeError(Exception):
    """Something went wrong that the user should hear about, in Flip's words."""


class LimitReached(MakeError):
    """The free GPU time for today is used up (it's per person, so every demo says the same)."""


class Stopped(Exception):
    pass


def not_ok(prompt):
    return NOT_OK.search(prompt or "") is not None


# ---------- pictures ----------

# What the agents and maps look like: picture AIs don't know Valorant, so "Jett" alone came out as a random
# (and too sexy) woman. Only looks that are sure; the others get the game's art style and their name.
LOOKS = {
    "jett": "a young Korean woman with short white hair, a blue-and-white high-collar jacket zipped up, long dark "
            "cargo pants and boots, swirling blue wind, throwing glowing blue kunai knives",
    "phoenix": "a young Black British man with short curly hair, a white-and-orange jacket, hands wreathed in fire",
    "sage": "a Chinese woman with long black hair in a ponytail, a white-and-teal outfit, a glowing jade healing orb",
    "sova": "a tall Russian man with white-blond hair tied back, a blue hooded coat, one glowing bionic eye, a "
            "high-tech recon bow",
    "reyna": "a Mexican woman with long black hair, glowing purple eyes, a black-and-purple outfit, purple soul orbs",
    "omen": "a tall hooded shadow figure in a dark blue cloak, faceless except three glowing blue slits, drifting "
            "shadow smoke",
    "viper": "a woman with dark hair in a bun, a black-and-green suit and a gas mask, toxic green gas",
    "cypher": "a man in a white trench coat and white hat, face hidden behind a white mask with glowing eyes, spy "
              "cameras and tripwires",
    "killjoy": "a young German woman with round glasses, a green beanie and a yellow jacket, a small robot turret",
    "raze": "a Brazilian woman in an orange-and-yellow outfit with a cap, a rocket launcher, playful explosives",
    "yoru": "a Japanese man with spiky dark blue hair, a blue-and-black jacket, a glowing blue dimensional rift",
    "neon": "a Filipina woman with blue hair in two long pigtails, a blue-and-black suit, crackling blue lightning",
    "chamber": "a French man with slicked hair and glasses in a sharp tailored suit, gold custom pistols",
    "skye": "an Australian woman with red braided hair, a green outfit, glowing green hawk and wolf spirits",
    "breach": "a Swedish man with a red beard and mohawk, huge orange bionic arms, seismic blasts",
    "kay/o": "a battle robot with a white-and-blue armored body and a glowing face screen",
    "astra": "a Ghanaian woman with gold jewelry and cosmic purple-and-gold star powers",
}
PLACES = {
    "haven": "a mountain temple monastery in Bhutan, stone courtyards and wooden buildings with golden roofs, "
             "prayer flags, misty peaks",
    "ascent": "a Venice-like Italian city on a floating island, cobblestone plazas, domes and arches",
    "bind": "a Moroccan desert city, sandstone buildings, arches and glowing teleporters",
    "split": "a vertical Tokyo city, neon signs, tall towers and ropes between levels",
    "icebox": "an arctic shipping yard, snow, stacked containers and cranes",
    "breeze": "a tropical Caribbean island, turquoise water, ancient stone ruins and palm trees",
    "fracture": "a research facility split in half, desert on one side and farmland on the other",
    "pearl": "an underwater Portuguese city under a dome, tiled buildings and blue light",
    "lotus": "an ancient Indian city in green mountains, carved stone temples and big rotating stone doors",
    "sunset": "a Los Angeles street at sunset, taco shops, palm trees and warm light",
    "abyss": "a facility on floating cliffs over a bottomless abyss in Norway, no railings, cold light",
}
PEOPLE = re.compile(r"\b(woman|women|girl|lady|man|men|guy|boy|person|people|character|agent|anime|waifu|she|her|he|"
                    r"him)\b", re.I)
ART_ONLY = re.compile(r"\b(valorant|agent|map|official|art|artwork|splash|portrait|picture|pic|image|photo|of|the|a|an|"
                      r"in|from|full|body|hd|4k|wallpaper|what|looks?|like|does|do|show|me)\b", re.I)


def _names(prompt, names):
    low = prompt.lower()
    return [n for n in names if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", low)]


def describe(prompt):
    """The prompt with what the picture AI needs to know: how agents and maps look, and fully clothed people."""
    agents = _names(prompt, LOOKS)
    places = _names(prompt, PLACES)
    try:
        import livedata
        known = livedata.art()
    except Exception:
        known = {}
    others = [n for n, a in known.items() if a["kind"] == "agent" and n not in LOOKS and n in _names(prompt, [n])]
    extra = [f"{n.title()} is {LOOKS[n]}" for n in agents]
    extra += [f"{n.title()} is {PLACES[n]}" for n in places]
    extra += [f"{known[n]['name']} is an agent from the game Valorant" for n in others]
    valorant = bool(extra) or "valorant" in prompt.lower()
    if valorant:
        extra.append("Valorant game art style, stylized painterly splash art")
    if agents or others or PEOPLE.search(prompt):
        # first, so a picture maker that only reads the start of a long description still gets it
        return ". ".join([MODEST, prompt] + extra)
    return ". ".join([prompt] + extra) if extra else prompt


MODEST = ("modest, fully clothed and covered up: closed jacket or long sleeves, long pants, no cleavage, no bare "
          "legs, non-suggestive, safe for work")


def official_art(prompt, stop=None):
    """"a picture of Jett", "Haven": the real picture from the game's files (bytes, ext, name) or None."""
    try:
        import livedata
        known = livedata.art()
    except Exception:
        return None
    hits = _names(prompt, known)
    if len(hits) != 1:
        return None
    rest = ART_ONLY.sub(" ", re.sub(re.escape(hits[0]), " ", prompt.lower()))
    if re.search(r"[a-z]{2}", re.sub(r"[^a-z\s]", " ", rest)):
        return None  # "Jett throwing daggers": a scene, so it gets painted
    if stop is not None and stop.is_set():
        raise Stopped()
    a = known[hits[0]]
    with urllib.request.urlopen(urllib.request.Request(a["url"], headers={"User-Agent": "Flip/1.0"}), timeout=60) as r:
        kind = (r.headers.get("Content-Type") or "").split(";")[0].strip()
        data = r.read(25 * 1024 * 1024)
    if not kind.startswith("image/") or len(data) < 2000:
        return None
    return data, {"image/jpeg": "jpg", "image/webp": "webp"}.get(kind, "png"), a["name"]


def make_image(prompt, size=(1024, 1024), on_status=lambda s: None, stop=None, local=True):
    """Returns (bytes, extension, what made it). local: draw it on this PC (a video's first frame is made
    online, the video is anyway)."""
    try:
        found = official_art(prompt, stop)
        if found:
            return found[0], found[1], f"the official {found[2]} art from the game"
    except Stopped:
        raise
    except Exception as e:
        log.warning("Couldn't get the official art: %s", e)
    prompt = describe(prompt)
    if local and draw.available():
        # drawn right here: the drawing kit is downloaded, used and deleted
        try:
            return draw.draw(prompt, on_status, stop), "png", "drawn on this PC"
        except draw.Stopped:
            raise Stopped()
        except Exception as e:
            log.exception("Couldn't draw it on this PC: %s", e)
    on_status("painting it… 🎨")
    try:
        data, ext = _pollinations(prompt, size, stop)
        return data, ext, "Pollinations (FLUX)"
    except Stopped:
        raise
    except Exception as e:
        log.warning("Pollinations couldn't make it: %s", e)
    for space in IMAGE_SPACES:
        try:
            path = run_space(space, "image", prompt, None, on_status, stop, timeout=240)
            data = Path(path).read_bytes()
            tidy(path)
            return data, Path(path).suffix.lstrip(".").lower() or "png", space
        except (Stopped, LimitReached):
            raise
        except Exception as e:
            log.warning("%s couldn't make the picture: %s", space, e)
    raise MakeError("couldn't make the picture right now 😵 the free picture makers are down or busy, try again in a bit")


def _pollinations(prompt, size, stop):
    if stop is not None and stop.is_set():
        raise Stopped()
    params = urllib.parse.urlencode({"width": size[0], "height": size[1], "seed": random.randint(1, 2 ** 31 - 1),
                                     "model": "flux", "nologo": "true", "safe": "true",
                                     "enhance": "false" if ". " in prompt else "true",
                                     "private": "true"})
    url = f"{POLLINATIONS}{urllib.parse.quote(prompt[:900], safe='')}?{params}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Flip/1.0"}), timeout=150) as r:
        kind = (r.headers.get("Content-Type") or "").split(";")[0].strip()
        data = r.read(25 * 1024 * 1024)
    if stop is not None and stop.is_set():
        raise Stopped()
    if not kind.startswith("image/") or len(data) < 2000:
        raise RuntimeError(f"didn't get a picture back ({kind or 'no type'}, {len(data)} bytes)")
    return data, {"image/png": "png", "image/webp": "webp"}.get(kind, "jpg")


# ---------- videos ----------

def make_video(prompt, picture=None, on_status=lambda s: None, stop=None):
    """picture: a picture file to bring to life (optional). Returns (path of the video, what made it)."""
    plans = [(space, picture) for space in PICTURE_TO_VIDEO] if picture else []
    plans += [(space, None) for space in TEXT_TO_VIDEO]
    if not picture:  # last try: paint the first frame, then animate it
        plans.append((PICTURE_TO_VIDEO[0], "paint"))
    problems = []
    for space, pic in plans:
        painted = None
        try:
            if pic == "paint":
                data, ext, _ = make_image(prompt + ", cinematic film still", (1280, 720), on_status, stop, local=False)
                TMP.mkdir(parents=True, exist_ok=True)
                pic = painted = TMP / f"frame-{uuid.uuid4().hex[:8]}.{ext}"
                pic.write_bytes(data)
            path = run_space(space, "video", describe(prompt) + VIDEO_STYLE, pic, on_status, stop, timeout=900)
            return path, space
        except (Stopped, LimitReached):
            raise
        except Exception as e:
            log.warning("%s couldn't make the video: %s", space, e)
            problems.append(f"{space.split('/')[-1]}: {str(e)[:120]}")
        finally:
            if painted is not None:
                painted.unlink(missing_ok=True)  # only needed while the video was being made
    raise MakeError("the free video makers are down or busy right now 😵 try again in a bit")


# ---------- free demos on Hugging Face ----------

def _label(info):
    return f"{info.get('label') or ''} {info.get('parameter_name') or ''}".lower()


def _component(info):
    return str(info.get("component") or "").lower()


def _makes(info, kind):
    if kind == "video":
        return _component(info) == "video" or ("video" in _label(info) and _component(info) == "file")
    return _component(info) in ("image", "gallery", "imageslider")


def _is_picture_input(p):
    return _component(p) == "image" or (_component(p) == "file" and "image" in _label(p))


def _is_prompt(p):
    return (_component(p) in ("textbox", "textarea", "text") and (p.get("python_type") or {}).get("type") == "str"
            and "negative" not in _label(p))


def pick_endpoint(api, kind, have_picture):
    """(endpoint, prompt parameter, picture parameter or None) of the demo's endpoint that makes a kind
    ("image"/"video") from a prompt, filling in only those two; None if it has none."""
    best = None
    for name, ep in ((api or {}).get("named_endpoints") or {}).items():
        params, returns = ep.get("parameters") or [], ep.get("returns") or []
        if not any(_makes(r, kind) for r in returns):
            continue
        texts = [p for p in params if _is_prompt(p)]
        prompt = next((p for p in texts if "prompt" in _label(p)), texts[0] if texts else None)
        if prompt is None:
            continue
        picture = next((p for p in params if _is_picture_input(p)), None)
        if picture is not None and not picture.get("parameter_has_default") and not have_picture:
            continue  # needs a picture and there isn't one
        needs = [p for p in params if p is not prompt and p is not picture and not p.get("parameter_has_default")]
        if needs:
            continue  # it needs something else that can't be filled in
        use_picture = picture is not None and have_picture
        score = ("prompt" in _label(prompt)) + 2 * use_picture + any(w in name for w in ("generate", "infer", "run"))
        if best is None or score > best[0]:
            best = (score, name, prompt["parameter_name"], picture["parameter_name"] if use_picture else None)
    return best[1:] if best else None


def find_file(result, kind):
    """The picture/video file in whatever a demo gave back (a path, a tuple, a dict, a gallery…)."""
    if isinstance(result, (list, tuple)):
        for r in result:
            found = find_file(r, kind)
            if found:
                return found
    elif isinstance(result, dict):
        for key in ("video", "path", "image", "name", "value"):
            if key in result:
                found = find_file(result[key], kind)
                if found:
                    return found
    elif isinstance(result, str) and Path(result).suffix.lower() in EXTENSIONS[kind] and Path(result).is_file():
        return result
    return None


def _status_text(status, kind):
    code = getattr(getattr(status, "code", None), "value", "")
    if code in ("JOINING_QUEUE", "IN_QUEUE", "QUEUE_FULL"):
        rank, size = getattr(status, "rank", None), getattr(status, "queue_size", None)
        return f"in line for the free GPU (#{rank + 1} of {size})…" if rank is not None and size else "in line for the free GPU…"
    doing = "filming it… 🎬" if kind == "video" else "painting it… 🎨"
    if code in ("PROCESSING", "PROGRESS", "ITERATING"):
        for unit in getattr(status, "progress_data", None) or []:
            index, length = getattr(unit, "index", None), getattr(unit, "length", None)
            if index is not None and length:
                return f"{doing[:-2]} {round(100 * index / length)}%"
        return doing
    return "waking up the free GPU…"


def _limit_text(error):
    wait = re.search(r"(?:try again|retry|available again)\s+in\s+([\d:]+(?:\s*\w+)?)", error, re.I)
    return ("the free video GPUs' daily limit is used up" + (f" (it resets in {wait.group(1)})" if wait else "") +
            " 😭 Google Flow and Kling give free videos every day, want me to open one? I'll copy your prompt.")


def run_space(space, kind, prompt, picture, on_status, stop, timeout):
    """Runs a free Hugging Face demo and returns the path of what it made."""
    from gradio_client import Client, handle_file

    if stop is not None and stop.is_set():
        raise Stopped()
    TMP.mkdir(parents=True, exist_ok=True)
    on_status("waking up the free GPU…")
    client = Client(space, token=TOKEN or None, verbose=False, download_files=str(TMP), analytics_enabled=False)
    found = pick_endpoint(client.view_api(print_info=False, return_format="dict"), kind, picture is not None)
    if not found:
        raise RuntimeError(f"no way to make a {kind} there")
    endpoint, prompt_name, picture_name = found
    args = {prompt_name: prompt}
    if picture_name:
        args[picture_name] = handle_file(str(picture))
    log.info("Making a %s with %s %s", kind, space, endpoint)
    job = client.submit(api_name=endpoint, **args)
    deadline = time.time() + timeout
    said = "waking up the free GPU…"
    while not job.done():
        if stop is not None and stop.is_set():
            job.cancel()
            raise Stopped()
        if time.time() > deadline:
            job.cancel()
            raise TimeoutError("took too long")
        text = _status_text(job.status(), kind)
        if text != said:
            on_status(text)
            said = text
        time.sleep(0.5)
    try:
        result = job.result()
    except Exception as e:
        if re.search(r"quota|exceeded|too many requests|rate.?limit", str(e), re.I):
            raise LimitReached(_limit_text(str(e)))
        raise
    path = find_file(result, kind)
    if not path:
        raise RuntimeError(f"it gave back no {kind} ({str(result)[:150]})")
    return path


# ---------- in the chat ----------

CAPTIONS = {
    "image": ["here you go 🎨", "fresh out the oven 🔥", "cooked this up for you 👨‍🍳", "how's this? 👀",
              "painted it, rate it 1-10 😤", "one picture, extra crispy 🖼️"],
    "video": ["here's your clip 🎬", "rolling 🎥 how'd it come out?", "action 🎬 lmk if you want changes",
              "fresh clip just dropped 🔥", "filmed it, rate it 😤"],
}


def caption(kind, earlier=()):
    """A short line to go with what he made, not one he used lately."""
    fresh = [c for c in CAPTIONS[kind] if not any(c in e for e in earlier)]
    return random.choice(fresh or CAPTIONS[kind])


def last_made(chat):
    """{"kind", "prompt", "id"} of the picture/video his last reply had, for follow-ups like "make it darker"
    or "now animate it"."""
    for m in reversed((chat or {}).get("messages") or []):
        if m.get("role") == "assistant":
            made = [a for a in m.get("attachments") or [] if a.get("made")]
            return {"kind": made[0]["kind"], "prompt": made[0].get("prompt", ""), "id": made[0]["id"]} if made else None
    return None


def tidy(path):
    """Deletes what a demo downloaded (gradio puts each result in its own folder under TMP)."""
    import shutil

    path = Path(path)
    try:
        if TMP in path.parents:
            folder = path.parent if path.parent != TMP else None
            path.unlink(missing_ok=True)
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)
            if TMP.exists() and not any(TMP.iterdir()):
                TMP.rmdir()
    except OSError:
        pass
