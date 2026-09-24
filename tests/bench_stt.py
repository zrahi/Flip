"""Times speech-to-text settings on real speech (run by the bench workflow on Windows)."""
import os
import subprocess
import sys
import tempfile
import time
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import voice  # noqa: E402

path = os.path.join(tempfile.gettempdir(), "bench.wav")
ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
      f"$s.SetOutputToWaveFile('{path}'); $s.Speak('hey Flip, what agent should I play on Ascent'); $s.Dispose()")
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
with wave.open(path) as w:
    rate, data = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
a = data.astype(np.float32) / 32768
audio = np.interp(np.linspace(0, len(a) - 1, int(len(a) * 16000 / rate)), np.arange(len(a)), a).astype(np.float32)
print(f"::notice title=cpu::{os.cpu_count()} logical cpus, audio {len(audio) / 16000:.1f}s")

from faster_whisper import WhisperModel  # noqa: E402
from faster_whisper.utils import download_model  # noqa: E402

rows = []
kokoro = None
try:
    v = voice.Voice({})
    kokoro = v._get_kokoro()
except Exception as e:
    rows.append(f"kokoro failed {e}")
import threading  # noqa: E402

for size in ("small.en", "base.en"):
    folder = download_model(size)
    m = WhisperModel(folder, device="cpu", compute_type="int8", cpu_threads=4)
    kw = dict(language="en", beam_size=1, without_timestamps=True, condition_on_previous_text=False,
              chunk_length=6, initial_prompt=voice.HINT_WORDS)
    list(m.transcribe(audio, **kw)[0])

    def timed():
        t = time.time()
        text = " ".join(s.text for s in m.transcribe(audio, **kw)[0]).strip()
        return time.time() - t, text

    rows.append(f"{size} alone {timed()[0]:.2f}s {timed()[1]}")
    # while his voice is being made
    if kokoro:
        stop = threading.Event()
        th = threading.Thread(target=lambda: [kokoro.create("yo what's good, this is a long sentence to keep the voice busy for a while", voice="am_fenrir", speed=1.0, lang="en-us") for _ in range(3) if not stop.is_set()])
        th.start(); time.sleep(0.3)
        rows.append(f"{size} during-voice {timed()[0]:.2f}s")
        stop.set(); th.join()
        rows.append(f"{size} right-after-voice {timed()[0]:.2f}s")
    # while the speech detector runs every 32 ms like in a call
    ears = voice.Ears()
    stop = threading.Event()

    def vad_loop():
        f = np.zeros(512, dtype=np.float32)
        while not stop.is_set():
            ears.speech_chance(f); time.sleep(0.03)
    th = threading.Thread(target=vad_loop); th.start()
    rows.append(f"{size} during-detector {timed()[0]:.2f}s")
    stop.set(); th.join()
print("::notice title=bench::" + " || ".join(rows))
