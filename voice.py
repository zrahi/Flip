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
# How much higher each style sounds (and a tiny bit quicker; the talking speed makes up for it).
PITCH = {"cute": 1.12, "normal": 1.0, "deep": 0.92}

CODE_BLOCK = re.compile(r"```.*?(```|$)", re.S)
URL = re.compile(r"https?://\S+")
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")
# Things speech-to-text "hears" in silence or background noise.
NOISE_WORDS = {"", "you", "thank you", "thank you.", "thanks for watching!", "bye.", ".", "uh", "um", "hmm"}


def speakable(text):
    """Turn a chat reply into something that sounds good out loud."""
    text = CODE_BLOCK.sub(" I dropped the code in the chat. ", text)
    text = URL.sub(" the link ", text)
    text = EMOJI.sub("", text)
    text = re.sub(r"[`*_#>|]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 700:
        cut = text[:700]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = cut[: end + 1] if end > 200 else cut
    return text


FRAME = 512  # 32 ms at 16 kHz: the size the speech detector works on

# Words he should expect to hear, so speech-to-text spells them right.
HINT_WORDS = ("Flip, Valorant, Jett, Reyna, Raze, Phoenix, Neon, Iso, Yoru, Sova, Skye, Fade, Gekko, KAY/O, Breach, "
              "Omen, Viper, Astra, Harbor, Clove, Brimstone, Killjoy, Cypher, Sage, Chamber, Deadlock, Vyse, Tejo, "
              "Waylay, Vandal, Phantom, Operator, Sheriff, Ascent, Haven, Bind, Split, Lotus, Sunset, Icebox, Breeze, "
              "Pearl, Fracture, Abyss, Radiant, Immortal, clutch, eco, one tap, gg.")


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

    def feed(self, frame, strict=False):
        """Feed 512 samples at 16 kHz. Returns the finished utterance once they stop talking, else None.
        strict: he's talking right now, so it takes clearer, longer speech to count (leftover echo doesn't)."""
        p = self.chance(frame)
        if not self.talking:
            self.pre.append(frame)
            self.voiced = self.voiced + 1 if p > (0.7 if strict else 0.5) else 0
            if self.voiced >= (8 if strict else 3):  # about 0.25 s (or 0.1 s) of real speech
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
        self._whisper = None
        self._whisper_lock = threading.Lock()
        self._ears_lock = threading.Lock()  # one speech-to-text run at a time
        self._stream = None
        self._frames = []
        self._rate = RATE
        self._cancel = threading.Event()
        self._kokoro = None
        self._mouth_lock = threading.Lock()
        self.level = 0.0
        self.names = []

    # ---------- ears ----------

    def preload(self):
        try:
            self._get_whisper()
        except Exception:
            log.exception("Couldn't load speech-to-text")
        self.preload_mouth()

    def _get_whisper(self):
        with self._whisper_lock:
            if self._whisper is None:
                import shutil

                from faster_whisper import WhisperModel
                from faster_whisper.utils import download_model

                from paths import DATA
                size = self._s.get("whisper_model") or "small.en"
                folder = DATA / "speech" / size
                if not (folder / "model.bin").exists():
                    # a plain folder: the default download kept a second copy of the model on Windows
                    download_model(size, output_dir=str(folder))
                self._whisper = WhisperModel(str(folder), device="cpu", compute_type="int8", cpu_threads=_threads())
                for old in (DATA / "speech").glob("models--*"):  # left over from older versions
                    shutil.rmtree(old, ignore_errors=True)
            return self._whisper

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

    def transcribe(self, audio, trim_silence=False, quick=False):
        """quick (voice calls): greedy, and only looks at a window as long as the clip instead of the
        usual 30 s, which is most of the work for short sentences."""
        if len(audio) < RATE * 0.3:
            return ""
        started = time.time()
        peak = float(np.max(np.abs(audio)))
        if 0 < peak < 0.3:  # quiet mic: turn it up so speech-to-text hears it clearly
            audio = audio * min(8.0, 0.5 / peak)
        window = max(4, min(30, int(len(audio) / RATE) + 2)) if quick else 30

        def run(window):
            segments, _ = self._get_whisper().transcribe(
                audio, language="en", beam_size=1 if quick else 5, initial_prompt=", ".join(self.names + [HINT_WORDS]),
                condition_on_previous_text=False, without_timestamps=quick, chunk_length=window,
                vad_filter=trim_silence, vad_parameters={"threshold": 0.3, "min_silence_duration_ms": 600},
            )
            return " ".join(s.text.strip() for s in segments).strip()

        try:
            text = run(window)
        except Exception:
            if window == 30:
                raise
            log.exception("Short-window speech-to-text failed, using the full window")
            window = 30
            text = run(window)
        self.last_stt = {"audio": round(len(audio) / RATE, 1), "secs": round(time.time() - started, 2), "window": window}
        log.info("Heard %.1fs of audio in %.2fs (window %ss)", len(audio) / RATE, time.time() - started, window)
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
    # and you can talk over him). The window sends 16 kHz audio here every 100 ms.

    def call_start(self, on_heard, chance=None, on_partial=None):
        self._call = UtteranceDetector(chance, end_silence=0.45)
        self._call_pending = np.zeros(0, dtype=np.float32)
        self._on_heard = on_heard
        self._on_partial = on_partial
        self._utt = 0            # which thing they're saying (goes up each time they start talking)
        self._was_talking = False
        self._job = None         # the newest speech-to-text run for what they're saying right now

    def call_feed(self, pcm_b64, speaking=False):
        """Returns {"talking": True} as soon as they start talking (so he can stop and listen).
        While they talk, what they've said so far gets written out in the background, so by the
        time they stop it's (nearly) done."""
        call = getattr(self, "_call", None)
        if call is None:
            return {"talking": False}
        audio = _decode_pcm(pcm_b64)
        if len(audio):
            self.level = min(1.0, float(np.sqrt(np.mean(audio ** 2))) * 12)
        self._call_pending = np.concatenate([self._call_pending, audio])
        while len(self._call_pending) >= FRAME:
            frame, self._call_pending = self._call_pending[:FRAME], self._call_pending[FRAME:]
            utterance = call.feed(frame, strict=speaking)
            if call.talking and not self._was_talking:
                self._utt += 1
                self._job = None
            self._was_talking = call.talking
            if utterance is not None:
                job, self._job = self._job, None
                if job and job["utt"] == self._utt and job["said"] == call.last_said:
                    # nothing new since that run started: its text is the answer
                    threading.Thread(target=self._deliver, args=(job,), daemon=True).start()
                else:
                    threading.Thread(target=self._heard, args=(utterance,), daemon=True).start()
        if call.talking:
            job = self._job
            if call.silent >= 5 and not (job and job["said"] == call.said):
                self._run_job(call, wait=True)  # they just paused: get it ready for when they're done
            elif call.silent == 0 and call.said - (job["said"] if job else 0) >= 25:
                self._run_job(call, wait=False)  # still talking: update the live caption
        return {"talking": call.talking}

    def _run_job(self, call, wait):
        if not wait and self._ears_lock.locked():
            return
        job = {"utt": self._utt, "said": call.said, "done": threading.Event(), "text": ""}
        audio = np.concatenate(call.speech)
        self._job = job

        def run():
            with self._ears_lock:
                try:
                    job["text"] = self.transcribe(audio, quick=True)
                except Exception:
                    log.exception("Couldn't understand that")
            job["done"].set()
            c = self._call
            if job["text"] and c is not None and c.talking and self._utt == job["utt"] and self._on_partial:
                self._on_partial(job["text"])

        threading.Thread(target=run, daemon=True).start()

    def _deliver(self, job):
        job["done"].wait(20)
        if job["text"] and getattr(self, "_call", None) is not None:
            self._on_heard(job["text"])

    def _heard(self, audio):
        try:
            with self._ears_lock:
                text = self.transcribe(audio, quick=True)
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
            self._get_kokoro()
        except Exception:
            log.exception("Couldn't load my voice")

    def _get_kokoro(self):
        with self._mouth_lock:
            if self._kokoro is None:
                from kokoro_onnx import Kokoro

                from engine import download
                from paths import DATA

                folder = DATA / "voice"
                folder.mkdir(exist_ok=True)
                for name in (VOICE_MODEL, VOICE_STYLES):
                    if not (folder / name).exists():
                        download(f"{VOICE_URL}/{name}", folder / name, lambda d, t: None)
                self._kokoro = Kokoro(str(folder / VOICE_MODEL), str(folder / VOICE_STYLES))
                for old in folder.glob("kokoro-*.onnx"):  # the slower voice older versions used
                    if old.name != VOICE_MODEL:
                        old.unlink(missing_ok=True)
            return self._kokoro

    def say(self, text):
        """One part of a reply as audio: {"audio": base64, "mime", "rate"}, or None (the app then
        uses the Windows voice). "rate" is how fast to play it; playing faster also raises the pitch,
        which is how the cute style works."""
        text = speakable(text)
        if not text:
            return None
        pitch = PITCH.get(self._s.get("voice_style"), PITCH["cute"])
        speed = float(self._s.get("talk_speed") or 1.0)
        voice = self._s.get("voice") or DEFAULT_VOICE
        try:
            kokoro = self._get_kokoro()
            if voice not in kokoro.get_voices():
                voice = DEFAULT_VOICE
            samples, rate = kokoro.create(text, voice=voice, speed=speed / pitch, lang="en-us")
            return {"audio": _wav_base64(samples, rate), "mime": "audio/wav", "rate": pitch}
        except Exception:
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


def _threads():
    """Speech-to-text threads: the real cores (it defaults to 4)."""
    import os

    return max(4, min(8, (os.cpu_count() or 8) // 2))


def _decode_pcm(pcm_b64):
    """16-bit 16 kHz audio (base64) from the chat window → float samples."""
    raw = base64.b64decode(pcm_b64) if pcm_b64 else b""
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def _wav_base64(samples, rate):
    import io
    import wave

    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return base64.b64encode(buf.getvalue()).decode()
