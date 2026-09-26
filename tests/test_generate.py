import urllib.parse
from pathlib import Path
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import attachments
import generate
import router


def param(name, component, python_type="str", has_default=True, label=None):
    return {"label": label or name.replace("_", " ").title(), "parameter_name": name, "parameter_has_default": has_default,
            "parameter_default": None, "python_type": {"type": python_type}, "component": component}


# Shaped like the real demos: Wan 2.2 picture-to-video, Wan 2.2 text-to-video, FLUX.1-schnell.
WAN_I2V = {"named_endpoints": {"/generate_video": {
    "parameters": [param("input_image", "Image", "filepath", False), param("prompt", "Textbox"),
                   param("steps", "Slider", "float"), param("negative_prompt", "Textbox"),
                   param("duration_seconds", "Slider", "float"), param("seed", "Slider", "float"),
                   param("randomize_seed", "Checkbox", "bool")],
    "returns": [{"label": "Generated Video", "component": "Video"}, {"label": "Seed", "component": "Slider"}]}}}
WAN_T2V = {"named_endpoints": {
    "/enhance_prompt": {"parameters": [param("prompt", "Textbox", has_default=False)],
                        "returns": [{"label": "Prompt", "component": "Textbox"}]},
    "/generate_video": {"parameters": [param("prompt", "Textbox", has_default=False), param("negative_prompt", "Textbox"),
                                       param("duration_seconds", "Slider", "float")],
                        "returns": [{"label": "Video", "component": "Video"}, {"label": "Seed", "component": "Number"}]}}}
FLUX = {"named_endpoints": {"/infer": {
    "parameters": [param("prompt", "Textbox", has_default=False), param("seed", "Slider", "float"),
                   param("randomize_seed", "Checkbox", "bool"), param("width", "Slider", "float")],
    "returns": [{"label": "Result", "component": "Image"}, {"label": "Seed", "component": "Slider"}]}}}
NEEDS_MORE = {"named_endpoints": {"/go": {
    "parameters": [param("prompt", "Textbox"), param("style_ref", "Dropdown", has_default=False)],
    "returns": [{"component": "Video"}]}}}


def test_finds_the_right_part_of_each_demo():
    assert generate.pick_endpoint(WAN_I2V, "video", True) == ("/generate_video", "prompt", "input_image")
    assert generate.pick_endpoint(WAN_I2V, "video", False) is None      # needs a picture
    assert generate.pick_endpoint(WAN_T2V, "video", False) == ("/generate_video", "prompt", None)
    assert generate.pick_endpoint(WAN_T2V, "video", True) == ("/generate_video", "prompt", None)
    assert generate.pick_endpoint(FLUX, "image", False) == ("/infer", "prompt", None)
    assert generate.pick_endpoint(FLUX, "video", False) is None
    assert generate.pick_endpoint(NEEDS_MORE, "video", False) is None   # something else it needs


def test_finds_the_file_in_what_comes_back(tmp_path):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    pic = tmp_path / "b.webp"
    pic.write_bytes(b"x")
    assert generate.find_file((str(video), 42), "video") == str(video)
    assert generate.find_file(({"video": str(video), "subtitles": None}, 1), "video") == str(video)
    assert generate.find_file([{"image": str(pic), "caption": None}], "image") == str(pic)
    assert generate.find_file((str(pic), 3), "video") is None
    assert generate.find_file("/nope/missing.mp4", "video") is None


class FakeJob:
    def __init__(self, result=None, error=None, steps=2):
        self._result, self._error, self._steps = result, error, steps
        self.cancelled = False

    def done(self):
        self._steps -= 1
        return self._steps < 0

    def status(self):
        return types.SimpleNamespace(code=types.SimpleNamespace(value="IN_QUEUE"), rank=2, queue_size=5)

    def cancel(self):
        self.cancelled = True

    def result(self):
        if self._error:
            raise self._error
        return self._result


def fake_client(api, job, seen):
    class Client:
        def __init__(self, src, **kw):
            seen.append(("open", src, kw.get("analytics_enabled")))

        def view_api(self, **kw):
            return api

        def submit(self, api_name=None, **args):
            seen.append(("submit", api_name, args))
            return job
    return Client


def test_running_a_demo(monkeypatch, tmp_path):
    import gradio_client

    video = tmp_path / "out.mp4"
    video.write_bytes(b"video")
    seen, said = [], []
    monkeypatch.setattr(gradio_client, "Client", fake_client(WAN_T2V, FakeJob((str(video), 7)), seen))
    got = generate.run_space("zerogpu-aoti/wan2-2-fp8da-aoti", "video", "a frog dancing", None, said.append, None, 30)
    assert got == str(video)
    assert seen[0] == ("open", "zerogpu-aoti/wan2-2-fp8da-aoti", False)
    assert seen[1] == ("submit", "/generate_video", {"prompt": "a frog dancing"})  # only the prompt; the rest stays default
    assert "in line for the free GPU (#3 of 5)…" in said

    job = FakeJob(error=Exception("You have exceeded your free GPU quota (60s requested vs. 0s left). Try again in 4:10:05"))
    monkeypatch.setattr(gradio_client, "Client", fake_client(WAN_T2V, job, []))
    with pytest.raises(generate.LimitReached, match="resets in 4:10:05"):
        generate.run_space("x/y", "video", "a frog", None, lambda s: None, None, 30)

    stop = threading.Event()
    stop.set()
    job = FakeJob(steps=100)
    monkeypatch.setattr(gradio_client, "Client", fake_client(WAN_T2V, job, []))
    with pytest.raises(generate.Stopped):
        generate.run_space("x/y", "video", "a frog", None, lambda s: None, stop, 30)


def test_video_tries_in_the_best_order(monkeypatch, tmp_path):
    tried = []

    def run_space(space, kind, prompt, picture, on_status, stop, timeout):
        tried.append((space, str(picture) if picture else None))
        raise RuntimeError("busy")

    monkeypatch.setattr(generate, "run_space", run_space)
    monkeypatch.setattr(generate, "make_image", lambda *a, **k: (b"\xff\xd8" + b"x" * 3000, "jpg", "test"))
    with pytest.raises(generate.MakeError):
        generate.make_video("a frog dancing")
    assert [s for s, _ in tried] == generate.TEXT_TO_VIDEO + generate.PICTURE_TO_VIDEO[:1]
    assert tried[-1][1] and tried[-1][1].endswith(".jpg")  # last try: paint a first frame, then animate it

    tried.clear()
    pic = tmp_path / "mine.png"
    pic.write_bytes(b"x")
    with pytest.raises(generate.MakeError):
        generate.make_video("dance", pic)
    assert [s for s, _ in tried][:len(generate.PICTURE_TO_VIDEO)] == generate.PICTURE_TO_VIDEO  # their picture first
    assert tried[0][1] == str(pic)

    def limited(*a, **k):
        tried.append("limit")
        raise generate.LimitReached("used up")

    tried.clear()
    monkeypatch.setattr(generate, "run_space", limited)
    with pytest.raises(generate.LimitReached):
        generate.make_video("a frog")
    assert tried == ["limit"]  # the limit is per person: no point asking the other demos


class FakePollinations(BaseHTTPRequestHandler):
    down = False

    def log_message(self, *a):
        pass

    def do_GET(self):
        FakePollinations.path_seen = self.path
        if FakePollinations.down:
            self.send_response(502)
            self.end_headers()
            return
        body = b"\x89PNG\r\n\x1a\n" + b"x" * 4000
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_pictures(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), FakePollinations)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(generate, "POLLINATIONS", f"http://127.0.0.1:{server.server_port}/prompt/")
    monkeypatch.setattr(generate.draw, "available", lambda: False)  # (the online backup)
    data, ext, source = generate.make_image("jett dashing on ascent")
    assert data.startswith(b"\x89PNG") and ext == "png" and "Pollinations" in source
    seen = urllib.parse.unquote(FakePollinations.path_seen)
    assert seen.startswith("/prompt/modest, fully clothed") and "jett dashing on ascent. Jett is a young Korean" in seen
    assert "long dark cargo pants" in seen and "bodysuit" not in seen
    assert "fully clothed" in seen and "safe=true" in seen and "Venice" in seen

    FakePollinations.down = True  # down: a free FLUX demo does it instead
    monkeypatch.setattr(generate, "run_space", lambda space, kind, *a, **k: (_ for _ in ()).throw(RuntimeError("busy")))
    with pytest.raises(generate.MakeError):
        generate.make_image("a cat")
    FakePollinations.down = False
    server.shutdown()


def test_saving_and_showing_what_he_made():
    made = attachments.save_made("chat1", b"\x00\x00\x00\x18ftypmp42" + b"x" * 100, "mp4", "video", "A Frog, Dancing!")
    assert made["made"] and made["name"] == "flip-a-frog-dancing.mp4" and made["kind"] == "video"
    assert attachments.load_video("chat1", made["id"]).startswith("data:video/mp4;base64,")
    assert attachments.path_of("chat1", "../../etc/passwd") is None
    assert attachments.meta([dict(made, url="data:…")]) == [made]  # prompt and "made" are kept, the data isn't
    chat = {"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y", "attachments": [made]}]}
    assert generate.last_made(chat) == {"kind": "video", "prompt": "A Frog, Dancing!", "id": made["id"]}
    assert generate.last_made({"messages": chat["messages"] + [{"role": "assistant", "content": "z"}]}) is None


def test_knows_when_they_want_a_picture_or_a_video():
    want = router.media_request
    assert want("make a picture of jett dashing on ascent") == ("image", "jett dashing on ascent")
    assert want("yo can you make me an anime picture of Reyna?") == ("image", "Reyna, anime")
    assert want("draw me a cute cat") == ("image", "cute cat")
    assert want("make a video of a car drifting in tokyo at night") == ("video", "a car drifting in tokyo at night")
    assert want("animate this", has_picture=True)[0] == "video"
    for no in ("can you make pictures?", "how do I make a video for youtube?", "make a video game in roblox",
               "make an image button in my gui", "what's in this picture?", "make me a plan for ranked", "thanks bro"):
        assert want(no) is None, no
    cat = {"kind": "image", "prompt": "a cute cat", "id": "x.jpg"}
    assert want("make it darker", last=cat) == ("image", "a cute cat, darker")
    assert want("another one", last=cat) == ("image", "a cute cat")
    assert want("now animate it", last=cat) == ("video", "a cute cat")
    assert want("a sunset over the ocean", mode="image") == ("image", "sunset over the ocean")
    assert generate.not_ok("a naked person") and not generate.not_ok("jett on ascent")


def test_with_a_real_gradio_demo(tmp_path):
    """Runs a small local demo shaped like Wan 2.2's (only when gradio is installed)."""
    gr = pytest.importorskip("gradio")

    def make(picture, prompt, steps=4, negative_prompt="blurry", seed=42):
        out = tmp_path / "made.mp4"
        out.write_bytes(b"\x00\x00\x00\x18ftypmp42" + prompt.encode())
        return str(out), seed

    with gr.Blocks() as demo:
        pic, prompt = gr.Image(type="filepath", label="Input Image"), gr.Textbox(label="Prompt", value="move")
        steps, neg, seed = gr.Slider(1, 8, value=4, label="Steps"), gr.Textbox(label="Negative prompt", value="x"), gr.Number(42)
        out = gr.Video(label="Video")
        gr.Button().click(make, [pic, prompt, steps, neg, seed], [out, seed], api_name="generate_video")
    _, url, _ = demo.queue().launch(prevent_thread_lock=True, quiet=True)
    try:
        still = tmp_path / "still.png"
        from PIL import Image
        Image.new("RGB", (32, 32), "red").save(still)
        got = generate.run_space(url, "video", "a red square spinning", still, lambda s: None, None, 60)
        assert open(got, "rb").read().endswith(b"a red square spinning")
    finally:
        demo.close()


def test_agents_and_maps_look_right():
    d = generate.describe("jett throwing daggers")
    assert "short white hair" in d and "kunai" in d and "Valorant" in d and "fully clothed" in d
    assert "Bhutan" in generate.describe("haven at night")
    assert generate.describe("a cat in space") == "a cat in space"  # nothing to add
    assert "fully clothed" in generate.describe("anime girl with a sword")


class FakeArt(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = b"\x89PNG\r\n\x1a\n" + b"a" * 5000
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.end_headers()
        self.wfile.write(body)


def test_plain_agent_or_map_pictures_are_the_real_art(monkeypatch):
    import livedata

    server = HTTPServer(("127.0.0.1", 0), FakeArt)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    monkeypatch.setattr(livedata, "art", lambda: {"jett": {"name": "Jett", "kind": "agent", "url": url + "jett"},
                                                  "haven": {"name": "Haven", "kind": "map", "url": url + "haven"}})
    for ask in ("Jett", "jett full body", "the valorant map haven", "Haven"):
        data, ext, source = generate.make_image(ask)
        assert data.startswith(b"\x89PNG") and "official" in source, ask
    monkeypatch.setattr(generate, "_pollinations", lambda prompt, size, stop: (b"painted", "jpg"))
    monkeypatch.setattr(generate.draw, "available", lambda: False)  # (drawing on the PC is tested in test_draw)
    assert generate.make_image("jett throwing daggers")[0] == b"painted"  # a scene gets painted
    assert generate.make_image("jett and haven")[0] == b"painted"
    server.shutdown()


def test_nothing_is_left_behind_after_making_a_video(monkeypatch):
    import shutil

    shutil.rmtree(generate.TMP, ignore_errors=True)
    monkeypatch.setattr(generate, "_pollinations", lambda prompt, size, stop: (b"\x89PNG" + b"f" * 3000, "png"))

    def space(name, kind, prompt, pic, *a, **k):
        if pic is None or "wan" not in name or "faster" not in name:
            raise RuntimeError("busy")  # only painting the first frame and animating it works
        out = generate.TMP / "run1" / "video.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"video")
        return str(out)
    monkeypatch.setattr(generate, "run_space", space)
    path, source = generate.make_video("a frog dancing")
    assert Path(path).read_bytes() == b"video"
    generate.tidy(path)
    assert not generate.TMP.exists() or not any(generate.TMP.rglob("*"))  # the painted frame is gone too


def test_starting_flip_clears_leftover_downloads_but_keeps_what_he_made():
    import storage

    made = attachments.save_made("keepchat", b"\x89PNG" + b"k" * 3000, "png", "image", "a kept picture")
    (generate.TMP / "crashed").mkdir(parents=True, exist_ok=True)
    (generate.TMP / "crashed" / "half.mp4").write_bytes(b"half")
    storage.tidy_on_start()
    assert not generate.TMP.exists()
    assert attachments.path_of("keepchat", made["id"]).read_bytes().startswith(b"\x89PNG")  # never lost


def test_ok_makes_what_they_asked_for():
    h = [{"role": "user", "content": "generate me a video of jett throwing daggers"},
         {"role": "assistant", "content": "jett's daggers? let me generate that video for you right now, just say the word."}]
    assert router.pending_request("ok generate it, whatever u decide", h) == ("video", "jett throwing daggers")  # (user's screenshot)
    assert router.pending_request("ok", h) == ("video", "jett throwing daggers")
    assert router.pending_request("ok what else?", h) is None
    offered = [{"role": "user", "content": "ur not generating it"},
               {"role": "assistant", "content": "i can make a picture of jett mid-throw with daggers in her hand. want that?"}]
    assert router.pending_request("ok", offered) == ("image", "jett mid-throw with daggers in her hand")
    made = h + [{"role": "assistant", "content": "filmed it", "attachments": [{"made": True}]}]
    assert router.pending_request("ok", made) is None  # already made: "ok" is just "ok"
    assert router.media_request("can you make a vid of reyna dancing") == ("video", "reyna dancing")


def test_he_never_claims_he_made_something(monkeypatch):
    import store
    from brain import Brain

    class Backend:
        def answer(self, system, history, tools, run_tool, on_text=None, stop=None, **kw):
            text = "just made it, jett throwing daggers in slow-mo. watch her land the final dagger mid-air."
            on_text(text)
            return text, False

    if store.account is None:
        store.use_account(store.create_account("honest", "password1"))
    store.use_profile(store.profiles()[0] if store.profiles() else store.create_profile("Sam"))
    b = Brain({"name": "Flip", "roblox_studio": False}, "You are {name}.", "http://127.0.0.1:9/v1")
    b.backend = Backend()
    reply, _, _ = b.chat("honestchat", "where can i see the video")
    assert "made it" not in reply and "make a video of" in reply


def test_pictures_are_drawn_on_this_pc_first(monkeypatch):
    asked = []
    monkeypatch.setattr(generate.draw, "available", lambda: True)
    monkeypatch.setattr(generate.draw, "draw", lambda prompt, on_status, stop: asked.append(prompt) or b"\x89PNG local")
    monkeypatch.setattr(generate, "_pollinations", lambda *a: (_ for _ in ()).throw(AssertionError("went online")))
    data, ext, source = generate.make_image("a frog wearing a gaming headset")
    assert data == b"\x89PNG local" and source == "drawn on this PC" and "frog" in asked[0]
    assert generate.describe("anime girl with a sword").startswith("modest, fully clothed")
