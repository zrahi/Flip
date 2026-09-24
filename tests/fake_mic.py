"""Makes the recording the build plays into Flip's mic during the app test (Windows only):
Windows' built-in voice asks a question, then it's quiet for a long time (the recording loops).

    python tests/fake_mic.py out.wav
"""
import subprocess
import sys
import wave

import numpy as np

QUESTION = "hey Flip, what agent should I play on Ascent, and why?"


def main(out):
    speech = out + ".speech.wav"
    ps = (f"Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{speech}'); $s.Speak('{QUESTION}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    with wave.open(speech) as w:
        rate, channels = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, channels)[:, 0]
    rng = np.random.default_rng(0)
    hiss = lambda sec: rng.normal(0, 60, int(rate * sec)).astype("<i2")  # a real mic is never totally silent
    audio = np.concatenate([hiss(3), data, hiss(600)])
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(audio.tobytes())
    print(f"fake mic: {len(data) / rate:.1f}s of speech at {rate} Hz -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
