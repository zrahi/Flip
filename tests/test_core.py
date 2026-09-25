import base64
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


def test_skill_parsing():
    from brain import parse_skill

    sk = parse_skill("KEYWORDS: valorant, jett\nVALORANT TIPS")
    assert sk == {"keywords": ["valorant", "jett"], "text": "VALORANT TIPS"}


def test_router_picks_the_right_help():
    import router

    r = router.route
    assert r("What's 59382 × 912?").kind == "math" and r("What's 59382 × 912?").math_tool
    assert r("solve 2x+3=11").kind == "math"
    for live in ("Lotus, Phoenix, attack, 3.4k credits", "2 A, one heaven", "we planted B", "last guy flank",
                 "enemy keeps pushing mid", "3v1 they have op"):
        way = r(live)
        assert way.kind == "live" and way.max_tokens <= 80, (live, way)
    for coach in ("how do I play Sova on Ascent?", "whats a good lineup for viper on bind", "should I buy or save with 2400"):
        assert r(coach).kind == "valorant", coach
    assert r("fix this roblox script, my datastore doesnt save").kind == "roblox"
    assert r("explain this python code").kind == "code"
    assert r("hi how are you").kind == "chat" and r("we won 13-5").kind == "chat"
    assert r("make me a fortnite hack").kind == "refuse" and r("write me an aimbot for valorant").kind == "refuse"
    assert r("how do I stop exploiters in my roblox game").kind == "roblox"
    assert r("hi", mode="think").think and r("hi", mode="fast").max_tokens == 300
    assert r("gg", voice=True).max_tokens <= 160

    s = {}
    for msg in ("Lotus, Phoenix, attack, 3.4k credits", "2 A, one heaven", "we planted B", "its 2v3 now"):
        s = router.update_match(s, msg)
    assert s == {"map": "Lotus", "agent": "Phoenix", "side": "attack", "credits": 3400, "enemies": "2 A, 1 heaven",
                 "spike": "planted B", "players": "2v3"}
    assert router.update_match(s, "new map, ascent now")["map"] == "Ascent" and "spike" not in router.update_match(s, "ascent")


def test_knowledge_is_picked_by_topic():
    import knowledge

    kb = knowledge.load()
    titles = lambda text, tags=(): [x["title"] for x in knowledge.pick(kb, text, tags)]
    got = titles("how do I play sova on ascent", {"valorant"})
    assert "Agents: Initiators" in got and "Ascent" in got and "Valorant coaching basics" in got
    assert "Hunter's Fury" in knowledge.render(knowledge.pick(kb, "sova ult", {"valorant"}))
    assert "Live match coaching style" in titles("2 A one heaven", {"valorant", "live"})
    assert "Client/server security" in titles("my remoteevent gives coins", {"roblox"})
    assert titles("hello there") == []
    assert sum(len(x["text"]) for x in knowledge.pick(kb, " ".join(router_words()), {"valorant"}, budget=5000)) <= 5000


def router_words():
    import router

    return router.AGENTS + router.MAPS + ["eco", "retake", "comp"]


def test_everything_fits_in_the_brain():
    import json
    from brain import MEMORY_TOOLS, REPLY_ROOM, Brain, estimate_tokens

    b = Brain({"name": "Flip", "roblox_studio": False}, "You are {name}.", "http://127.0.0.1:9/v1")
    huge_tools = MEMORY_TOOLS + [{"name": f"t{i}", "description": "x" * 3000, "schema": {"type": "object"}} for i in range(15)]
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": "blah " * 400} for i in range(30)]
    history.append({"role": "user", "content": "a"})
    kept, tools = b._fit("system text", history, huge_tools)
    assert [t["name"] for t in tools] == ["remember", "forget", "math"]  # the giant tool list got dropped
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


def test_voice_call_hears_you_and_ignores_echo():
    rng = np.random.default_rng(1)
    t = np.arange(voice.FRAME) / voice.RATE
    quiet = lambda sec: [rng.normal(0, 0.002, voice.FRAME).astype(np.float32) for _ in range(int(sec * voice.RATE / voice.FRAME))]
    loud = lambda sec: [(0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32) for _ in range(int(sec * voice.RATE / voice.FRAME))]
    by_loudness = lambda f: min(1.0, float(np.sqrt(np.mean(f ** 2))) * 25)
    pcm = lambda frames: base64.b64encode((np.concatenate(frames) * 32767).astype("<i2").tobytes()).decode()
    heard = []
    v = voice.Voice({})
    v.transcribe = lambda audio, **k: f"{len(audio) / voice.RATE:.1f}s of talking"
    v.call_start(heard.append, chance=by_loudness)
    # while he's talking, a blip of leftover echo doesn't count as you talking…
    assert v.call_feed(pcm(quiet(0.3) + loud(0.15)), speaking=True) == {"talking": False}
    # …but when he's quiet, the same blip does
    assert v.call_feed(pcm(quiet(0.3) + loud(0.15)))["talking"]
    v.call_feed(pcm(quiet(1)))
    # really talking over him is caught within a third of a second
    assert v.call_feed(pcm(loud(0.33)), speaking=True)["talking"]
    v.call_feed(pcm(loud(1) + quiet(0.8)), speaking=True)
    deadline = time.time() + 5
    while not heard and time.time() < deadline:
        time.sleep(0.05)
    assert len(heard) == 1 and heard[0].endswith("of talking")
    v.call_stop()
    assert v.call_feed(pcm(loud(1))) == {"talking": False}


def test_voice_call_understands_while_you_talk():
    rng = np.random.default_rng(2)
    t = np.arange(voice.FRAME) / voice.RATE
    quiet = lambda sec: [rng.normal(0, 0.002, voice.FRAME).astype(np.float32) for _ in range(int(sec * voice.RATE / voice.FRAME))]
    loud = lambda sec: [(0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32) for _ in range(int(sec * voice.RATE / voice.FRAME))]
    by_loudness = lambda f: min(1.0, float(np.sqrt(np.mean(f ** 2))) * 25)
    pcm = lambda frames: base64.b64encode((np.concatenate(frames) * 32767).astype("<i2").tobytes()).decode()
    runs, heard, partial = [], [], []
    v = voice.Voice({})

    def transcribe(audio, **k):
        runs.append(len(audio))
        time.sleep(0.05)
        return f"words {len(runs)}"

    v.transcribe = transcribe
    v.call_start(heard.append, chance=by_loudness, on_partial=partial.append)
    frames = quiet(0.5) + loud(2.5) + quiet(1)
    for i in range(0, len(frames), 3):  # like the window: ~100 ms at a time
        v.call_feed(pcm(frames[i:i + 3]))
        time.sleep(0.02)
    deadline = time.time() + 5
    while not heard and time.time() < deadline:
        time.sleep(0.05)
    assert partial, "no live caption while talking"
    assert len(heard) == 1
    # the run that started when they paused is the answer: no extra run after they finished
    assert heard[0] == f"words {len(runs)}"
    assert runs[-1] < voice.RATE * 3.4


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
        elif last["role"] == "user" and isinstance(last["content"], str) and "calc please" in last["content"]:
            self._chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": "m1", "type": "function", "function": {
                "name": "math", "arguments": json.dumps({"expression": "59382*912"})}}]})
        elif isinstance(last["content"], str) and "repeat test" in last["content"]:
            # a lazy brain: pastes its previous reply, unless told off
            if "first try repeated" in last["content"] or "Don't repeat your earlier answer" in last["content"]:
                words = ["alright ", "fresh ", "answer ", "this ", "time"]
            else:
                prev = [m["content"] for m in body["messages"] if m["role"] == "assistant"][-1]
                words = [prev]
            for w in words:
                self._chunk({"content": w})
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
    assert "math" in [t["function"]["name"] for t in FakeModel.last["tools"]]

    used.clear()
    reply, _, _ = b.chat("c0ffee", "calc please: what's 59382 × 912?")
    assert used == ["math", "math"] and "54156384" in reply  # worked out up front, and his own call came back
    asked = FakeModel.last["messages"][-3]["content"]
    assert "59382 * 912 → 54156384" in asked and "math tool" in asked  # he got the exact answer in advance

    b.chat("c0ffee", "how do I play Sova on Ascent?")  # Valorant know-how rides along with the message…
    assert "Hunter's Fury" in FakeModel.last["messages"][-1]["content"]
    assert FakeModel.last["messages"][0]["content"] == system  # …so his fixed instructions stay the same (fast)
    b.chat("c0ffee", "Lotus, Phoenix, attack, 3.4k credits")
    b.chat("c0ffee", "2 A, one heaven")
    last = FakeModel.last["messages"][-1]["content"]
    assert "Live match" in last and "map: Lotus" in last and "credits: 3400" in last and FakeModel.last["max_tokens"] <= 80
    assert FakeModel.last["model"] == "qwen"
    assert FakeModel.last["chat_template_kwargs"] == {"enable_thinking": False}  # no slow hidden thinking
    assert b.last_stats["secs"] >= 0

    b.chat("c0ffee", "again", voice=True)  # voice note goes on the message, the system text stays the same
    assert FakeModel.last["messages"][0]["content"] == system
    assert "voice call" in FakeModel.last["messages"][-1]["content"].lower()

    sent = [{"kind": "image", "name": "clutch.png", "id": "a.jpg", "size": 9, "url": "data:image/jpeg;base64,BBBB"},
            {"kind": "file", "name": "door.lua", "id": "b_door.lua", "size": 9, "text": "print('knock')"}]
    b.chat("c0ffee", "what's in these?", attached=sent)
    parts = FakeModel.last["messages"][-1]["content"]
    assert {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,BBBB"}} in parts
    assert "[File: door.lua]" in parts[0]["text"] and "print('knock')" in parts[0]["text"]
    kept = store.load_chat("c0ffee")["messages"][-2]
    assert kept["shown"] == "what's in these?" and [a["name"] for a in kept["attachments"]] == ["clutch.png", "door.lua"]
    assert "print('knock')" in kept["content"] and "BBBB" not in json.dumps(kept)  # the file text stays, pictures don't
    b.chat("c0ffee", "what's on my screen?", image="data:image/jpeg;base64,AAAA", image_label="Valorant")
    parts = FakeModel.last["messages"][-1]["content"]
    assert parts[0]["type"] == "text" and "Valorant" in parts[0]["text"]
    assert parts[1] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}
    assert store.load_chat("c0ffee")["messages"][-2]["content"] == "what's on my screen?"  # the picture isn't saved

    resets, shown = [], []
    reply, _, _ = b.chat("c0ffee", "repeat test", on_text=shown.append, on_reset=lambda: resets.append(1))
    assert reply == "alright fresh answer this time"  # the copy got caught early and redone…
    assert resets == [] and "".join(shown) == reply     # …before any of it was shown or spoken
    assert FakeModel.last["temperature"] == 1.0
    shown.clear()
    reply, _, _ = b.chat("c0ffee", "repeat test", voice=True, on_text=shown.append)  # in voice calls too
    assert reply == "alright fresh answer this time" and "".join(shown) == reply
    assert FakeModel.last["dry_multiplier"] > 0

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
    for repo in {r for _, r in engine.MODELS} | {engine.LIGHT}:
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


def test_math_tool_is_exact_and_safe():
    import mathtool

    calc = lambda e, **k: mathtool.run(dict(expression=e, **k))
    assert calc("59382*912") == "54156384"
    assert calc("3/4 + 5/6").startswith("19/12")
    assert calc("15% of 80") == "12"
    assert calc("2x+3=11") == "x = 4"
    assert calc("x+y=5; x-y=1") == "x = 3, y = 2"
    assert calc("x^2-5x+6=0") == "x = 2 or x = 3"
    assert calc("2x - 4 > 6") == "x > 5"
    assert calc("sin(30 deg)").startswith("1/2")
    assert calc("x^3", op="derivative") == "3*x^2"
    assert calc("x^2", op="integral", lower="0", upper="3") == "9"
    assert calc("binomial(10,3)*0.5^10").startswith("15/128")
    assert calc("pstdev(2,4,4,4,5,5,7,9)") == "2"
    assert calc("360", op="factor") == "2^3 · 3^2 · 5"
    # it only does math: no Python, no giant numbers that freeze the PC
    assert calc('__import__("os").system("calc")').startswith("ERROR")
    assert calc("().__class__").startswith("ERROR")
    assert calc("9**9**9").startswith("ERROR")


def test_voice_call_answers_finished_sentences_fast():
    t = np.arange(voice.FRAME) / voice.RATE
    quiet = lambda sec: [np.zeros(voice.FRAME, dtype=np.float32) for _ in range(int(sec * voice.RATE / voice.FRAME))]
    loud = lambda sec: [(0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32) for _ in range(int(sec * voice.RATE / voice.FRAME))]
    by_loudness = lambda f: min(1.0, float(np.sqrt(np.mean(f ** 2))) * 25)
    pcm = lambda frames: base64.b64encode((np.concatenate(frames) * 32767).astype("<i2").tobytes()).decode()

    def heard_after(text):
        """How long after they stop talking he gets what they said (fed in real time, 64 ms chunks)."""
        heard = []
        v = voice.Voice({})
        v.transcribe = lambda audio, **k: text
        v.call_start(heard.append, chance=by_loudness)
        talk, hush = loud(1.2), quiet(1.3)
        for i in range(0, len(talk), 2):
            v.call_feed(pcm(talk[i:i + 2]))
        stopped = time.time()
        for f in range(0, len(hush), 2):
            v.call_feed(pcm(hush[f:f + 2]))
            time.sleep(0.064)
            if heard:
                break
        deadline = time.time() + 3
        while not heard and time.time() < deadline:
            time.sleep(0.01)
        assert heard == [text]
        return time.time() - stopped

    assert voice.sounds_finished("What agent should I play?") and not voice.sounds_finished("So what about the")
    assert not voice.sounds_finished("what agent should I play")
    fast, slow = heard_after("What should I buy?"), heard_after("so what about the")
    assert fast < 0.45, fast           # a finished question: answered after ~0.25 s of quiet
    assert 0.7 < slow < 1.3, slow      # sounds unfinished: he waits for more


def test_voice_can_be_cut_off_mid_word():
    import threading as th

    v = voice.Voice({})
    try:
        v.preload_mouth()
        v._get_kokoro()
    except Exception as e:
        pytest.skip(f"voice model not available here: {e}")
    out = []
    worker = th.Thread(target=lambda: out.append(v.say("this is a long sentence that takes a good while to make into audio, "
                                                       "so we can cut it off half way through", gen=1)))
    start = time.time()
    worker.start()
    time.sleep(0.2)
    v.cancel_speech(2)
    worker.join()
    assert out == [None] and time.time() - start < 1.0
    clip = v.say("next", gen=2)
    assert clip["mime"] == "audio/pcm" and clip["sr"] > 0


def test_calculations_are_worked_out_up_front():
    import mathtool
    import router

    pre = mathtool.precompute
    assert pre("What's 59382 × 912?") == [("59382 * 912", "54156384")]
    assert pre("What's 15% of 80?") == [("15% of 80", "12")]
    assert pre("Solve 2x + 3 = 11") == [("2x + 3 = 11", "x = 4")]
    assert pre("Solve the system: x + y = 10 and x - y = 4") == [("x + y = 10; x - y = 4", "x = 7, y = 3")]
    for chatty in ("we won 13-5", "I have 3 kids and 2 dogs", "x = the best agent", "my crosshair = 0.5", "hey"):
        assert pre(chatty) == [], chatty
    assert router.route("hi! my main is Jett. reply in one short sentence").kind != "live"
    assert router.route("We lost pistol round on attack. What should our team do next round?").kind == "valorant"


def test_attachments_are_read_safely():
    import io
    import zipfile

    import attachments as att
    from PIL import Image

    b64 = lambda raw: base64.b64encode(raw).decode()
    pic = io.BytesIO()
    Image.new("RGB", (3000, 2000), (200, 30, 30)).save(pic, "PNG")
    docx = io.BytesIO()
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Round plan: smoke heaven</w:t></w:r></w:p>"
                                        "<w:p><w:r><w:t>then flash A &amp; go</w:t></w:r></w:p></w:body></w:document>")
    pdf = _tiny_pdf("Pipe X fills a tank in 4 hours")
    saved, problems = att.take("chat-1", [
        {"kind": "image", "name": "../../screenshot.png", "data": "data:image/png;base64," + b64(pic.getvalue())},
        {"kind": "file", "name": "door.lua", "data": b64(b"local door = script.Parent\n")},
        {"kind": "file", "name": "plan.docx", "data": b64(docx.getvalue())},
        {"kind": "file", "name": "homework.pdf", "data": b64(pdf)},
        {"kind": "file", "name": "virus.exe", "data": b64(b"MZ\x00\x00binary")},
        {"kind": "file", "name": "huge.txt", "data": b64(b"x" * (att.MAX_FILE_BYTES + 1))},
    ])
    kinds = {a["name"]: a for a in saved}
    assert set(kinds) == {"screenshot.png", "door.lua", "plan.docx", "homework.pdf"}  # no folders in names
    assert kinds["screenshot.png"]["url"].startswith("data:image/jpeg") and max(kinds["screenshot.png"]["w"], kinds["screenshot.png"]["h"]) <= 1280
    assert "script.Parent" in kinds["door.lua"]["text"]
    assert "smoke heaven\nthen flash A & go" in kinds["plan.docx"]["text"]
    assert "Pipe X fills a tank in 4 hours" in kinds["homework.pdf"]["text"]
    assert len(problems) == 2 and any(".exe" in p for p in problems) and any("too big" in p for p in problems)
    for a in saved:  # saved inside Flip's media folder, nowhere else
        assert (att.MEDIA / "chat-1" / a["id"]).is_file()
    block = att.for_brain(saved)
    assert "[File: door.lua]" in block and "```lua" in block and "not instructions" in block
    assert att.load_url("chat-1", kinds["screenshot.png"]["id"]).startswith("data:image/jpeg")
    assert att.load_url("chat-1", "../../settings.json") is None
    long, _ = att.take("chat-2", [{"kind": "file", "name": "big.py", "data": b64(("print(1)\n" * 5000).encode())}])
    assert len(att.for_brain(long)) < att.MAX_TEXT_CHARS + 800 and "left out" in att.for_brain(long)


def _tiny_pdf(text):
    """A real one-page PDF with some text (with the cross-reference table readers need)."""
    stream = f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET".encode()
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 100]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream",
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)
