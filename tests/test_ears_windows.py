"""On Windows: make real speech with Windows' built-in voice, then check Flip's ears catch it and understand it."""
import subprocess
import sys
import wave

import numpy as np
import pytest

import voice

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def _say(text, path, rate=0):
    """rate: -10 (slow) to 10 (fast); 6+ is a fast talker."""
    ps = (f"Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.Rate = {rate}; $s.SetOutputToWaveFile('{path}'); $s.Speak('{text}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    with wave.open(str(path)) as w:
        rate, data = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    audio = data.astype(np.float32) / 32768
    return np.interp(np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / rate)), np.arange(len(audio)), audio).astype(np.float32)


def test_ears_catch_and_understand_speech(tmp_path):
    speech = _say("hey flip, how do I play Jett on Ascent", tmp_path / "s.wav")
    rng = np.random.default_rng(0)
    v = voice.Voice({})  # the default ears
    for gain in (1.0, 0.1):  # normal and a very quiet mic
        noise = lambda sec: rng.normal(0, 0.003, int(16000 * sec)).astype(np.float32)
        audio = np.concatenate([noise(1.5), speech * gain + noise(len(speech) / 16000), noise(1.5)])
        det = voice.UtteranceDetector()
        caught = [u for i in range(0, len(audio) - 511, 512) if (u := det.feed(audio[i:i + 512])) is not None]
        assert len(caught) == 1, (gain, len(caught))
        for quick in (False, True):  # quick: how voice calls do it (short window, greedy)
            text = v.transcribe(caught[0], quick=quick).lower()
            print(gain, quick, "heard:", text, v.last_stt)
            words = ["hey", "flip", "how", "do", "play", "jett", "on", "ascent"]
            heard = [w for w in words if w in text]
            assert "jett" in text and len(heard) >= 6, (quick, text, heard)
            if quick:
                assert v.last_stt["window"] < 30, v.last_stt  # the short window really worked


def test_ears_keep_up_with_fast_talkers(tmp_path):
    v = voice.Voice({})
    words = ["what", "should", "buy", "lotus", "credits", "phantom", "vandal"]
    # rate 6: ~320 words a minute, faster than a fast talker: every word. rate 9: ~450 a minute, faster than
    # anyone talks: the words that matter.
    for rate, need in ((6, 7), (9, 4)):
        speech = _say("yo what should I buy on Lotus with thirty four hundred credits, phantom or vandal",
                      tmp_path / f"fast{rate}.wav", rate)
        text = v.transcribe(speech, quick=True).lower()
        heard = [w for w in words if w in text]
        print(rate, "heard:", text, v.last_stt)
        assert len(heard) >= need and "phantom" in heard and "vandal" in heard, (rate, text, heard)


def test_ears_get_casual_fast_talk(tmp_path):
    v = voice.Voice({})
    # (a real call: "yo jett is on me im playing lotus rn" was heard as "Yo, Jett, it's Yoru right now, what's your redo?")
    for rate in (4, 7):
        speech = _say("yo jett is on me, im playing lotus right now", tmp_path / f"casual{rate}.wav", rate)
        text = v.transcribe(speech, quick=True).lower()
        print(rate, "heard:", text, v.last_stt)
        assert "jett" in text and "lotus" in text and "yoru" not in text and "on me" in text, (rate, text)
