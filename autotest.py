"""Clicks through the real Flip app like a person would (used by the build on a Windows machine).

Runs when FLIP_AUTOTEST is set to a folder: results.txt and a screenshot per step end up there.
"""

import json
import logging
import os
import time
import traceback
from pathlib import Path

log = logging.getLogger("flip")


class Failed(Exception):
    pass


def run(api):
    out = Path(os.environ["FLIP_AUTOTEST"])
    out.mkdir(parents=True, exist_ok=True)
    results = []
    main = api._main

    def js(expr):
        return main.evaluate_js(expr)

    def call(code):
        """Runs code in the window without waiting for it (clicks, async functions)."""
        main.evaluate_js(f"setTimeout(() => {{ {code}; }}, 0); 1")

    def wait_for(expr, timeout=60, what=""):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if js(expr):
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise Failed(f"timed out waiting for {what or expr}")

    def shot(name):
        try:
            from PIL import ImageGrab

            ImageGrab.grab(all_screens=True).save(out / f"{len(results):02d}-{name}.png")
        except Exception:
            log.exception("screenshot failed")

    def step(name, fn):
        started = time.time()
        try:
            detail = fn() or ""
            results.append({"step": name, "ok": True, "detail": str(detail)[:300], "secs": round(time.time() - started, 1)})
        except Exception as e:
            results.append({"step": name, "ok": False, "detail": f"{e}\n{traceback.format_exc()[-800:]}",
                            "secs": round(time.time() - started, 1)})
        shot(name.replace(" ", "-"))
        (out / "results.json").write_text(json.dumps(results, indent=1))

    def last_reply():
        return js("(() => { const m = [...document.querySelectorAll('.msg.pet')].pop();"
                  " return m ? JSON.stringify({text: m.querySelector('.b').textContent, error: m.classList.contains('error'),"
                  " stopped: !!m.querySelector('.stopped')}) : '{}'; })()")

    def chat(text, timeout=600):
        before = js("document.querySelectorAll('.msg.pet').length")
        call(f"send({json.dumps(text)})")
        wait_for(f"document.querySelectorAll('.msg.pet').length > {before} && busy === false", timeout, "the reply")
        r = json.loads(last_reply())
        if not r.get("text", "").strip() or r.get("error"):
            raise Failed(f"bad reply: {r}")
        return r["text"]

    # ---------------- the steps ----------------

    step("app opens on create account", lambda: wait_for(
        "document.body.classList.contains('auth') && !document.querySelector('#auth-pass2').hidden", 60))

    def create_account():
        call("document.querySelector('#auth-user').value = 'tester'; document.querySelector('#auth-pass').value = 'password1';"
             "document.querySelector('#auth-pass2').value = 'password1'; document.querySelector('#auth-go').click()")
        wait_for("document.body.classList.contains('profiles') && !document.querySelector('#prof-form').hidden", 20)
    step("create account", create_account)

    def create_profile():
        call("document.querySelector('#prof-name').value = 'Sam'; document.querySelector('#prof-create').click()")
        wait_for("!document.body.classList.contains('profiles') && me && me.name === 'Sam'", 20)
        js("muted = true;")  # the build machine has no speakers; the voice gets its own test below
    step("create profile", create_profile)

    step("brain loads", lambda: wait_for("!document.body.classList.contains('setup')", 1800, "the brain")
         or api._engine.status.get("model"))

    def first_chat():
        reply = chat("hi! my main is Jett. reply in one short sentence")
        wait_for("allChats.length >= 1 && document.querySelector('#chat-title').textContent !== 'New chat'", 20,
                 "the chat to show up in the sidebar")
        return f"{reply} | {api._brain.last_stats}"
    step("chat: reply streams in", first_chat)

    step("chat: second message reuses its work", lambda: f"{chat('what agent do I main? one short sentence')} | {api._brain.last_stats}")

    def voice():
        clip = api.say("yo, testing my voice real quick")
        if not clip or len(clip.get("audio", "")) < 10000:
            raise Failed(f"no voice: {clip and clip.get('mime')}")
        return f"{clip['mime']}, {len(clip['audio']) // 1000} kB"
    step("his voice speaks", voice)

    def new_chat():
        call("newChat()")
        wait_for("!document.body.classList.contains('chatting') && document.querySelector('#chat-title').textContent === 'New chat'", 10)
    step("new chat", new_chat)

    def memory():
        call("openMemory()")
        wait_for("document.body.classList.contains('panel-open') && document.querySelector('#memory-panel').offsetParent !== null", 10)
        n = js("document.querySelectorAll('#mem-list .mem').length")
        call("closeAll()")
        return f"{n} memories"
    step("memory panel", memory)

    def settings():
        call("openSettings()")
        wait_for("document.querySelectorAll('#storage-list .st-row').length > 0", 20, "the storage list")
        rows = js("[...document.querySelectorAll('#storage-list .st-row')].map(r => r.textContent).join(' | ')")
        return rows
    step("settings + storage", settings)
    call("closeAll()")

    def sharing():
        r = api.share_sources()
        if "error" in r:
            raise Failed(r["error"])
        src = r["sources"][0]
        started = api.share_start(src["id"], src["title"])
        if "error" in started:
            raise Failed(started["error"])
        call(f"startShare({json.dumps(src)})")
        wait_for("document.body.classList.contains('sharing')", 10)
        reply = chat("what app do you see on my screen? one short sentence")
        call("stopShare()")
        return reply
    step("screen sharing: he sees the screen", sharing)

    def stop_button():
        call("send('count slowly from 1 to 300, one number per line')")
        wait_for("stream && stream.text.length > 3", 300, "him to start writing")
        call("stopReply()")
        wait_for("busy === false", 30, "him to stop")
        r = json.loads(last_reply())
        if not r.get("stopped"):
            raise Failed(f"didn't stop: {r}")
        return r["text"][:60]
    step("stop button", stop_button)

    def fast_mode():
        call("document.querySelector('#fast-btn').click()")
        wait_for("fast === true", 20)
        wait_for("!document.body.classList.contains('setup') && fast === true", 900, "fast mode to load")
        reply = chat("say gg in one word")
        call("document.querySelector('#fast-btn').click()")
        wait_for("fast === false && !document.body.classList.contains('setup')", 900, "smart mode to come back")
        return reply
    step("fast mode", fast_mode)

    def pet():
        api.show_pet()
        time.sleep(8)
        if api._pet is None:
            raise Failed("the pet window didn't open")
    step("desktop pet shows up", pet)
    api.hide_pet()

    def log_out_and_in():
        call("logOut()")
        wait_for("document.body.classList.contains('auth')", 15)
        call("document.querySelector('#auth-user').value = 'tester'; document.querySelector('#auth-pass').value = 'password1';"
             "document.querySelector('#auth-go').click()")
        wait_for("!document.body.classList.contains('auth') && me && me.name === 'Sam'", 20)
        return js("allChats.length") or ""
    step("log out and back in", log_out_and_in)

    ok = all(r["ok"] for r in results)
    lines = [f"{'PASS' if r['ok'] else 'FAIL'} {r['step']} ({r['secs']}s): {r['detail']}" for r in results]
    (out / "results.txt").write_text(("ALL PASSED\n" if ok else "SOME FAILED\n") + "\n".join(lines), encoding="utf-8")
    log.info("Autotest done: %s", "all passed" if ok else "some failed")
    api.quit()
