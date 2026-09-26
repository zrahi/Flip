import json

import numpy as np
import pytest

import draw

ov = pytest.importorskip("openvino")


def _fake_kit(folder):
    """Tiny stand-ins with the real models' inputs and outputs, so the drawing loop runs without 2 GB."""
    import openvino.opset13 as op

    ids = op.parameter([1, 77], np.int64, name="input_ids")
    hidden = op.broadcast(op.constant(np.float32(0.1)), op.constant(np.array([1, 77, 768], dtype=np.int64)))
    used = op.multiply(op.convert(op.reduce_sum(ids, op.constant([1]), True), np.float32), op.constant(np.float32(0)))
    enc = ov.Model([op.add(hidden, op.unsqueeze(used, op.constant([2])))], [ids], "text_encoder")
    sample = op.parameter([1, 4, 64, 64], np.float32, name="sample")
    t = op.parameter([1], np.float32, name="timestep")
    hs = op.parameter([1, 77, 768], np.float32, name="encoder_hidden_states")
    w = op.parameter([1, 256], np.float32, name="timestep_cond")
    out = op.multiply(sample, op.constant(np.float32(0.1)))
    unet = ov.Model([out], [sample, t, hs, w], "unet")
    lat = op.parameter([1, 4, 64, 64], np.float32, name="latent_sample")
    first3 = op.slice(lat, op.constant([0]), op.constant([3]), op.constant([1]), op.constant([1]))
    big = op.interpolate(first3, op.constant(np.array([512, 512], dtype=np.int64)), "nearest", "sizes",
                         axes=op.constant(np.array([2, 3], dtype=np.int64)))
    vae = ov.Model([op.tanh(big)], [lat], "vae_decoder")
    for name, model in (("text_encoder", enc), ("unet", unet), ("vae_decoder", vae)):
        ov.save_model(model, str(folder / f"{name}.xml"))
    vocab = {"<|startoftext|>": 0, "<|endoftext|>": 1, "a</w>": 2, "c": 3, "at</w>": 4, "cat</w>": 5}
    (folder / "vocab.json").write_text(json.dumps(vocab))
    (folder / "merges.txt").write_text("#version: 0.2\na t</w>\nc at</w>\n")


def test_draws_on_this_pc_and_leaves_nothing(monkeypatch):
    seen = []
    monkeypatch.setattr(draw, "_download", lambda folder, on_status, stop: _fake_kit(folder))
    png = draw.draw("a cat", on_status=seen.append, seed=1)
    assert png.startswith(b"\x89PNG") and len(png) > 1000
    assert any("drawing… 4/4" in s for s in seen)
    assert not draw.HOME.exists()  # the kit is deleted as soon as it's drawn


def test_lcm_schedule_matches_the_reference(tmp_path):
    assert list(draw.lcm_timesteps()) == [999, 759, 519, 279]
    assert draw.guidance_embedding(8.0).shape == (1, 256)
    from cliptok import ClipTokenizer

    _fake_kit(tmp_path)
    ids = ClipTokenizer(tmp_path / "vocab.json", tmp_path / "merges.txt").encode("A  Cat", length=6)
    assert ids == [0, 2, 5, 1, 1, 1]  # start, "a", "cat" (merged from c + at), end, padding
