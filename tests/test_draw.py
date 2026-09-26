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
    t.output(0).get_tensor().set_names({"731", "timestep", "timesteps", "730"})  # like the real one (build 63)
    hs = op.parameter([1, 77, 768], np.float32, name="encoder_hidden_states")
    w = op.parameter([1, 256], np.float32, name="timestep_cond")
    out = op.multiply(sample, op.constant(np.float32(0.1)))
    unet = ov.Model([out], [sample, t, hs, w], "unet")
    lat = op.parameter([1, 4, 64, 64], np.float32, name="latent_sample")
    first3 = op.slice(lat, op.constant([0]), op.constant([3]), op.constant([1]), op.constant([1]))
    big = op.interpolate(first3, op.constant(np.array([512, 512], dtype=np.int64)), "nearest", "sizes",
                         axes=op.constant(np.array([2, 3], dtype=np.int64)))
    vae = ov.Model([op.tanh(op.multiply(big, op.constant(np.float32(0.001))))], [lat], "vae_decoder")  # smooth
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


def test_every_unet_input_is_fed_even_with_several_names(tmp_path):
    # build 62 drew static: the timestep input is called "731" as well as "timestep", only the first name was
    # looked at, so the timestep was never given to the model
    _fake_kit(tmp_path)
    ports = draw._unet_ports(ov.Core().compile_model(str(tmp_path / "unet.xml"), "CPU"))
    assert {k: "timestep" in p.get_names() for k, p in ports.items()} == {
        "sample": False, "timestep": True, "encoder_hidden_states": False, "timestep_cond": False}
    assert "sample" in ports["sample"].get_names() and "timestep_cond" in ports["timestep_cond"].get_names()


def test_static_is_not_a_picture():
    rng = np.random.default_rng(0)
    assert draw.roughness(rng.integers(0, 256, (512, 512, 3), dtype=np.uint8)) > draw.NOISE
    smooth = np.tile(np.linspace(0, 255, 512, dtype=np.uint8)[None, :, None], (512, 1, 3))
    assert draw.roughness(smooth) < draw.NOISE
