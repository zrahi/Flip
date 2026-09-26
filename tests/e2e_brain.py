"""Full brain test on Windows: download llama.cpp + a small seeing brain, start it, chat, and look at a picture."""
import base64
import io
import os
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # the Windows console can't print emoji otherwise
os.environ["FLIP_HOME"] = os.environ.get("FLIP_E2E_HOME") or tempfile.mkdtemp(prefix="flip-e2e-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import store  # noqa: E402
from brain import Brain  # noqa: E402
from engine import Engine  # noqa: E402

settings = {"name": "Flip", "local_model": "Qwen/Qwen3-VL-2B-Instruct-GGUF", "roblox_studio": False}
engine = Engine(settings)
engine.start()
last = None
deadline = time.time() + 2400
while time.time() < deadline:
    s = engine.status
    if s["state"] != (last or {}).get("state"):
        print(s, flush=True)
    last = s
    if s["state"] in ("ready", "error"):
        break
    time.sleep(2)
assert engine.status["state"] == "ready", engine.status
assert engine.status["vision"], "the brain has no eyes"

store.use_account(store.create_account("tester", "password1"))
store.use_profile(store.create_profile("Sam"))
brain = Brain(settings, (Path(__file__).resolve().parent.parent / "personality.txt").read_text(encoding="utf-8"), engine.url)
brain.warm_up()
reply, _, _ = brain.chat("e2e", "hi! my name is Sam and my main is Jett. say hi back.")
print("REPLY:", reply, brain.last_stats)
assert reply.strip()
reply, _, _ = brain.chat("e2e", "who's my main agent?")
print("REPLY 2:", reply, brain.last_stats)

# no parroting: different messages in a voice call get different replies, and so does the same message twice
from repeats import too_similar as verdict  # noqa: E402  (stricter than his own check)

said = []
for msg in ("yo what's up bro", "could you stop saying the same thing every time", "do you see my screen?",
            "wsp coach", "wsp coach"):
    reply, _, _ = brain.chat("e2erepeat", msg, voice=True)  # (letters only: a "-" never saved the chat)
    print("REPLY VOICE:", reply)
    assert not verdict(reply, said), f"repeated itself: {reply!r} after {said!r}"
    said.append(reply)
said = []
for msg in ("wsp coach", "wsp coach", "I play Yoru", "I do hear a coach."):  # the chat from the user's screenshots
    reply, _, _ = brain.chat("e2etext", msg)
    print("REPLY TEXT:", reply)
    assert not verdict(reply, said), f"repeated itself: {reply!r} after {said!r}"
    said.append(reply)

# eyes: a picture with a big red square on white; he has to say it's red
from PIL import Image, ImageDraw  # noqa: E402

img = Image.new("RGB", (640, 360), "white")
ImageDraw.Draw(img).rectangle((180, 80, 460, 280), fill=(230, 20, 20))
buf = io.BytesIO()
img.save(buf, "JPEG")
pic = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
reply, _, _ = brain.chat("e2eeyes", "What color is the big square on my screen? Answer with one word.", image=pic,
                         image_label="a test picture")
print("REPLY EYES:", reply, brain.last_stats)
assert "red" in reply.lower(), reply
print("hardware:", engine.hardware())

# quality: math (with the calculator) and Valorant coaching
import playtest as evals  # noqa: E402

# coaching and how he talks come first; math matters least
lines = []


def log(line):
    print(line, flush=True)
    lines.append(line)


val_ok, val_n = evals.run_valorant(brain, log)
chat_ok, chat_n = evals.run_chat(brain, log)
math_ok, calc_used, math_n = evals.run_math(brain, log, only=evals.QUICK_MATH)
print(f"SCORE valorant {val_ok}/{val_n}, chat {chat_ok}/{chat_n}, math {math_ok}/{math_n} "
      f"(calculator used when needed {calc_used}/{math_n})")
engine.stop()
must = ["no strats when we're just chatting", "doesn't invent agents"]  # the things the user caught him on
missed = [m for m in must if any(l.startswith("EVAL valorant FAIL") and f"[{m}]" in l for l in lines)]
assert not missed, f"got these wrong: {missed}"
assert val_ok >= round(val_n * 0.7), f"valorant coaching eval too low: {val_ok}/{val_n}"
assert chat_ok >= chat_n - 2, f"chat eval too low: {chat_ok}/{chat_n}"
assert math_ok >= math_n - 2, f"math eval too low: {math_ok}/{math_n}"
print("E2E OK")
