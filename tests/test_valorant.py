import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import hotkey
import knowledge
import livedata
import router
import web

# Shaped like valorant-api.com's answers (trimmed).
AGENTS = [
    {"displayName": "Jett", "isPlayableCharacter": True, "fullPortrait": "http://art/jett.png", "role": {"displayName": "Duelist"}, "abilities": [
        {"slot": "Ultimate", "displayName": "Blade Storm", "description": "EQUIP a set of highly accurate knives."},
        {"slot": "Ability1", "displayName": "Updraft", "description": "INSTANTLY propel Jett high into the air."},
        {"slot": "Ability2", "displayName": "Tailwind", "description": "ACTIVATE to prepare a gust of wind."},
        {"slot": "Grenade", "displayName": "Cloudburst", "description": "INSTANTLY throw a projectile that expands."},
        {"slot": "Passive", "displayName": "Drift", "description": "Hold jump to glide."}]},
    {"displayName": "Novaa", "isPlayableCharacter": True, "role": {"displayName": "Initiator"}, "abilities": [
        {"slot": "Ability1", "displayName": "Starline", "description": "A brand-new ability."}]},
    {"displayName": "Sova", "isPlayableCharacter": False, "role": None, "abilities": []},  # a duplicate test entry
]
MAPS = [
    {"displayName": "Ascent", "splash": "http://art/ascent.png", "tacticalDescription": "A/B Sites", "callouts": [
        {"regionName": "Tree", "superRegionName": "A"}, {"regionName": "Heaven", "superRegionName": "A"},
        {"regionName": "Market", "superRegionName": "Mid"}, {"regionName": "Tree", "superRegionName": "A"}]},
    {"displayName": "The Range", "tacticalDescription": None, "callouts": None},
    {"displayName": "Piazza", "tacticalDescription": None, "callouts": [{"regionName": "X", "superRegionName": "Y"}]},
]
WEAPONS = [
    {"displayName": "Vandal", "shopData": {"cost": 2900, "category": "Rifles"},
     "weaponStats": {"magazineSize": 25, "damageRanges": [{"rangeStartMeters": 0, "rangeEndMeters": 50, "headDamage": 160,
                                                           "bodyDamage": 40, "legDamage": 34}]}},
    {"displayName": "Melee", "shopData": None, "weaponStats": None},
]
GEAR = [{"displayName": "Regen Shield", "shopData": {"cost": 650}, "description": "Regenerates shields."}]
VERSION = {"riotClientVersion": "release-11.06-shipping-9-3565925", "version": "11.06.00.3565925"}


def test_live_notes_from_the_game_data():
    text = livedata.build("11.06", AGENTS, MAPS, WEAPONS, GEAR)
    sections = {s["title"]: s for s in knowledge.parse(text, "valorant-current")}
    live = sections["Current agents and version (live)"]
    assert "*valorant" in live["keys"] and "Duelists: Jett" in live["text"] and "Initiators: Novaa" in live["text"]
    assert "Sova" not in live["text"]  # not a playable entry
    jett = sections["Jett (Duelist), current kit"]
    assert "updraft" in jett["keys"] and "jett" in jett["keys"]
    lines = jett["text"].splitlines()
    assert lines[0].startswith("- Q: Updraft") and lines[1].startswith("- E: Tailwind") and "X (ult): Blade Storm" in lines[3]
    ascent = sections["Ascent callouts (current)"]
    assert "A: Tree, Heaven" in ascent["text"] and "Mid: Market" in ascent["text"]
    assert not any("Range" in t or "Piazza" in t for t in sections)  # not competitive maps
    guns = sections["Guns and prices (current)"]
    assert "Vandal: 2900 credits, Rifle, 25 rounds, head/body/legs 160/40/34 at 0-50 m" in guns["text"]
    assert "Regen Shield (650 credits)" in sections["Shields (current)"]["text"]
    # a brand-new agent the old notes never heard of gets picked when mentioned
    chosen = knowledge.pick(list(sections.values()), "how do I play novaa", {"valorant"})
    assert any("Novaa" in s["text"] for s in chosen)
    assert livedata.version_text(VERSION) == "11.06"


class FakeAPI(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        FakeAPI.calls.append(self.path)
        data = {"/v1/version": VERSION}.get(self.path) or (
            AGENTS if "agents" in self.path else MAPS if "maps" in self.path else WEAPONS if "weapons" in self.path
            else GEAR)
        body = json.dumps({"status": 200, "data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def test_refresh_downloads_once_a_day(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), FakeAPI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(livedata, "API", f"http://127.0.0.1:{server.server_port}/v1/")
    monkeypatch.setattr(livedata, "patch_notes", lambda version, names: None)  # no web here
    livedata.NOTES.unlink(missing_ok=True)
    assert livedata.refresh() is True
    assert "Jett (Duelist), current kit" in livedata.NOTES.read_text(encoding="utf-8")
    n = len(FakeAPI.calls)
    assert livedata.refresh() is False and len(FakeAPI.calls) == n  # checked today already: nothing downloaded
    state = json.loads(livedata.STATE.read_text())
    livedata.STATE.write_text(json.dumps(dict(state, checked=0)))
    assert livedata.refresh() is False and FakeAPI.calls[n:] == ["/v1/version"]  # a day later, same version: just a check
    assert any(s["source"] == "valorant-current" for s in knowledge.load())  # his notes read it
    assert livedata.art() == {"jett": {"name": "Jett", "kind": "agent", "url": "http://art/jett.png"},
                              "ascent": {"name": "Ascent", "kind": "map", "url": "http://art/ascent.png"}}
    server.shutdown()
    livedata.NOTES.unlink()


RESULTS_HTML = """
<div class="result results_links"><div class="links_main result__body">
<h2 class="result__title"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fplayvalorant.com%2Fen-us%2Fnews%2Fgame-updates%2Fvalorant-patch-notes-11-06%2F&amp;rut=abc">VALORANT Patch Notes 11.06</a></h2>
<a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">Welcome to <b>Patch Notes 11.06</b>. Jett changes…</a>
</div></div>
<div class="result"><h2><a class="result__a" rel="nofollow" href="https://duckduckgo.com/y.js?ad_domain=ads.example">Ad</a></h2></div>
<div class="result"><h2 class="result__title"><a href="https://www.youtube.com/watch?v=abc" class="result__a">Sova Ascent lineups</a></h2>
<a class="result__snippet">Every recon lineup on Ascent</a></div>
"""
LITE_HTML = """
<table><tr><td valign="top">1.&nbsp;</td><td><a rel="nofollow" href="https://blitz.gg/valorant/meta" class='result-link'>Valorant meta tier list</a></td></tr>
<tr><td>&nbsp;&nbsp;&nbsp;</td><td class='result-snippet'>The best <b>agents</b> right now</td></tr></table>
"""


def test_reads_search_results():
    got = web.parse_results(RESULTS_HTML)
    assert [r["url"] for r in got] == ["https://playvalorant.com/en-us/news/game-updates/valorant-patch-notes-11-06/",
                                       "https://www.youtube.com/watch?v=abc"]  # the ad is gone
    assert got[0]["title"] == "VALORANT Patch Notes 11.06" and got[0]["snippet"].startswith("Welcome to Patch Notes 11.06")
    assert got[1]["snippet"] == "Every recon lineup on Ascent"
    lite = web.parse_results(LITE_HTML)
    assert lite == [{"title": "Valorant meta tier list", "url": "https://blitz.gg/valorant/meta",
                     "snippet": "The best agents right now"}]


class FakeSite(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        here = f"http://127.0.0.1:{self.server.server_port}/page"  # (every link local: online, the real site got read)
        self._send(RESULTS_HTML.replace("https%3A%2F%2Fplayvalorant.com%2Fen-us%2Fnews%2Fgame-updates%2F"
                                        "valorant-patch-notes-11-06%2F", here).replace("https://www.youtube.com/watch?v=abc", here))

    def do_GET(self):
        self._send("<html><head><script>var x=1</script><style>p{}</style></head><body><nav>Menu Home</nav><main>"
                   "<h1>Patch 11.06</h1><p>Jett: Tailwind dash window reduced.</p>" + "<p>More changes here.</p>" * 30 +
                   "</main><footer>cookies</footer></body></html>")

    def _send(self, text):
        body = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


def test_lookup_reads_the_best_page(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), FakeSite)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(web, "SEARCH", f"http://127.0.0.1:{server.server_port}/html/")
    web._cache.clear()
    text = web.lookup("valorant patch notes")
    assert "1. VALORANT Patch Notes 11.06" in text
    assert "Jett: Tailwind dash window reduced." in text and "var x" not in text and "Menu Home" not in text
    server.shutdown()


def test_what_gets_looked_up_and_reviewed():
    assert router.route("what's the current meta on ascent?").search.startswith("valorant what's the current meta")
    assert router.route("sova lineups for ascent a site").search
    assert router.route("search the web for vct champions results").search == "vct champions results"
    assert not router.route("how do I play jett on ascent?").search      # his notes cover this
    assert not router.route("2 A, one heaven", "valorant").search          # no lookups mid-round
    assert not router.route("vandal pros and cons").search
    r = router.route("why did we lose? we went 7-13 on bind")
    assert r.kind == "review" and "review" in r.tags and "What lost rounds" in r.note
    assert router.route("review my game", pictures=1).kind == "review"     # with a scoreboard screenshot
    assert router.route("what went wrong in my code?").kind != "review"


def test_notes_for_live_callouts_come_first():
    sections = knowledge.load()
    chosen = knowledge.pick(sections, "2 a, one heaven ascent", {"valorant", "live"}, budget=1250)
    assert chosen and chosen[0]["title"] == "Live match coaching style"
    chosen = knowledge.pick(sections, "how do i retake b on bind", {"valorant"}, budget=2500)
    titles = [s["title"] for s in chosen]
    assert "Bind strats" in titles or "Retakes and post-plant" in titles  # about the question, before the basics


def test_voice_shortcut_parsing():
    assert hotkey.parse("ctrl+alt+v") == (0x2 | 0x1, ord("V"))
    assert hotkey.parse("Shift+F9") == (0x4, 0x78)
    assert hotkey.parse("f8") == (0, 0x77)
    for bad in ("v", "ctrl+alt", "ctrl+banana"):
        try:
            hotkey.parse(bad)
            assert False, bad
        except ValueError:
            pass
    assert hotkey.pretty("ctrl+alt+v") == "Ctrl+Alt+V"


def test_brain_looks_it_up_before_answering(monkeypatch):
    import store
    from brain import Brain

    asked = []
    monkeypatch.setattr(web, "lookup", lambda q, **k: asked.append(q) or "1. Patch 11.06 — Jett nerfed (https://x.gg)")

    class Backend:
        def answer(self, system, history, tools, run_tool, on_text=None, stop=None, **kw):
            Backend.seen, Backend.tools = history[-1]["content"], [t["name"] for t in tools]
            on_text("Jett got nerfed this patch, I looked it up.")
            return "Jett got nerfed this patch, I looked it up.", False

    used = []
    store.use_profile(store.profiles()[0])
    b = Brain({"name": "Flip", "roblox_studio": False}, "You are {name}.", "http://127.0.0.1:9/v1")
    b.backend, b.on_tool = Backend(), used.append
    b.chat("metachat", "is jett still meta right now?")
    assert asked and "jett" in asked[0].lower() and used == ["web_search"]
    assert "Looked this up on the web" in Backend.seen and "Jett nerfed" in Backend.seen
    assert "web_search" in Backend.tools


def test_every_reply_has_an_end():
    for msg, mode in [("hi", "auto"), ("what's 59382 × 912?", "auto"), ("write a luau door script", "auto"),
                      ("how do I play jett?", "auto"), ("why did we lose? 6-13", "valorant"), ("hard problem", "think")]:
        assert router.route(msg, mode).max_tokens, msg  # a looping small brain can't write forever
