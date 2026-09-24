"""Sets up a demo account in FLIP_HOME so the build can screenshot the real app."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store  # noqa: E402
from paths import DATA, load_settings, save_settings  # noqa: E402

acct = store.create_account("demo", "password1")
store.use_account(acct)
prof = store.create_profile("Marru")
store.use_profile(prof)
chat = store.new_chat()
chat["title"] = "jett tips for ascent"
chat["messages"] = [
    {"role": "user", "content": "how do I play jett on ascent"},
    {"role": "assistant", "content": "bet 😤 **Jett on Ascent** is all about taking A main early.\n\n"
                                     "Dash in behind a smoke, get the pick, updraft out. Don't re-peek the same angle fr."},
]
chat["updated"] = time.time()
store.save_chat(chat)

s = load_settings()
s.update({"remember_account": acct["id"], "pet_visible": True, "llm_url": "http://127.0.0.1:9/v1",
          "roblox_studio": False})
save_settings(s)
print("demo ready in", DATA, json.dumps(s)[:200])
