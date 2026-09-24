"""Flip's ears (mic + speech-to-text) and mouth (text-to-speech)."""

import asyncio
import base64
import logging
import queue
import re
import threading
from collections import deque

import numpy as np

log = logging.getLogger("flip")

RATE = 16000
CHUNK_SEC = 0.03

# His voice runs on the PC (Kokoro): downloaded once (~120 MB), no internet needed after that.
VOICE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
VOICE_MODEL = "kokoro-v1.0.int8.onnx"
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

    def __init__(self, chance=None, end_silence=0.8, max_len=30.0):
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

    def feed(self, frame):
        """Feed 512 samples at 16 kHz. Returns the finished utterance once they stop talking, else None."""
        p = self.chance(frame)
        if not self.talking:
            self.pre.append(frame)
            self.voiced = self.voiced + 1 if p > 0.5 else 0
            if self.voiced >= 3:  # about 0.1 s of real speech
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
        self._stream = None
        self._frames = []
        self._rate = RATE
        self._cancel = threading.Event()
        self._kokoro = None
        self._mouth_lock = threading.Lock()
        self.level = 0.0

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
                from faster_whisper import WhisperModel

                from paths import DATA
                self._whisper = WhisperModel(self._s.get("whisper_model") or "small.en", device="cpu",
                                             compute_type="int8", download_root=str(DATA / "speech"))
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

    def transcribe(self, audio, trim_silence=False):
        if len(audio) < RATE * 0.3:
            return ""
        peak = float(np.max(np.abs(audio)))
        if 0 < peak < 0.3:  # quiet mic: turn it up so speech-to-text hears it clearly
            audio = audio * min(8.0, 0.5 / peak)
        segments, _ = self._get_whisper().transcribe(
            audio, language="en", beam_size=5, initial_prompt=HINT_WORDS, condition_on_previous_text=False,
            vad_filter=trim_silence, vad_parameters={"threshold": 0.3, "min_silence_duration_ms": 600},
        )
        text = " ".join(s.text.strip() for s in segments).strip()
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
            return self._kokoro

    def speech_parts(self, text):
        """The reply split into sentences, so he can start talking before the whole thing is ready."""
        text = speakable(text)
        parts, current = [], ""
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            current = f"{current} {sentence}".strip()
            if len(current) >= 40:  # tiny sentences ride along with the next one
                parts.append(current)
                current = ""
        if current:
            parts.append(current)
        return parts

    def say(self, text):
        """One part of a reply as audio: {"audio": base64, "mime", "rate"}, or None (the app then
        uses the Windows voice). "rate" is how fast to play it; playing faster also raises the pitch,
        which is how the cute style works."""
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
