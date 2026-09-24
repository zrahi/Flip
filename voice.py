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

# (pitch, speed) for each voice style
STYLES = {"cute": ("+38Hz", "+8%"), "normal": ("+2Hz", "+10%"), "deep": ("-10Hz", "+4%")}

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


class UtteranceDetector:
    """Figures out when someone starts talking and when they've finished, from mic loudness."""

    def __init__(self, chunk_sec=CHUNK_SEC, end_silence=0.9, max_len=30.0):
        self.chunk_sec = chunk_sec
        self.end_chunks = int(end_silence / chunk_sec)
        self.max_chunks = int(max_len / chunk_sec)
        self.noise = None
        self.voiced = 0
        self.silent = 0
        self.talking = False
        self.pre = deque(maxlen=int(0.3 / chunk_sec))
        self.speech = []

    def feed(self, chunk):
        """Returns the finished utterance (audio) once they stop talking, else None."""
        rms = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
        if self.noise is None:
            self.noise = rms
        threshold = max(self.noise * 3.0, 0.01)
        if not self.talking:
            self.noise = 0.95 * self.noise + 0.05 * rms  # learn the room's background noise
            self.pre.append(chunk)
            self.voiced = self.voiced + 1 if rms > threshold else max(0, self.voiced - 1)
            if self.voiced >= 4:
                self.talking = True
                self.speech = list(self.pre)
                self.silent = 0
            return None
        self.speech.append(chunk)
        self.silent = self.silent + 1 if rms < threshold * 0.7 else 0
        if self.silent >= self.end_chunks or len(self.speech) >= self.max_chunks:
            audio = np.concatenate(self.speech)
            self.talking = False
            self.voiced = 0
            self.speech = []
            self.pre.clear()
            return audio
        return None


class Voice:
    def __init__(self, settings):
        self._s = settings
        self._whisper = None
        self._whisper_lock = threading.Lock()
        self._stream = None
        self._frames = []
        self._rate = RATE
        self._cancel = threading.Event()
        self.level = 0.0

    # ---------- ears ----------

    def preload(self):
        try:
            self._get_whisper()
        except Exception:
            log.exception("Couldn't load speech-to-text")

    def _get_whisper(self):
        with self._whisper_lock:
            if self._whisper is None:
                from faster_whisper import WhisperModel
                self._whisper = WhisperModel(self._s.get("whisper_model", "base.en"), device="cpu", compute_type="int8")
            return self._whisper

    def _open_mic(self, on_audio, blocksize=0):
        import sounddevice as sd

        try:
            self._rate = RATE
            stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", callback=on_audio,
                                    blocksize=blocksize and int(RATE * blocksize))
        except Exception:
            # Some mics don't do 16 kHz; record at their normal rate and convert later.
            self._rate = int(sd.query_devices(kind="input")["default_samplerate"])
            stream = sd.InputStream(samplerate=self._rate, channels=1, dtype="float32", callback=on_audio,
                                    blocksize=blocksize and int(self._rate * blocksize))
        stream.start()
        return stream

    def _to_16k(self, audio):
        if self._rate == RATE:
            return audio
        n = int(len(audio) * RATE / self._rate)
        return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)

    def transcribe(self, audio):
        if len(audio) < RATE * 0.4:
            return ""
        segments, _ = self._get_whisper().transcribe(audio, language="en", beam_size=1, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return "" if text.lower() in NOISE_WORDS else text

    # Click-to-talk: record until stop_listening() is called.
    def start_listening(self):
        self._frames = []
        self._stream = self._open_mic(lambda data, *_: self._frames.append(data[:, 0].copy()))

    def stop_listening(self):
        if self._stream is None:
            return ""
        self._stream.stop()
        self._stream.close()
        self._stream = None
        if not self._frames:
            return ""
        return self.transcribe(self._to_16k(np.concatenate(self._frames)))

    # Voice chat: wait for the next thing they say, however long that takes.
    def listen_utterance(self):
        """Returns what they said, or None if voice chat was ended."""
        self._cancel.clear()
        chunks = queue.Queue()
        stream = self._open_mic(lambda data, *_: chunks.put(data[:, 0].copy()), blocksize=CHUNK_SEC)
        detector = UtteranceDetector()
        try:
            while not self._cancel.is_set():
                try:
                    chunk = chunks.get(timeout=0.1)
                except queue.Empty:
                    continue
                self.level = min(1.0, float(np.sqrt(np.mean(chunk ** 2))) * 12)
                audio = detector.feed(chunk)
                if audio is None:
                    continue
                text = self.transcribe(self._to_16k(audio))
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

    def speak(self, text):
        """Returns the reply as base64 MP3, or None so the app uses the Windows voice instead."""
        text = speakable(text)
        if not text:
            return None
        try:
            return base64.b64encode(asyncio.run(self._tts(text))).decode()
        except Exception:
            log.exception("Online voice failed, falling back to Windows voice")
            return None

    async def _tts(self, text):
        import edge_tts

        pitch, rate = STYLES.get(self._s.get("voice_style"), STYLES["cute"])
        tts = edge_tts.Communicate(
            text,
            self._s.get("voice", "en-US-BrianNeural"),
            rate=self._s.get("voice_rate") or rate,
            pitch=self._s.get("voice_pitch") or pitch,
        )
        audio = bytearray()
        async for chunk in tts.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        if not audio:
            raise RuntimeError("no audio")
        return bytes(audio)
