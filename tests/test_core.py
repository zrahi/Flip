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


def test_speakable():
    s = voice.speakable("yo 🔥 **bet**:\n```lua\nprint(1)\n```\nsee https://x.com fr 😭")
    assert s == "yo bet: I dropped the code in the chat. see the link fr"


def test_utterance_detector():
    rng = np.random.default_rng(0)
    chunk = int(voice.RATE * voice.CHUNK_SEC)
    quiet = lambda sec: [rng.normal(0, 0.002, chunk).astype(np.float32) for _ in range(int(sec / voice.CHUNK_SEC))]
    t = np.arange(chunk) / voice.RATE
    loud = lambda sec: [(0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32) for _ in range(int(sec / voice.CHUNK_SEC))]
    d = voice.UtteranceDetector()
    got = [a for c in quiet(1) + loud(1) + quiet(1.2) if (a := d.feed(c)) is not None]
    assert len(got) == 1
    assert 1.0 <= len(got[0]) / voice.RATE <= 2.3


class FakeModel(BaseHTTPRequestHandler):
    """Acts like the AI: first asks to use tools, then answers."""

    def log_message(self, *a):
        pass

    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send({"object": "list", "data": [{"id": "embed-x", "object": "model"}, {"id": "qwen", "object": "model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeModel.last = body
        last = body["messages"][-1]
        if last["role"] == "user":
            calls = [{"id": "c1", "type": "function", "function": {"name": "remember", "arguments": json.dumps({"fact": "name is Marru"})}},
                     {"id": "c2", "type": "function", "function": {"name": "run_code", "arguments": json.dumps({"command": "print(1)"})}}]
            msg = {"role": "assistant", "content": None, "tool_calls": calls}
        else:
            results = [m["content"] for m in body["messages"] if m["role"] == "tool"]
            msg = {"role": "assistant", "content": "<think>hmm</think>bet " + " | ".join(results)}
        self._send({"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                    "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}]})


def test_brain_memory_and_studio_tools():
    server = HTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    settings = {"name": "Flip", "roblox_studio": True, "roblox_command": [sys.executable, str(HERE / "fake_mcp.py")]}
    b = Brain(settings, "You are {name}.", f"http://127.0.0.1:{server.server_port}/v1")
    for _ in range(100):
        if b.roblox_status() != "starting":
            break
        time.sleep(0.2)
    assert b.roblox_status() == "connected"
    used = []
    b.on_tool = used.append

    store.use_profile(store.profiles()[0])
    reply, chat = b.chat("c0ffee", "yo I'm Marru")
    assert used == ["remember", "run_code"]
    assert reply.startswith("bet saved as [") and reply.endswith("ran: print(1)")
    assert "<think>" not in reply
    assert store.load_chat("c0ffee")["title"] == "yo I'm Marru"
    assert any(m["text"] == "name is Marru" for m in store.memories())

    b.chat("c0ffee", "again")  # the memory now shows up in what the AI is told
    assert "name is Marru" in FakeModel.last["messages"][0]["content"]
    assert "You're talking to Marru" in FakeModel.last["messages"][0]["content"]
    assert FakeModel.last["model"] == "qwen"
    server.shutdown()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_downloads_exist():
    import engine

    assert engine.gpu_memory_gb() >= 0
    assert engine.pick_model(24) == engine.MODELS[0][1]
    assert engine.pick_model(8) == engine.MODELS[1][1]
    assert engine.pick_model(0) == engine.MODELS[2][1]
    url, size = engine.llama_download()
    assert url.endswith(".zip") and size > 1e6
    for _, repo in engine.MODELS:
        url, name, size = engine.model_download(repo)
        assert name.endswith(".gguf") and size > 1e9, (repo, name, size)
