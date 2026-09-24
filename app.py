"""Flip - your own animated AI buddy. This file starts everything."""

import atexit
import json
import logging
import os
import sys
import threading
import time

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
                "sounddevice", "edge_tts", "kokoro_onnx", "pystray", "PIL", "brain", "engine", "voice", "store", "storage", "updater", "screen", "autotest"):
        try:
            __import__(mod)
            lines.append(f"ok {mod}")
        except BaseException as e:  # sounddevice raises OSError when there's no audio device, that's fine
            lines.append(f"{'ok' if mod == 'sounddevice' and isinstance(e, OSError) else 'FAIL'} {mod}: {e!r}")
    for f in ("ui/index.html", "ui/pet.html", "ui/app.js", "ui/desk.js", "ui/pet.js", "ui/pet.css",
              "ui/style.css", "personality.txt", "flip.ico", "skills/valorant.txt", "version.txt"):
        lines.append(f"{'ok' if (RES / f).exists() else 'FAIL'} file {f}")
    import faster_whisper
    assets = os.path.join(os.path.dirname(faster_whisper.__file__), "assets")
    lines.append(f"{'ok' if os.path.isdir(assets) and os.listdir(assets) else 'FAIL'} whisper assets")
    try:  # really speak once with his own voice (downloads the voice model)
        import voice
        v = voice.Voice({})
        clip = v.say("testing, one two three")
        lines.append(f"{'ok' if clip and clip['mime'] == 'audio/wav' and len(clip['audio']) > 10000 else 'FAIL'} his voice speaks")
    except BaseException as e:
        lines.append(f"FAIL his voice speaks: {e!r}")
    try:
        from faster_whisper.vad import get_vad_model
        import numpy as np
        get_vad_model()(np.zeros(512 * 4, dtype=np.float32))
        lines.append("ok speech detector")
    except BaseException as e:
        lines.append(f"FAIL speech detector: {e!r}")
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

import screen  # noqa: E402
import storage  # noqa: E402
from updater import Updater  # noqa: E402
import store  # noqa: E402
from brain import Brain, NoModelError  # noqa: E402
from engine import Engine  # noqa: E402
from voice import VOICES, Voice, list_mics  # noqa: E402


def load_skills():
    """Extra know-how (like Valorant) from the skills folders: built-in ones plus any .txt the user adds."""
    texts = []
    for folder in (RES / "skills", DATA / "skills"):
        for f in sorted(folder.glob("*.txt")) if folder.is_dir() else []:
            try:
                texts.append(f.read_text(encoding="utf-8").strip())
            except OSError:
                pass
    return texts


def _native_form(window, timeout=15):
    """The Windows Forms window behind a pywebview window (waits until it exists)."""
    from webview.platforms.winforms import BrowserView

    deadline = time.time() + timeout
    while time.time() < deadline:
        form = BrowserView.instances.get(window.uid)
        if form is not None:
            try:
                if form.IsHandleCreated and form.Visible:
                    return form
            except Exception:
                pass
        time.sleep(0.2)
    return None


def _on_ui_thread(form, fn):
    from System import Func, Type

    form.Invoke(Func[Type](fn))


def see_through(window):
    """Makes the desktop pet's window background invisible (pywebview leaves it grey on Windows)."""
    if sys.platform != "win32":
        return
    try:
        from System.Drawing import Color

        form = _native_form(window)
        if form is None:
            log.warning("Pet window never showed up, can't make it see-through")
            return

        def apply():
            key = Color.FromArgb(255, 1, 1, 1)  # this exact color becomes see-through (and click-through)
            form.BackColor = key
            form.TransparencyKey = key
            for control in form.Controls:
                control.BackColor = key

        _on_ui_thread(form, apply)
        log.info("Pet window is see-through")
    except Exception:
        log.exception("Couldn't make the pet window see-through")


_mic_handlers = []  # keeps the permission handler alive


def allow_mic(window):
    """Lets the chat window use the mic without a popup (voice calls record through it, since the
    browser's mic has echo cancellation: he doesn't hear himself and you can talk over him)."""
    if sys.platform != "win32":
        return
    try:
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionKind, CoreWebView2PermissionState

        form = _native_form(window, timeout=60)
        if form is None:
            return

        def on_permission(sender, args):
            if args.PermissionKind == CoreWebView2PermissionKind.Microphone:
                args.State = CoreWebView2PermissionState.Allow

        _mic_handlers.append(on_permission)
        attached = []

        def attach():
            core = form.browser.webview.CoreWebView2
            if core is not None and not attached:
                core.PermissionRequested += on_permission
                attached.append(True)

        deadline = time.time() + 60
        while not attached and time.time() < deadline:
            _on_ui_thread(form, attach)
            if not attached:
                time.sleep(0.3)
        log.info("Mic permission handler %s", "ready" if attached else "never attached")
    except Exception:
        log.exception("Couldn't set up the mic permission")


def dark_title_bar(window):
    """Windows draws a white title bar by default; ask for the dark one."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        form = _native_form(window)
        if form is None:
            return
        hwnd = form.Handle.ToInt64()
        on = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (newer, then older Windows 10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr, ctypes.byref(on), 4) == 0:
                break
        # make Windows redraw the frame so the dark title bar shows up right away
        flags = 0x0001 | 0x0002 | 0x0004 | 0x0020  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED
        ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(hwnd), None, 0, 0, 0, 0, flags)
    except Exception:
        log.exception("Couldn't make the title bar dark")


class Api:
    """Everything the two windows (chat + desktop pet) can ask Python to do."""

    def __init__(self, settings):
        self._settings = settings
        self._engine = Engine(settings)
        self._brain = Brain(settings, personality_file().read_text(encoding="utf-8"), self._engine.url, load_skills())
        self._brain.on_tool = self._on_tool
        self._engine.on_ready = self._warm_up
        self._voice = Voice(settings)
        self._updater = Updater()
        self._main = None
        self._pet = None
        self._tray = None
        self._quitting = False
        self._chat_hidden = False
        self._stop = threading.Event()
        self._voice_on = False
        self._share = None  # {"id", "title"} of the screen/window he can see

    # ---------- startup info ----------

    def hello(self):
        info = {"name": self._settings["name"], "pet": self._pet is not None, "account": None,
                "has_accounts": bool(store.accounts())}
        remembered = store.get_account(self._settings.get("remember_account") or "")
        if store.account is None and remembered:
            store.use_account(remembered)
        if store.account is not None:
            info["account"] = self._account_info()
        return info

    # ---------- accounts ----------

    def _account_info(self):
        return {"username": store.account["username"], "profiles": store.public_profiles(),
                "last": self._settings.get("last_profile")}

    def _logged_in(self, acct, remember):
        store.use_account(acct)
        self._settings["remember_account"] = acct["id"] if remember else None
        save_settings(self._settings)
        return {"account": self._account_info()}

    def create_account(self, username, password, remember=True):
        try:
            return self._logged_in(store.create_account(username, password), remember)
        except ValueError as e:
            return {"error": str(e)}

    def login(self, username, password, remember=True):
        try:
            return self._logged_in(store.login(username, password), remember)
        except ValueError as e:
            return {"error": str(e)}

    def log_out(self):
        store.log_out()
        self._settings["remember_account"] = None
        save_settings(self._settings)
        return True

    def change_password(self, old, new):
        try:
            store.change_password(store.account["id"], old, new)
            return {"ok": True}
        except ValueError as e:
            return {"error": str(e)}

    def account_profiles(self):
        return self._account_info() if store.account else None

    # ---------- profiles ----------

    def _warm_up(self):
        if store.current is not None and self._engine.status["state"] == "ready":
            self._brain.warm_up()

    def _enter(self, prof):
        store.use_profile(prof)
        self._voice.names = [prof["name"], self._settings["name"]]  # so speech-to-text spells them right
        threading.Thread(target=self._warm_up, daemon=True).start()
        self._settings["last_profile"] = prof["id"]
        save_settings(self._settings)
        chats = store.list_chats()
        chat = store.load_chat(chats[0]["id"]) if chats else store.new_chat()
        return {"profile": {"id": prof["id"], "name": prof["name"], "color": prof["color"]}, "chat": chat}

    def enter_profile(self, profile_id, pin=""):
        prof = store.check_pin(profile_id, pin)
        return self._enter(prof) if prof else {"error": "wrong PIN 🙅"}

    def create_profile(self, name, pin=""):
        if store.account is None:
            return {"error": "log in first"}
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

    def set_fast(self, on):
        self._engine.set_fast(on)
        save_settings(self._settings)
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
        self._stop.clear()
        buf, last = [], [0.0]

        def flush():
            if buf and self._main:
                self._main.evaluate_js(f"onText({json.dumps(''.join(buf))})")
                buf.clear()
            last[0] = time.time()

        def on_text(piece):  # send the reply to the window in small batches as it's written
            buf.append(piece)
            if time.time() - last[0] > 0.05:
                flush()

        image, label = None, ""
        if self._share:
            image = screen.capture(self._share["id"])
            label = self._share["title"]
            if image is None:  # the window got closed
                self._share = None
                if self._main:
                    self._main.evaluate_js("onShareEnded()")
        def on_reset():  # he's redoing a reply that repeated an earlier one
            buf.clear()
            if self._main:
                self._main.evaluate_js("onResetText()")

        try:
            reply, chat, stopped = self._brain.chat(chat_id, text, voice, on_text, self._stop, image, label, on_reset)
            flush()
            if self._pet is not None and (self._chat_hidden or voice) and not stopped:
                self.pet_say(reply)
            return {"reply": reply, "stopped": stopped, "chat_id": chat["id"], "title": chat["title"],
                    "secs": self._brain.last_stats.get("secs")}
        except APIConnectionError:
            return {"error": "yo I can't reach my brain 💀 try closing and reopening me."}
        except NoModelError:
            return {"error": "bro my brain has no model loaded 😭"}
        except APIStatusError as e:
            log.exception("Model error")
            if "context" in str(e).lower():
                return {"error": "that was too much for my brain to read at once 😵 try a new chat"}
            return {"error": f"my brain glitched 😵 try again? ({e.status_code})"}
        except Exception as e:
            log.exception("Chat failed")
            return {"error": f"something broke 😭 ({e})"}

    def stop(self):
        self._stop.set()

    # ---------- screen sharing ----------

    def share_sources(self):
        if not self._engine.status.get("vision"):
            return {"error": "my brain can't see pictures yet 👀 (it's still loading, or you're using your own AI server)"}
        return {"sources": screen.sources(own_titles=(self._settings["name"],))}

    def share_start(self, source_id, title):
        preview = screen.capture(source_id)
        if preview is None:
            return {"error": "couldn't see that one 😵 pick another?"}
        self._share = {"id": source_id, "title": title}
        return {"preview": preview}

    def share_stop(self):
        self._share = None
        return True

    def list_chats(self):
        return store.list_chats()

    def rename_chat(self, chat_id, title):
        store.update_chat(chat_id, title=title)
        return store.list_chats()

    def pin_chat(self, chat_id, pinned):
        store.update_chat(chat_id, pinned=pinned)
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
        info = {k: self._settings.get(k) for k in ("name", "voice", "voice_style", "talk_speed", "mic", "roblox_studio",
                                                   "brain_size")}
        info["voices"] = VOICES
        try:
            info["mics"] = list_mics()
        except Exception:
            log.exception("Couldn't list mics")
            info["mics"] = []
        return info

    def save_settings(self, changes):
        new_brain = "brain_size" in changes and changes["brain_size"] != (self._settings.get("brain_size") or "smart")
        for k in ("name", "voice", "voice_style", "talk_speed", "mic", "roblox_studio", "brain_size"):
            if k in changes:
                self._settings[k] = changes[k]
        save_settings(self._settings)
        if new_brain:
            self._engine.switch_brain()
        return {"brain_switching": new_brain}

    def storage_report(self):
        return storage.report()

    def clean_up(self):
        freed = storage.clean_up()
        return {"freed_gb": freed, "report": storage.report()}

    def delete_everything(self, delete_app=False):
        self._engine.stop()
        storage.delete_everything(bool(delete_app))
        threading.Timer(0.5, self.quit).start()
        return True

    def check_update(self):
        return self._updater.check()

    def install_update(self):
        return self._updater.install(self.quit)

    def update_status(self):
        return self._updater.status

    def open_folder(self):
        os.startfile(DATA) if sys.platform == "win32" else None

    # ---------- voice ----------

    def say(self, text):
        return self._voice.say(text)

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

    # Voice calls through the chat window's mic: it sends audio here, what they say comes back
    # through onHeard(text).

    def voice_call_start(self):
        def heard(text):
            if self._main:
                self._main.evaluate_js(f"onHeard({json.dumps(text)})")

        try:
            self._voice.call_start(heard)
            return {}
        except Exception as e:
            log.exception("Voice call couldn't start")
            return {"error": f"my ears glitched 😵 ({e})"}

    def voice_feed(self, pcm, speaking=False):
        return self._voice.call_feed(pcm, bool(speaking))

    def voice_call_stop(self):
        self._voice.call_stop()

    def mic_level(self):
        return self._voice.level

    def mic_name(self):
        """The name of the mic picked in Settings ("" for the Windows default)."""
        mic = self._settings.get("mic")
        if mic is None:
            return ""
        try:
            return next((m["name"] for m in list_mics() if m["id"] == mic), "")
        except Exception:
            return ""

    # ---------- desktop pet ----------

    def show_pet(self):
        if self._pet is None:
            screen = webview.screens[0]
            x, y = self._settings.get("pet_pos") or (screen.width - 250, screen.height - 310)
            self._pet = webview.create_window(
                "Flip pet", "ui/pet.html", js_api=self, width=230, height=270, x=x, y=y,
                frameless=True, transparent=True, on_top=self._settings.get("pet_pinned", True),
                resizable=False, easy_drag=True, background_color="#010101",
            )
            self._pet.events.closed += self._pet_closed
            pet = self._pet
            threading.Thread(target=see_through, args=(pet,), daemon=True).start()
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

    def pet_info(self):
        return {"pinned": self._settings.get("pet_pinned", True), "voice": self._voice_on}

    def pet_pin(self, on):
        self._settings["pet_pinned"] = bool(on)
        save_settings(self._settings)
        if self._pet is not None:
            self._pet.on_top = bool(on)
        return bool(on)

    def pet_voice(self):
        """The voice button on the desktop pet: start or end a voice chat (run by the chat window)."""
        if store.current is None:
            self.pet_say("open the chat and log in first 👀")
            return False
        if self._main:
            self._main.evaluate_js("toggleVoiceFromPet()")
        return True

    def pet_interrupt(self):
        if self._main:
            self._main.evaluate_js("stopReply()")

    def voice_state(self, on):
        self._voice_on = bool(on)
        if self._pet is not None:
            self._pet.evaluate_js(f"voiceChanged({json.dumps(self._voice_on)})")

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
        threading.Thread(target=dark_title_bar, args=(self._main,), daemon=True).start()
        threading.Thread(target=allow_mic, args=(self._main,), daemon=True).start()
        threading.Thread(target=storage.tidy_on_start, daemon=True).start()
        self._engine.start()
        threading.Thread(target=self._voice.preload, daemon=True).start()
        self._start_tray()
        if self._settings.get("pet_visible"):
            self.show_pet()
        if os.environ.get("FLIP_SCREENSHOT"):  # used by the build to check the real windows
            threading.Thread(target=self._screenshot, daemon=True).start()
        if os.environ.get("FLIP_AUTOTEST"):  # used by the build: clicks through the whole app
            import autotest
            threading.Thread(target=autotest.run, args=(self,), daemon=True).start()

    def _screenshot(self):
        try:
            from PIL import ImageGrab

            time.sleep(float(os.environ.get("FLIP_SCREENSHOT_WAIT", "25")))
            ImageGrab.grab(all_screens=True).save(os.environ["FLIP_SCREENSHOT"])
        except Exception:
            log.exception("Screenshot failed")
        finally:
            self.quit()

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
        self._voice.call_stop()
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
