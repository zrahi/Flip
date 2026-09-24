import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
import pytest

import store
import voice
from brain import Brain

HERE = Path(__file__).resolve().parent


def test_accounts_and_passwords():
    acct = store.create_account("zrahi", "hunter22")
    raw = (store.ACCOUNTS_FILE).read_text()
    assert "hunter22" not in raw                       # password is never saved as-is
    with pytest.raises(ValueError):
        store.create_account("ZRAHI", "whatever1")     # username taken
    with pytest.raises(ValueError):
        store.create_account("x", "whatever1")         # username too short
    with pytest.raises(ValueError):
        store.create_account("sam", "123")             # password too short
    assert store.login("Zrahi", "hunter22")["id"] == acct["id"]
    for _ in range(store.MAX_TRIES):
        with pytest.raises(ValueError, match="wrong"):
            store.login("zrahi", "nope")
    with pytest.raises(ValueError, match="wait"):      # locked out after too many tries
        store.login("zrahi", "hunter22")
    store._tries.clear()
    store.change_password(acct["id"], "hunter22", "newpass9")
    assert store.login("zrahi", "newpass9")
    store.use_account(acct)


def test_profiles_keep_things_separate():
    a = store.create_profile("Marru", "1234")
    b = store.create_profile("Sam")
    with pytest.raises(ValueError):
        store.create_profile("marru")          # name taken
    with pytest.raises(ValueError):
        store.create_profile("Zed", "12")      # PIN too short
    assert store.check_pin(a["id"], "0000") is None
    assert store.check_pin(a["id"], "1234")["name"] == "Marru"
    assert store.check_pin(b["id"], "")["name"] == "Sam"
    assert [p["has_pin"] for p in store.public_profiles()] == [True, False]
    assert "pin" not in store.public_profiles()[0]

    store.use_profile(a)
    store.remember("Marru likes obbies")
    store.use_profile(b)
    assert store.memories() == []              # Sam can't see Marru's memory
    store.delete_profile(b["id"])
    assert [p["name"] for p in store.public_profiles()] == ["Marru"]
    store.use_profile(a)
    store.forget(store.memories()[0]["id"])

    other = store.create_account("friend", "password1")  # another account can't see these profiles
    store.use_account(other)
    assert store.public_profiles() == []
    store.use_account(store.login("zrahi", "newpass9"))


def test_chats_and_memory():
    store.use_profile(store.profiles()[0])
    chat = store.new_chat()
    assert store.load_chat(chat["id"]) is None  # empty chats aren't saved
    chat["messages"].append({"role": "user", "content": "hi"})
    store.save_chat(chat)
    assert [c["id"] for c in store.list_chats()] == [chat["id"]]
    store.delete_chat(chat["id"])
    assert store.list_chats() == []
    assert store.load_chat("../../etc") is None

    m = store.remember("likes Roblox")
    assert store.remember("Likes roblox") is None  # no duplicates
    assert store.forget(m["id"]) and store.memories() == []


def test_storage_cleanup_keeps_what_is_in_use():
    import json
    import storage
    from engine import LLAMA_DIRS, MODEL_DIR
    from paths import DATA

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (MODEL_DIR / "big.gguf").write_bytes(b"x" * 3000)
    (MODEL_DIR / "small.gguf").write_bytes(b"x" * 1000)
    (MODEL_DIR / "models.json").write_text(json.dumps({"org/Big-GGUF": "big.gguf", "org/Small-GGUF": "small.gguf"}))
    for kind, folder in LLAMA_DIRS.items():
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "llama-server.exe").write_bytes(b"x" * 500)
    (DATA / "llama-cuda-0.zip").write_bytes(b"x" * 200)  # unfinished download
    (DATA / "running.json").write_text(json.dumps({"kind": "cuda", "model": "small.gguf"}))

    r = storage.report()
    assert any(i["what"] == "brain: Big" and not i["in_use"] for i in r["items"])
    assert any(i["what"] == "brain: Small" and i["in_use"] for i in r["items"])
    storage.clean_up()
    assert not (MODEL_DIR / "big.gguf").exists() and (MODEL_DIR / "small.gguf").exists()
    assert json.loads((MODEL_DIR / "models.json").read_text()) == {"org/Small-GGUF": "small.gguf"}
    assert not LLAMA_DIRS["vulkan"].exists() and LLAMA_DIRS["cuda"].exists()
    assert not (DATA / "llama-cuda-0.zip").exists()
    for f in (MODEL_DIR / "small.gguf", MODEL_DIR / "models.json", DATA / "running.json"):
        f.unlink()


def test_speakable():
    s = voice.speakable("yo 🔥 **bet**:\n```lua\nprint(1)\n```\nsee https://x.com fr 😭")
    assert s == "yo bet: I dropped the code in the chat. see the link fr"


def test_skills_only_when_relevant():
    from brain import Brain, parse_skill

    sk = parse_skill("KEYWORDS: valorant, jett\nVALORANT TIPS")
    assert sk == {"keywords": ["valorant", "jett"], "text": "VALORANT TIPS"}
    b = Brain({"name": "Flip", "roblox_studio": False}, "You are {name}.", "http://127.0.0.1:9/v1",
              ["KEYWORDS: valorant, jett\nVALORANT TIPS", "ALWAYS ON"])
    assert "VALORANT TIPS" not in b._system("make me a door script")
    assert "VALORANT TIPS" in b._system("how do I play Jett")
    assert "ALWAYS ON" in b._system("anything")


def test_everything_fits_in_the_brain():
    import json
    from brain import MEMORY_TOOLS, REPLY_ROOM, Brain, estimate_tokens

    b = Brain({"name": "Flip", "roblox_studio": False}, "You are {name}.", "http://127.0.0.1:9/v1")
    huge_tools = MEMORY_TOOLS + [{"name": f"t{i}", "description": "x" * 3000, "schema": {"type": "object"}} for i in range(15)]
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": "blah " * 400} for i in range(30)]
    history.append({"role": "user", "content": "a"})
    kept, tools = b._fit("system text", history, huge_tools)
    assert tools == MEMORY_TOOLS                      # the giant tool list got dropped
    assert kept[-1]["content"] == "a" and kept[0]["role"] == "user"
    total = estimate_tokens("system text") + estimate_tokens(json.dumps(tools)) + sum(estimate_tokens(m["content"]) for m in kept)
    assert total <= 8192 - REPLY_ROOM


def test_roblox_tools_only_for_roblox_chats():
    from brain import Brain

    b = Brain({"name": "Flip", "roblox_studio": False}, "You are {name}.", "http://127.0.0.1:9/v1")

    class FakeLink:
        status = "connected"
        tools = [{"name": "run_code", "description": "", "schema": {}}]

    b.roblox = FakeLink()
    assert "run_code" not in [t["name"] for t in b._tools("a")]
    assert "run_code" in [t["name"] for t in b._tools("make my HouseFlipper door script work")]


def test_update_versions():
    from updater import _parse

    assert _parse("v1.12") > _parse("1.9") and _parse("dev") == ()


def test_utterance_detector():
    rng = np.random.default_rng(0)
    t = np.arange(voice.FRAME) / voice.RATE
    quiet = lambda sec: [rng.normal(0, 0.002, voice.FRAME).astype(np.float32) for _ in range(int(sec * voice.RATE / voice.FRAME))]
    loud = lambda sec: [(0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32) for _ in range(int(sec * voice.RATE / voice.FRAME))]
    by_loudness = lambda f: min(1.0, float(np.sqrt(np.mean(f ** 2))) * 25)
    d = voice.UtteranceDetector(chance=by_loudness)
    got = [a for f in quiet(1) + loud(1) + quiet(1.2) if (a := d.feed(f)) is not None]
    assert len(got) == 1
    assert 1.0 <= len(got[0]) / voice.RATE <= 2.4
    d = voice.UtteranceDetector(chance=by_loudness)  # a click is too short to count
    assert [a for f in quiet(1) + loud(0.1) + quiet(1.2) if (a := d.feed(f)) is not None] == []


def test_speech_parts():
    parts = voice.Voice({}).speech_parts("yo that was clean. Hi! You're actually cracked, ngl. Want tips for Ascent?")
    assert parts == ["yo that was clean. Hi! You're actually cracked, ngl.", "Want tips for Ascent?"]


class FakeModel(BaseHTTPRequestHandler):
    """Acts like the AI server: first asks to use tools, then streams an answer word by word."""

    slow = False

    def log_message(self, *a):
        pass

    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _chunk(self, delta):
        data = {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": "qwen",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
        self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()

    def do_GET(self):
        self._send({"object": "list", "data": [{"id": "embed-x", "object": "model"}, {"id": "qwen", "object": "model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeModel.last = body
        assert body["stream"] is True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        last = body["messages"][-1]
        if last["role"] == "user" and "tools please" in last["content"]:
            self._chunk({"role": "assistant", "tool_calls": [
                {"index": 0, "id": "c1", "type": "function", "function": {"name": "remember", "arguments": ""}}]})
            self._chunk({"tool_calls": [{"index": 0, "function": {"arguments": json.dumps({"fact": "name is Marru"})}}]})
            self._chunk({"tool_calls": [{"index": 1, "id": "c2", "type": "function",
                                         "function": {"name": "run_code", "arguments": json.dumps({"command": "print(1)"})}}]})
        else:
            results = [m["content"] for m in body["messages"] if m["role"] == "tool"]
            words = ["<think>", "hmm", "</think>", "bet ", " | ".join(results)] if results else ["yo ", "what's ", "good"]
            if FakeModel.slow:
                words = ["one ", "two ", "three ", "four ", "five "]
            for w in words:
                self._chunk({"content": w})
                if FakeModel.slow:
                    time.sleep(0.3)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def test_brain_memory_tools_and_streaming():
    server = HTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    settings = {"name": "Flip", "roblox_studio": True, "roblox_command": [sys.executable, str(HERE / "fake_mcp.py")]}
    b = Brain(settings, "You are {name}.", f"http://127.0.0.1:{server.server_port}/v1", ["VALORANT know-how"])
    for _ in range(100):
        if b.roblox_status() != "starting":
            break
        time.sleep(0.2)
    assert b.roblox_status() == "connected"
    used, pieces = [], []
    b.on_tool = used.append

    store.use_profile(store.profiles()[0])
    reply, chat, stopped = b.chat("c0ffee", "yo I'm Marru, tools please", on_text=pieces.append)
    assert used == ["remember", "run_code"]
    assert reply.startswith("bet saved as [") and reply.endswith("ran: print(1)")
    assert "<think>" not in reply and "hmm" not in "".join(pieces)
    assert "".join(pieces).strip() == reply     # what streamed is what got saved
    assert not stopped
    assert store.load_chat("c0ffee")["title"] == "yo I'm Marru, tools please"
    assert any(m["text"] == "name is Marru" for m in store.memories())

    b.chat("c0ffee", "again")  # the memory now shows up in what the AI is told
    system = FakeModel.last["messages"][0]["content"]
    assert "name is Marru" in system and "You're talking to Marru" in system and "VALORANT know-how" in system
    assert FakeModel.last["model"] == "qwen"
    assert FakeModel.last["chat_template_kwargs"] == {"enable_thinking": False}  # no slow hidden thinking
    assert b.last_stats["secs"] >= 0

    b.chat("c0ffee", "again", voice=True)  # voice note goes on the message, the system text stays the same
    assert FakeModel.last["messages"][0]["content"] == system
    assert "voice call" in FakeModel.last["messages"][-1]["content"]

    b.chat("c0ffee", "what's on my screen?", image="data:image/jpeg;base64,AAAA", image_label="Valorant")
    parts = FakeModel.last["messages"][-1]["content"]
    assert parts[0]["type"] == "text" and "Valorant" in parts[0]["text"]
    assert parts[1] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}
    assert store.load_chat("c0ffee")["messages"][-2]["content"] == "what's on my screen?"  # the picture isn't saved

    FakeModel.slow = True  # the stop button
    stop = threading.Event()
    threading.Timer(0.8, stop.set).start()
    reply, _, stopped = b.chat("c0ffee", "count", stop=stop)
    FakeModel.slow = False
    assert stopped and reply.startswith("one") and "five" not in reply
    assert store.load_chat("c0ffee")["messages"][-1]["content"] == reply
    server.shutdown()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_downloads_exist():
    import engine

    assert engine.gpu_memory_gb() >= 0
    assert engine.pick_model(24) == engine.MODELS[0][1]
    assert engine.pick_model(8) == engine.MODELS[0][1]  # an 8 GB card like the RTX 4060 gets the 8B brain
    assert engine.pick_model(4) == engine.MODELS[-1][1]
    assert engine.pick_model(0) == engine.MODELS[-1][1]
    for kind, parts in (("vulkan", 1), ("cuda", 2)):
        found = engine.llama_download(kind)
        assert len(found) == parts, (kind, found)
        assert all(url.endswith(".zip") and size > 1e6 for url, size in found)
    for repo in {r for _, r in engine.MODELS} | set(engine.FAST.values()):
        url, name, size = engine.model_download(repo)
        assert name.endswith(".gguf") and size > 5e8, (repo, name, size)
        eyes = engine.eyes_download(repo)
        assert eyes and "mmproj" in eyes[1].lower() and eyes[2] > 1e8, (repo, eyes)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_screen_sharing_sources_and_capture():
    import screen

    items = screen.sources()
    assert items[0]["kind"] == "screen"
    shot = screen.capture(items[0]["id"])
    assert shot and shot.startswith("data:image/jpeg;base64,") and len(shot) > 5000
    windows = [s for s in items if s["kind"] == "window"]
    print("windows:", [w["title"] for w in windows][:10])
    for w in windows[:3]:
        assert screen.capture(w["id"]) is not None, w
