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

for size in ("small.en", "base.en", "tiny.en", "distil-small.en"):
    try:
        folder = download_model(size)
    except Exception as e:
        print(f"::notice title={size}::download failed {e}")
        continue
    for threads in (4, os.cpu_count() or 4):
        t = time.time()
        m = WhisperModel(folder, device="cpu", compute_type="int8", cpu_threads=threads)
        load = time.time() - t
        for prompt in (True, False):
            for window in (30, 5):
                kw = dict(language="en", beam_size=1, without_timestamps=True, condition_on_previous_text=False,
                          chunk_length=window, initial_prompt=voice.HINT_WORDS if prompt else None)
                list(m.transcribe(audio, **kw)[0])  # warm
                best, text = 99, ""
                for _ in range(3):
                    t = time.time()
                    text = " ".join(s.text for s in m.transcribe(audio, **kw)[0])
                    best = min(best, time.time() - t)
                print(f"::notice title={size} t{threads} prompt={prompt} win{window}::{best:.2f}s (load {load:.1f}s) {text.strip()}")
