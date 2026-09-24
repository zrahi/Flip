"""On Windows: make real speech with Windows' built-in voice, then check Flip's ears catch it and understand it."""
import subprocess
import sys
import wave

import numpy as np
import pytest

import voice

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def _say(text, path):
    ps = (f"Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{text}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    with wave.open(str(path)) as w:
        rate, data = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    audio = data.astype(np.float32) / 32768
    return np.interp(np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / rate)), np.arange(len(audio)), audio).astype(np.float32)


def test_ears_catch_and_understand_speech(tmp_path):
    speech = _say("hey flip, how do I play Jett on Ascent", tmp_path / "s.wav")
    rng = np.random.default_rng(0)
    v = voice.Voice({"whisper_model": "small.en"})
    for gain in (1.0, 0.1):  # normal and a very quiet mic
        noise = lambda sec: rng.normal(0, 0.003, int(16000 * sec)).astype(np.float32)
        audio = np.concatenate([noise(1.5), speech * gain + noise(len(speech) / 16000), noise(1.5)])
        det = voice.UtteranceDetector()
        caught = [u for i in range(0, len(audio) - 511, 512) if (u := det.feed(audio[i:i + 512])) is not None]
        assert len(caught) == 1, (gain, len(caught))
        text = v.transcribe(caught[0]).lower()
        print(gain, "heard:", text)
        words = ["hey", "flip", "how", "do", "play", "jett", "on", "ascent"]
        heard = [w for w in words if w in text]
        assert "jett" in text and len(heard) >= 6, (text, heard)
