"""Flip - your own animated AI buddy. This file starts everything."""

import atexit
import json
import logging
import os
import sys
import threading

from paths import DATA, RES, load_settings, personality_file, save_settings

_log_file = open(DATA / "flip.log", "a", encoding="utf-8", buffering=1)
if sys.stdout is None:  # no console when running as Flip.exe
    sys.stdout = _log_file
if sys.stderr is None:
    sys.stderr = _log_file
logging.basicConfig(stream=_log_file, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("flip")


def selftest(out_path):
    """Used by the build: checks that everything Flip needs made it into the .exe."""
    lines = []
    for mod in ("webview", "clr", "openai", "mcp", "mcp.client.stdio", "faster_whisper", "ctranslate2", "onnxruntime", "numpy",
                "sounddevice", "edge_tts", "pystray", "PIL", "brain", "engine", "voice", "store"):
        try:
            __import__(mod)
            lines.append(f"ok {mod}")
        except BaseException as e:  # sounddevice raises OSError when there's no audio device, that's fine
            lines.append(f"{'ok' if mod == 'sounddevice' and isinstance(e, OSError) else 'FAIL'} {mod}: {e!r}")
    for f in ("ui/index.html", "ui/pet.html", "ui/app.js", "ui/desk.js", "ui/pet.js", "ui/pet.css",
              "ui/style.css", "personality.txt", "flip.ico"):
        lines.append(f"{'ok' if (RES / f).exists() else 'FAIL'} file {f}")
    import faster_whisper
    assets = os.path.join(os.path.dirname(faster_whisper.__file__), "assets")
    lines.append(f"{'ok' if os.path.isdir(assets) and os.listdir(assets) else 'FAIL'} whisper assets")
    try:  # really run speech-to-text once (downloads the tiny model)
        import numpy as np
        model = faster_whisper.WhisperModel("tiny.en", device="cpu", compute_type="int8")
        list(model.transcribe(np.zeros(16000, dtype=np.float32), vad_filter=True)[0])
        lines.append("ok whisper runs")
    except BaseException as e:
        lines.append(f"FAIL whisper runs: {e!r}")
    lines.append("DONE")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
    selftest(sys.argv[2])
    sys.exit(0)

import webview  # noqa: E402
from openai import APIConnectionError, APIStatusError  # noqa: E402

import store  # noqa: E402
from brain import Brain, NoModelError  # noqa: E402
from engine import Engine  # noqa: E402
from voice import Voice  # noqa: E402


class Api:
    """Everything the two windows (chat + desktop pet) can ask Python to do."""

    def __init__(self, settings):
        self._settings = settings
        self._engine = Engine(settings)
        self._brain = Brain(settings, personality_file().read_text(encoding="utf-8"), self._engine.url)
        self._brain.on_tool = self._on_tool
        self._voice = Voice(settings)
        self._main = None
        self._pet = None
        self._tray = None
        self._quitting = False
        self._chat_hidden = False

    # ---------- startup info ----------

    def hello(self):
        return {"name": self._settings["name"], "pet": self._pet is not None,
                "profiles": store.public_profiles(), "last": self._settings.get("last_profile")}

    # ---------- profiles ----------

    def _enter(self, prof):
        store.use_profile(prof)
        self._settings["last_profile"] = prof["id"]
        save_settings(self._settings)
        chats = store.list_chats()
        chat = store.load_chat(chats[0]["id"]) if chats else store.new_chat()
        return {"profile": {"id": prof["id"], "name": prof["name"], "color": prof["color"]}, "chat": chat}

    def enter_profile(self, profile_id, pin=""):
        prof = store.check_pin(profile_id, pin)
        return self._enter(prof) if prof else {"error": "wrong PIN 🙅"}

    def create_profile(self, name, pin=""):
        try:
            return self._enter(store.create_profile(name, pin))
        except ValueError as e:
            return {"error": str(e)}

    def delete_profile(self, profile_id, pin=""):
        if not store.check_pin(profile_id, pin):
            return {"error": "wrong PIN 🙅"}
        store.delete_profile(profile_id)
        return {"profiles": store.public_profiles()}

    def brain_status(self):
        return self._engine.status

    def retry_brain(self):
        self._engine.start()

    def status(self):
        return {"roblox": self._brain.roblox_status()}

    # ---------- chatting ----------

    def send(self, chat_id, text, voice=False):
        if store.current is None:
            return {"error": "pick a profile first 👤"}
        if self._engine.status["state"] != "ready":
            return {"error": "hold up, my brain is still loading 🧠 give me a sec"}
        try:
            reply, chat = self._brain.chat(chat_id, text, voice)
            if self._chat_hidden:
                self.pet_say(reply)
            return {"reply": reply, "chat_id": chat["id"], "title": chat["title"]}
        except APIConnectionError:
            return {"error": "yo I can't reach my brain 💀 try closing and reopening me."}
        except NoModelError:
            return {"error": "bro my brain has no model loaded 😭"}
        except APIStatusError as e:
            log.exception("Model error")
            return {"error": f"my brain threw an error 😵 ({e.status_code}): {e.message}"}
        except Exception as e:
            log.exception("Chat failed")
            return {"error": f"something broke 😭 ({e})"}

    def list_chats(self):
        return store.list_chats()

    def open_chat_id(self, chat_id):
        return store.load_chat(chat_id)

    def new_chat(self):
        return store.new_chat()

    def delete_chat(self, chat_id):
        store.delete_chat(chat_id)
        return store.list_chats()

    # ---------- memory ----------

    def memories(self):
        return store.memories()

    def forget(self, mem_id):
        store.forget(mem_id)
        return store.memories()

    def remember(self, text):
        store.remember(text)
        return store.memories()

    # ---------- settings ----------

    def get_settings(self):
        return {k: self._settings.get(k) for k in ("name", "voice", "roblox_studio")}

    def save_settings(self, changes):
        for k in ("name", "voice", "roblox_studio"):
            if k in changes:
                self._settings[k] = changes[k]
        save_settings(self._settings)
        return True

    def open_folder(self):
        os.startfile(DATA) if sys.platform == "win32" else None

    # ---------- voice ----------

    def speak(self, text):
        return self._voice.speak(text)

    def listen_start(self):
        try:
            self._voice.start_listening()
            return {}
        except Exception as e:
            log.exception("Mic failed")
            return {"error": f"can't hear you, I couldn't open your mic 🎤 ({e})"}

    def listen_stop(self):
        try:
            return {"text": self._voice.stop_listening()}
        except Exception as e:
            log.exception("Speech-to-text failed")
            return {"error": f"my ears glitched 😵 ({e})"}

    def voice_listen(self):
        try:
            text = self._voice.listen_utterance()
            return {"ended": True} if text is None else {"text": text}
        except Exception as e:
            log.exception("Voice chat mic failed")
            return {"error": f"can't hear you, I couldn't open your mic 🎤 ({e})"}

    def voice_cancel(self):
        self._voice.cancel_listening()

    def mic_level(self):
        return self._voice.level

    # ---------- desktop pet ----------

    def show_pet(self):
        if self._pet is None:
            screen = webview.screens[0]
            x, y = self._settings.get("pet_pos") or (screen.width - 250, screen.height - 310)
            self._pet = webview.create_window(
                "Flip pet", "ui/pet.html", js_api=self, width=230, height=250, x=x, y=y,
                frameless=True, transparent=True, on_top=True, resizable=False, easy_drag=True,
                background_color="#000000",
            )
            self._pet.events.closed += self._pet_closed
        self._settings["pet_visible"] = True
        save_settings(self._settings)
        self._update_tray()
        return True

    def hide_pet(self):
        pet = self._pet
        if pet is not None:
            self._settings["pet_pos"] = [pet.x, pet.y]
            self._settings["pet_visible"] = False
            save_settings(self._settings)
            pet.destroy()
        return True

    def _pet_closed(self):
        self._pet = None
        self._update_tray()
        if self._main:
            self._main.evaluate_js("onPetChanged(false)")
        if self._chat_hidden and not self._quitting:
            self.open_chat()

    def pet_visible(self):
        return self._pet is not None

    def pet_state(self, state):
        if self._pet is not None:
            self._pet.evaluate_js(f"mirror({json.dumps(state)})")

    def pet_say(self, text):
        if self._pet is not None:
            self._pet.evaluate_js(f"say({json.dumps(text)})")

    def open_chat(self):
        self._chat_hidden = False
        if self._main:
            self._main.show()
            self._main.restore()

    # ---------- plumbing ----------

    def _on_tool(self, name):
        if self._main:
            self._main.evaluate_js(f"onTool({json.dumps(name)})")

    def _on_main_closing(self):
        if self._quitting:
            return True
        if self._pet is not None:
            # The pet stays on the desktop; just tuck the chat away.
            self._chat_hidden = True
            self._main.hide()
            return False
        self.quit(close_main=False)
        return True

    def _startup(self):
        self._engine.start()
        threading.Thread(target=self._voice.preload, daemon=True).start()
        self._start_tray()
        if self._settings.get("pet_visible"):
            self.show_pet()

    def _start_tray(self):
        try:
            import pystray
            from PIL import Image

            menu = pystray.Menu(
                pystray.MenuItem("Open chat", lambda: self.open_chat(), default=True),
                pystray.MenuItem("Show pet on desktop", lambda: self.hide_pet() if self._pet else self.show_pet(),
                                 checked=lambda item: self._pet is not None),
                pystray.MenuItem("Open Flip's folder", lambda: self.open_folder()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda: self.quit()),
            )
            self._tray = pystray.Icon("Flip", Image.open(RES / "flip.ico"), self._settings["name"], menu)
            self._tray.run_detached()
        except Exception:
            log.exception("Tray icon failed")

    def _update_tray(self):
        if self._tray:
            self._tray.update_menu()

    def quit(self, close_main=True):
        self._quitting = True
        self._voice.cancel_listening()
        self._engine.stop()
        if self._tray:
            self._tray.stop()
        if self._pet is not None:
            self._pet.destroy()
        if self._main and close_main:
            self._main.destroy()


def main():
    settings = load_settings()
    api = Api(settings)
    atexit.register(api._engine.stop)
    window = webview.create_window(
        settings["name"], "ui/index.html", js_api=api,
        width=460, height=780, min_size=(380, 600), background_color="#15131f",
    )
    window.events.closing += api._on_main_closing
    api._main = window
    log.info("Starting %s", settings["name"])
    webview.start(api._startup)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Flip crashed")
        raise
