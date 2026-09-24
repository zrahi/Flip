"""Full test on Windows: download llama.cpp + a tiny model, start it, and chat with Flip."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # the Windows console can't print emoji otherwise
os.environ["FLIP_HOME"] = tempfile.mkdtemp(prefix="flip-e2e-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import store  # noqa: E402
from brain import Brain  # noqa: E402
from engine import Engine  # noqa: E402

settings = {"name": "Flip", "local_model": "unsloth/Qwen3-0.6B-GGUF", "roblox_studio": False}
engine = Engine(settings)
engine.start()
last = None
deadline = time.time() + 1500
while time.time() < deadline:
    s = engine.status
    if s != last:
        print(s, flush=True)
        last = s
    if s["state"] in ("ready", "error"):
        break
    time.sleep(2)
assert engine.status["state"] == "ready", engine.status

store.use_account(store.create_account("tester", "password1"))
store.use_profile(store.create_profile("Sam"))
brain = Brain(settings, "You are {name}, a friendly buddy. Keep replies short.", engine.url)
reply, _ = brain.chat("e2e", "hi! my name is Sam and I love Roblox. say hi back.")
print("REPLY:", reply)
assert reply.strip()
engine.stop()
print("E2E OK")
