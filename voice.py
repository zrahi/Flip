"""Flip's ears (mic + speech-to-text) and mouth (text-to-speech)."""

import asyncio
import base64
import logging
import queue
import re
import threading
import time
from collections import deque

import numpy as np

log = logging.getLogger("flip")

RATE = 16000
CHUNK_SEC = 0.03

# His voice runs on the PC (Kokoro): downloaded once (~200 MB), no internet needed after that.
# The fp16 model talks about 4x faster on a normal CPU than the smaller int8 one.
VOICE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
VOICE_MODEL = "kokoro-v1.0.fp16.onnx"
VOICE_STYLES = "voices-v1.0.bin"
DEFAULT_VOICE = "am_fenrir"  # the youngest-sounding of the good male voices
VOICES = {"am_fenrir": "Fenrir (young, default)", "am_puck": "Puck (playful)", "am_michael": "Michael (chill)",
          "am_eric": "Eric (bright)", "am_liam": "Liam (soft)", "bm_george": "George (British)"}
DEFAULT_SPEED = 1.25  # talking speed: a bit quicker than Kokoro's normal, still easy to follow
# How much higher each style sounds (and a tiny bit quicker; the talking speed makes up for it).
PITCH = {"cute": 1.12, "normal": 1.0, "deep": 0.92}

CODE_BLOCK = re.compile(r"```.*?(```|$)", re.S)
URL = re.compile(r"https?://\S+")
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")
# Things speech-to-text "hears" in silence or background noise.
NOISE_WORDS = {"", "you", "thank you", "thank you.", "thanks for watching!", "bye.", ".", "uh", "um", "hmm"}


def say_math(tex):
    """LaTeX → words, roughly how you'd read it out."""
    t = tex
    for _ in range(3):
        t = re.sub(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}", r" \1 over \2 ", t)
        t = re.sub(r"\\sqrt\{([^{}]*)\}", r" the square root of \1 ", t)
    words = {r"\cdot": " times ", r"\times": " times ", r"\div": " divided by ", r"\pm": " plus or minus ",
             r"\le": " is at most ", r"\ge": " is at least ", r"\neq": " is not ", r"\approx": " is about ",
             r"\pi": " pi ", r"\infty": " infinity ", r"\theta": " theta ", r"\sin": " sine ", r"\cos": " cos ",
             r"\tan": " tan ", r"\log": " log ", r"\ln": " natural log ", "^2": " squared ", "^3": " cubed "}
    for k, v in words.items():
        t = t.replace(k, v)
    t = re.sub(r"\^\{?([^{}\s]+)\}?", r" to the power of \1 ", t)
    t = re.sub(r"\\[a-zA-Z]+", " ", t).replace("{", " ").replace("}", " ")
    t = t.replace("=", " equals ").replace("<", " is less than ").replace(">", " is more than ")
    t = re.sub(r"(?<=\w)\s*-\s*(?=\w)", " minus ", t).replace("+", " plus ")
    return re.sub(r"\s+", " ", t).strip()


MATH_TEX = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\\((.+?)\\\)|\$(?![\s$])([^$\n]+?)(?<!\s)\$(?!\d)", re.S)


def speakable(text):
    """Turn a chat reply into something that sounds good out loud."""
    text = CODE_BLOCK.sub(" I dropped the code in the chat. ", text)
    text = MATH_TEX.sub(lambda m: " " + say_math(next(g for g in m.groups() if g)) + " ", text)
    text = URL.sub(" the link ", text)
    text = EMOJI.sub("", text)
    text = re.sub(r"[`*_#>|]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 700:
        cut = text[:700]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = cut[: end + 1] if end > 200 else cut
    return text


# Speech-to-text. "small" keeps up with fast talkers, where "base" turns quick speech into mush, so calls use
# it on every PC that runs it in time (it used to need to be twice as fast). (distil-small.en was tried: on
# real speech with the hint words it looped "how how how…", so it's out.)
EARS = "small.en"
BACKUP_EARS = "base.en"   # only on PCs too slow for EARS
CAPTION_EARS = "tiny.en"  # live captions while they talk (fastest; the final text uses EARS)
SPEECH_MODELS = (EARS, BACKUP_EARS, CAPTION_EARS, "distil-small.en", "medium.en", "small", "base", "tiny")
EARS_MAX = 1.4            # s for 3 s of audio: slower than this and calls fall back to BACKUP_EARS
UNSURE = -0.75            # average log-probability under which a quick transcript gets a careful second look

# When they've stopped talking: answer after END_FAST of quiet if what they said sounds finished
# ("what should I buy?"), otherwise wait up to END_SLOW ("so what about the…").
END_FAST = 0.25
END_SLOW = 0.8
FINAL_AFTER = 3        # frames of quiet (~0.1 s) before the final speech-to-text starts
CAPTION_EVERY = 30     # frames of speech (~1 s) between live captions
TRAILING = set("and but so or because cause like um uh the a an to of with if then my your our their is are was "
               "were should could would can do does did i you we they he she it for on in at about from that this "
               "than as".split())


def sounds_finished(text):
    """Whisper ends finished sentences with . ? or !; a trailing "and"/"the" means there's more coming."""
    t = text.strip()
    if not t or not t.endswith((".", "?", "!")) or t.endswith(("...", "…")):
        return False
    if t.endswith("?"):  # a question is a question, even one ending in "why?" or "is it?"
        return True
    last = re.sub(r"[^a-z']", "", t.split()[-1].lower())
    return last not in TRAILING

FRAME = 512  # 32 ms at 16 kHz: the size the speech detector works on

# How he expects to be talked to, so speech-to-text spells game words right and keeps up with fast, casual talk.
# (Sentences, not a list of names: a bare list of agents made it hear "Yoru" in "yo jett is on me".)
HINT_WORDS = ("Yo Flip, what's up bro. Jett is on me, I'm playing Lotus rn, two A one heaven. Reyna and Raze are "
              "pushing B, Omen smoke, Sova recon dart, Viper wall, Killjoy turret, Cypher cam, Sage wall, Brimstone "
              "molly. Should I buy a Vandal or Phantom, Sheriff or Spectre on eco? Ascent, Haven, Bind, Split, Icebox, "
              "Breeze, Pearl, Sunset, Abyss, Fracture. Ngl that was a clutch, one tap, gg, lol. Coach me.")


class Ears:
    """Speech detector: for each 32 ms slice of audio, how likely it is that someone's talking."""

    def __init__(self):
        self._vad = None
        try:
            from faster_whisper.vad import get_vad_model
            self._vad = get_vad_model()
        except Exception:
            log.exception("Speech detector unavailable, going by loudness")
        self._window = np.zeros(0, dtype=np.float32)

    def speech_chance(self, frame):
        rms = float(np.sqrt(np.mean(frame ** 2)))
        if self._vad is None:
            return min(1.0, rms * 25)
        # look at the last half second so it has some context, and take the newest slice's answer
        self._window = np.concatenate([self._window, frame])[-FRAME * 16:]
        usable = self._window[-(len(self._window) // FRAME) * FRAME:]
        return float(np.asarray(self._vad(usable)).reshape(-1)[-1])


class UtteranceDetector:
    """Figures out when someone starts talking and when they've finished."""

    def __init__(self, chance=None, end_silence=0.6, max_len=30.0):
        self.chance = chance or Ears().speech_chance
        frame_sec = FRAME / RATE
        self.end_frames = int(end_silence / frame_sec)
        self.max_frames = int(max_len / frame_sec)
        self.pre = deque(maxlen=int(0.5 / frame_sec))  # keep the half second before they start
        self.speech = []
        self.talking = False
        self.voiced = 0
        self.silent = 0
        self.said = 0
        self.last_said = 0

    def reset(self):
        """Forget the current utterance (it's been handled)."""
        self.talking = False
        self.voiced = self.silent = self.said = 0
        self.speech = []
        self.pre.clear()

    def feed(self, frame, strict=False):
        """Feed 512 samples at 16 kHz. Returns the finished utterance once they stop talking, else None.
        strict: he's talking right now, so it takes clearer, longer speech to count (leftover echo doesn't)."""
        p = self.chance(frame)
        if not self.talking:
            self.pre.append(frame)
            self.voiced = self.voiced + 1 if p > (0.7 if strict else 0.5) else 0
            if self.voiced >= (6 if strict else 3):  # about 0.2 s (or 0.1 s) of real speech
                self.talking = True
                self.speech = list(self.pre)
                self.silent = 0
                self.said = self.voiced
            return None
        self.speech.append(frame)
        if p > 0.35:
            self.silent = 0
            self.said += 1
        else:
            self.silent += 1
        if self.silent >= self.end_frames or len(self.speech) >= self.max_frames:
            audio, said = np.concatenate(self.speech), self.said
            self.last_said = said
            self.talking = False
            self.voiced = self.silent = self.said = 0
            self.speech = []
            self.pre.clear()
            return audio if said >= 6 else None  # skip coughs and clicks
        return None


def list_mics():
    """[{"id", "name"}] of the microphones on this PC."""
    import sounddevice as sd

    try:
        default_api = sd.default.hostapi if isinstance(sd.default.hostapi, int) else 0
    except Exception:
        default_api = 0
    mics, seen = [], set()
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and d["hostapi"] == default_api and d["name"] not in seen:
            seen.add(d["name"])
            mics.append({"id": i, "name": d["name"]})
    return mics


class Voice:
    def __init__(self, settings):
        self._s = settings
        self._whisper = {}
        self._whisper_lock = threading.Lock()
        self._ears_lock = threading.Lock()  # one speech-to-text run at a time
        self._stream = None
        self._frames = []
        self._rate = RATE
        self._cancel = threading.Event()
        self._kokoro = None
        self._mouth_lock = threading.Lock()
        self._say_lock = threading.Lock()
        self.level = 0.0
        self.names = []
        self.call_ears = EARS  # may become BACKUP_EARS after preload() times it on a slow PC

    # ---------- ears ----------

    def preload(self):
        """Loads (and runs once) the ears and the voice, so the first real call doesn't pay for it."""
        rng = np.random.default_rng(0)
        hiss = rng.normal(0, 0.01, RATE).astype(np.float32)
        took = {}
        for which in ("tiny", True):
            try:
                model = self._get_whisper(which)
                for _ in range(2):  # the second run is the real speed
                    t = time.time()
                    list(model.transcribe(np.tile(hiss, 3), language="en", beam_size=1, without_timestamps=True,
                                          chunk_length=5, temperature=0.0)[0])
                    took[which] = time.time() - t
            except Exception:
                log.exception("Couldn't load speech-to-text")
        if took.get(True, 0) > EARS_MAX:  # a really slow PC: understanding late is worse than a few typos
            self.call_ears = BACKUP_EARS
        log.info("Speech-to-text speed: %s -> calls use %s",
                 {("captions" if k == "tiny" else "calls"): round(v, 2) for k, v in took.items()}, self.call_ears)
        self._forget_old_ears()
        self.preload_mouth()

    def _ears_for(self, quick):
        """tiny: live captions. quick: voice calls. Otherwise click-to-talk, where a moment longer is fine."""
        if quick == "tiny":
            return CAPTION_EARS
        return self.call_ears if quick else self._s.get("whisper_model") or EARS

    def _forget_old_ears(self):
        """Speech models that aren't used anymore (older versions downloaded 3) get deleted."""
        import shutil

        from paths import DATA
        keep = {CAPTION_EARS, self.call_ears, self._ears_for(False)}
        for name in SPEECH_MODELS:
            folder = DATA / "speech" / name
            if name not in keep and folder.is_dir():
                shutil.rmtree(folder, ignore_errors=True)
                log.info("Deleted the unused %s speech model", name)

    def _get_whisper(self, quick=False):
        """quick (voice calls) and click-to-talk: EARS (or the user's own pick for click-to-talk).
        "tiny": live captions."""
        size = self._ears_for(quick)
        with self._whisper_lock:
            if size not in self._whisper:
                import shutil

                from faster_whisper import WhisperModel
                from faster_whisper.utils import download_model

                from paths import DATA
                folder = DATA / "speech" / size
                if not (folder / "model.bin").exists():
                    # a plain folder: the default download kept a second copy of the model on Windows
                    download_model(size, output_dir=str(folder))
                try:
                    model = WhisperModel(str(folder), device="cpu", compute_type="int8", cpu_threads=_threads())
                except RuntimeError:  # a broken or cut-off download: get it again instead of staying deaf
                    log.exception("Speech model %s is broken, downloading it again", size)
                    shutil.rmtree(folder, ignore_errors=True)
                    download_model(size, output_dir=str(folder))
                    model = WhisperModel(str(folder), device="cpu", compute_type="int8", cpu_threads=_threads())
                self._whisper[size] = model
                for old in (DATA / "speech").glob("models--*"):  # left over from older versions
                    shutil.rmtree(old, ignore_errors=True)
            return self._whisper[size]

    def _open_mic(self, on_audio, blocksize=0):
        import sounddevice as sd

        device = self._s.get("mic")
        try:
            self._rate = RATE
            stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", callback=on_audio,
                                    blocksize=blocksize, device=device)
        except Exception:
            # Some mics don't do 16 kHz; record at their normal rate and convert.
            info = sd.query_devices(device if device is not None else sd.default.device[0])
            self._rate = int(info["default_samplerate"])
            stream = sd.InputStream(samplerate=self._rate, channels=1, dtype="float32", callback=on_audio,
                                    blocksize=blocksize and int(blocksize * self._rate / RATE), device=device)
        stream.start()
        return stream

    def _to_16k(self, audio):
        if self._rate == RATE:
            return audio
        n = int(len(audio) * RATE / self._rate)
        return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)

    def transcribe(self, audio, trim_silence=False, quick=False, tiny=False):
        """quick (voice calls): greedy, one try (no retries at higher temperatures), and only looks at
        a window as long as the clip instead of the usual 30 s, which is most of the work for short
        sentences. tiny: the smallest model, for live captions while they're still talking."""
        if len(audio) < RATE * 0.3:
            return ""
        started = time.time()
        peak = float(np.max(np.abs(audio)))
        if 0 < peak < 0.3:  # quiet mic: turn it up so speech-to-text hears it clearly
            audio = audio * min(8.0, 0.5 / peak)
        quick = quick or tiny
        window = max(4, min(30, int(len(audio) / RATE) + 2)) if quick else 30
        model = self._get_whisper("tiny" if tiny else quick)

        def run(window, beam=None):
            extra = {"temperature": 0.0} if quick else {}
            segments, _ = model.transcribe(
                # a call's final words get a careful pass (several guesses compared): fast talkers got greedy
                # one-shot guesses wrong; live captions (tiny) stay quick
                audio, language="en", beam_size=beam or (1 if tiny else 5),
                initial_prompt=", ".join(self.names + [HINT_WORDS]),
                condition_on_previous_text=False, without_timestamps=quick, chunk_length=window,
                vad_filter=trim_silence, vad_parameters={"threshold": 0.3, "min_silence_duration_ms": 600}, **extra,
            )
            segments = list(segments)
            sure = min((s.avg_logprob for s in segments), default=0.0)
            return " ".join(s.text.strip() for s in segments).strip(), sure

        try:
            text, sure = run(window)
        except Exception:
            if window == 30:
                raise
            log.exception("Short-window speech-to-text failed, using the full window")
            window = 30
            text, sure = run(window)
        if quick and not tiny and text and sure < UNSURE:
            # Mumbled or said really fast: even the careful pass wasn't sure. A wider search once more.
            again, sure2 = run(window, beam=8)
            log.info("Unsure what I heard (%.2f): %r -> %r (%.2f)", sure, text, again, sure2)
            if again and sure2 >= sure:
                text = again
        secs = time.time() - started
        if not tiny:
            self.last_stt = {"audio": round(len(audio) / RATE, 1), "secs": round(secs, 2), "window": window}
        log.info("Heard %.1fs of audio in %.2fs (%s, window %ss)", len(audio) / RATE, secs,
                 "tiny" if tiny else self.call_ears if quick else "full", window)
        return "" if text.lower().strip(" .!?") in NOISE_WORDS else text

    # Click-to-talk: record until stop_listening() is called.
    def start_listening(self):
        self._frames = []

        def on_audio(data, *_):
            self._frames.append(data[:, 0].copy())
            self.level = min(1.0, float(np.sqrt(np.mean(data ** 2))) * 12)

        self._stream = self._open_mic(on_audio)

    def stop_listening(self):
        if self._stream is None:
            return ""
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self.level = 0.0
        if not self._frames:
            return ""
        return self.transcribe(self._to_16k(np.concatenate(self._frames)), trim_silence=True)

    # Voice chat: wait for the next thing they say, however long that takes.
    def listen_utterance(self):
        """Returns what they said, or None if voice chat was ended."""
        self._cancel.clear()
        chunks = queue.Queue()
        stream = self._open_mic(lambda data, *_: chunks.put(data[:, 0].copy()), blocksize=FRAME)
        detector = UtteranceDetector()
        pending = np.zeros(0, dtype=np.float32)
        try:
            while not self._cancel.is_set():
                try:
                    chunk = chunks.get(timeout=0.1)
                except queue.Empty:
                    continue
                self.level = min(1.0, float(np.sqrt(np.mean(chunk ** 2))) * 12)
                pending = np.concatenate([pending, self._to_16k(chunk)])
                while len(pending) >= FRAME:
                    frame, pending = pending[:FRAME], pending[FRAME:]
                    audio = detector.feed(frame)
                    if audio is None:
                        continue
                    text = self.transcribe(audio)
                    if text:
                        return text
        finally:
            stream.stop()
            stream.close()
            self.level = 0.0
        return None

    def cancel_listening(self):
        self._cancel.set()

    # Voice calls through the chat window's mic (it has echo cancellation, so he doesn't hear himself
    # and you can talk over him). The window sends 16 kHz audio here every ~64 ms.
    #
    # Speed: the final speech-to-text starts ~0.1 s after they go quiet, and he answers as soon as it's
    # ready and sounds finished (after at least END_FAST of quiet) instead of waiting out a fixed silence.

    def call_start(self, on_heard, chance=None, on_partial=None):
        self._call_lock = threading.Lock()
        self._call = UtteranceDetector(chance, end_silence=END_SLOW)
        self._call_pending = np.zeros(0, dtype=np.float32)
        self._on_heard = on_heard
        self._on_partial = on_partial
        self._utt = 0            # which thing they're saying (goes up each time they start talking)
        self._was_talking = False
        self._job = None         # the final speech-to-text run for what they're saying right now
        self._caption_said = 0
        self._last_voice = 0     # when their last bit of speech was actually spoken
        self.turn = {}           # timestamps of the current turn (see Api.voice_timing)

    def call_feed(self, pcm_b64, speaking=False):
        """Returns {"talking": True} as soon as they start talking (so he can stop and listen)."""
        call = getattr(self, "_call", None)
        if call is None:
            return {"talking": False}
        audio = _decode_pcm(pcm_b64)
        if len(audio):
            self.level = min(1.0, float(np.sqrt(np.mean(audio ** 2))) * 12)
        with self._call_lock:
            if self._call is not call:
                return {"talking": False}
            self._call_pending = np.concatenate([self._call_pending, audio])
            arrived = time.time()
            backlog = len(self._call_pending) // FRAME  # frames still to process from this chunk
            while len(self._call_pending) >= FRAME:
                frame, self._call_pending = self._call_pending[:FRAME], self._call_pending[FRAME:]
                utterance = call.feed(frame, strict=speaking)
                backlog -= 1
                if call.talking and call.silent == 0:
                    self._last_voice = arrived - backlog * FRAME / RATE
                if call.talking and not self._was_talking:
                    self._utt += 1
                    self._job = None
                    self._caption_said = 0
                self._was_talking = call.talking
                if utterance is not None:  # END_SLOW of quiet: done for sure
                    self._finish(call, utterance)
            if call.talking:
                job = self._job
                if call.silent >= FINAL_AFTER and not (job and job["said"] == call.said):
                    self._start_final(call)
                elif call.silent == 0 and call.said - self._caption_said >= CAPTION_EVERY:
                    self._caption(call)
                self._maybe_done(call)
            return {"talking": call.talking}

    def _start_final(self, call):
        job = {"utt": self._utt, "said": call.said, "done": threading.Event(), "text": "", "used": False}
        audio = np.concatenate(call.speech)
        self._job = job

        def run():
            with self._ears_lock:
                try:
                    job["text"] = self.transcribe(audio, quick=True)
                except Exception:
                    log.exception("Couldn't understand that")
            job["done"].set()
            with self._call_lock:  # they may have been quiet long enough already
                if self._call is call and call.talking:
                    self._maybe_done(call)

        threading.Thread(target=run, daemon=True).start()

    def _caption(self, call):
        """Live caption while they talk (tiny model; skipped if the ears are busy)."""
        if self._ears_lock.locked() or not self._on_partial:
            return
        self._caption_said = call.said
        audio, utt = np.concatenate(call.speech), self._utt

        def run():
            if not self._ears_lock.acquire(blocking=False):
                return
            try:
                text = self.transcribe(audio, tiny=True)
            except Exception:
                text = ""
            finally:
                self._ears_lock.release()
            c = self._call
            if text and c is not None and c.talking and self._utt == utt and not (self._job and self._job["done"].is_set()):
                self._on_partial(text)

        threading.Thread(target=run, daemon=True).start()

    def _maybe_done(self, call):
        """Called with the call lock held: answer now if they've been quiet for END_FAST, the final
        text is ready, nothing new was said since, and it sounds like a finished sentence."""
        job = self._job
        quiet = call.silent * FRAME / RATE
        if not job or job["used"] or job["said"] != call.said or quiet < END_FAST or not job["done"].is_set():
            return
        if not job["text"]:  # a cough or noise: forget it
            call.reset()
            self._job = None
            return
        if sounds_finished(job["text"]):
            job["used"] = True
            call.reset()
            self._job = None
            self.turn = {"stopped": self._last_voice, "endpoint": time.time(), "stt": time.time()}
            threading.Thread(target=self._on_heard, args=(job["text"],), daemon=True).start()

    def _finish(self, call, utterance):
        """END_SLOW of quiet: whatever they said is done."""
        self.turn = {"stopped": self._last_voice, "endpoint": time.time()}
        job, self._job = self._job, None
        if job and job["utt"] == self._utt and job["said"] == call.last_said:
            if job["used"]:
                return
            job["used"] = True
            threading.Thread(target=self._deliver, args=(job,), daemon=True).start()
        else:
            threading.Thread(target=self._heard, args=(utterance,), daemon=True).start()

    def _deliver(self, job):
        job["done"].wait(20)
        self.turn["stt"] = max(time.time(), self.turn.get("endpoint", 0))
        if job["text"] and getattr(self, "_call", None) is not None:
            self._on_heard(job["text"])

    def _heard(self, audio):
        try:
            with self._ears_lock:
                text = self.transcribe(audio, quick=True)
            self.turn["stt"] = time.time()
            if text and getattr(self, "_call", None) is not None:
                self._on_heard(text)
        except Exception:
            log.exception("Couldn't understand that")

    def call_stop(self):
        self._call = None
        self.level = 0.0

    # ---------- mouth ----------

    def preload_mouth(self):
        try:
            self._get_kokoro().create("yo", voice=DEFAULT_VOICE, speed=1.0, lang="en-us")  # first run is slow; do it now
        except Exception:
            log.exception("Couldn't load my voice")

    def _get_kokoro(self):
        with self._mouth_lock:
            if self._kokoro is None:
                import onnxruntime as ort
                from kokoro_onnx import Kokoro

                from engine import download
                from paths import DATA

                folder = DATA / "voice"
                folder.mkdir(exist_ok=True)
                for name in (VOICE_MODEL, VOICE_STYLES):
                    if not (folder / name).exists():
                        download(f"{VOICE_URL}/{name}", folder / name, lambda d, t: None)
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = _threads()  # real cores only: hyperthreads make it slower
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                session = ort.InferenceSession(str(folder / VOICE_MODEL), opts, providers=["CPUExecutionProvider"])
                self._kokoro = Kokoro.from_session(session, str(folder / VOICE_STYLES))
                self._kokoro.sess = _Abortable(session)
                for old in folder.glob("kokoro-*.onnx"):  # the slower voice older versions used
                    if old.name != VOICE_MODEL:
                        old.unlink(missing_ok=True)
            return self._kokoro

    def cancel_speech(self, gen=None):
        """He got cut off: voice parts asked for before gen (the window's reset time) get skipped, and
        the one being made right now is stopped mid-way (so it doesn't slow down his next answer)."""
        self._say_gen = max(getattr(self, "_say_gen", 0), gen or 0)
        running = getattr(self, "_making", None)
        if running and running[0] is not None and running[0] < self._say_gen and self._kokoro is not None:
            self._kokoro.sess.abort()
        return self._say_gen

    def say(self, text, gen=None, long=False):
        """One part of a reply as audio: {"audio": base64, "mime", "rate", "sr"}, or None (the app then
        uses the Windows voice). Kokoro's audio comes back as raw 16-bit samples ("audio/pcm") so the
        window can play it straight away. "rate" is how fast to play it; playing faster also raises the
        pitch, which is how the cute style works. gen: skip it if he was cut off since it was asked for.
        long: part of a long explanation, so a touch slower."""
        if gen is not None and gen < getattr(self, "_say_gen", 0):
            return None
        text = speakable(text)
        if not text:
            return None
        pitch = PITCH.get(self._s.get("voice_style"), PITCH["cute"])
        speed = float(self._s.get("talk_speed") or DEFAULT_SPEED) * (0.92 if long else 1.0)
        voice = self._s.get("voice") or DEFAULT_VOICE
        try:
            kokoro = self._get_kokoro()
            if voice not in kokoro.get_voices():
                voice = DEFAULT_VOICE
            with self._say_lock:  # one at a time: two at once each take twice as long
                if gen is not None and gen < getattr(self, "_say_gen", 0):
                    return None
                self._making = (gen,)
                try:
                    samples, rate = kokoro.create(text, voice=voice, speed=speed / pitch, lang="en-us")
                finally:
                    self._making = None
            pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
            return {"audio": base64.b64encode(pcm).decode(), "mime": "audio/pcm", "sr": rate, "rate": pitch}
        except Exception:
            if gen is not None and gen < getattr(self, "_say_gen", 0):
                return None  # stopped on purpose (he got cut off)
            log.exception("My own voice failed, trying the online one")
        try:
            return {"audio": base64.b64encode(asyncio.run(self._tts(text, speed))).decode(),
                    "mime": "audio/mpeg", "rate": 1.0}
        except Exception:
            log.exception("Online voice failed too, falling back to Windows voice")
            return None

    async def _tts(self, text, speed):
        import edge_tts

        tts = edge_tts.Communicate(text, "en-US-BrianNeural", rate=f"{round((speed - 1) * 100):+d}%", pitch="+30Hz")
        audio = bytearray()
        async for chunk in tts.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        if not audio:
            raise RuntimeError("no audio")
        return bytes(audio)


class _Abortable:
    """Kokoro's model session, but a run can be stopped half way (when he gets cut off)."""

    def __init__(self, session):
        self._session = session
        self._options = None

    def run(self, outputs, inputs, run_options=None):
        import onnxruntime as ort

        self._options = ort.RunOptions()
        try:
            return self._session.run(outputs, inputs, self._options)
        finally:
            self._options = None

    def abort(self):
        if self._options is not None:
            self._options.terminate = True

    def __getattr__(self, name):
        return getattr(self._session, name)


def _threads():
    """Threads for speech-to-text and the voice: the real cores. More than that (hyperthreads, or
    both running at once with all threads each) makes them several times slower, not faster."""
    import os

    n = os.cpu_count() or 4
    return max(2, min(8, n // 2 if n >= 8 else n))  # big CPUs have 2 threads per core; small ones often don't


def _decode_pcm(pcm_b64):
    """16-bit 16 kHz audio (base64) from the chat window → float samples."""
    raw = base64.b64decode(pcm_b64) if pcm_b64 else b""
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
