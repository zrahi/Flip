import repeats
import router

# Real replies from a chat where he kept saying the same thing (screenshots from the user).
S1a = ("WSP? Let's go live.\n\nWhat map are we on?\nI'll tell you the exact spot, util timing + why — no fluff. "
       "You got this.\n\n*(Just say the map or \"call me.\")*")
S1b = ("WSP? Let's get real — you're in the right headspace.\n\nWhat map are we on?\nI'll give you *exactly* where "
       "to stand, when to swing and why. No fluff.\n\n*(Just say the map or \"call me\".)*")
S2a = ("You're on point — Yoru's all about flash + smokes. Set up early, trade in angles, stay high, peek wide.\n\n"
       "Let me know the map and I'll call you live. 🎯")
S2b = ("You're in the right headspace — Yoru's about flash + smoke. Set up smokes early, trade where you're in angle, "
       "stay high, peek wide.\n\nLet me know the map — I'll call you live when you're ready. 🎯")


def feed(watch, pieces):
    for p in pieces:
        watch.feed(p)
    watch.finish()
    return watch


def test_catches_the_reworded_repeats_from_the_screenshots():
    assert repeats.verdict(S1b, [S1a])
    assert repeats.verdict(S2b, [S2a])
    assert repeats.verdict(S2b, [S1a, S1b, S2a])
    assert repeats.verdict("What map are we on? Tell me and we cook.", [S1a])  # the same question again
    assert repeats.verdict("gg", ["gg"])


def test_different_replies_are_fine():
    pairs = [
        ("Smoke Heaven and Tree, flash A main, entry behind the flash and plant default.",
         "Smoke Market and Stairs, flash B main, clear Boathouse and Lane, then plant safe."),
        ("Jett's dash is Tailwind: press it, then dash within the window.",
         "Save this round. Buy Sheriffs next round only if the team forces with you."),
        ("haha fair, what are you playing tonight?", "gg! that clutch was crazy, how many rounds did you win?"),
        ("x = 4, because 2x = 8.", "x = 3 or x = 2, it factors as (x-2)(x-3)."),
        (S1a, "Yoru on Ascent? Fakeout into A main, then Gatecrash behind them while they turn."),
        (S2a, "Nah you're good, one bad round doesn't mean anything. Reset and play your first contact slower."),
    ]
    for old, new in pairs:
        assert not repeats.verdict(new, [old]), (new, old)


def test_code_is_not_compared():
    old = "Here's the fixed door script:\n```lua Door.lua\nlocal door = script.Parent\nprint(1)\n```"
    new = "Here's the door script with a slower tween:\n```lua Door.lua\nlocal door = script.Parent\nprint(2)\n```"
    assert not repeats.verdict(new, [old])


def test_watch_stops_a_repeat_before_any_of_it_shows():
    shown = []
    w = feed(repeats.Watch([S1a], shown.append), ["WSP", "? ", "Let's ", "get ", "real ", "— you're"])
    assert w.stopped and shown == [] and "opens like before" in w.why
    shown = []
    w = feed(repeats.Watch([S2a], shown.append), ["You're ", "in the right headspace ", "— Yoru's ",
                                                  "about flash + smoke. ", "Set up"])
    assert w.stopped and shown == []


def test_watch_lets_new_replies_through_word_by_word():
    shown = []
    w = feed(repeats.Watch([S1a], shown.append), ["Bet", ", Jett ", "on Ascent. ", "Dash ", "in ", "after ", "the flash."])
    assert not w.stopped and "".join(shown) == "Bet, Jett on Ascent. Dash in after the flash." == w.text()
    assert shown[-1] == "the flash."  # after the first sentence, words go out as they come
    shown = []
    w = feed(repeats.Watch([], shown.append), ["no ", "earlier ", "replies"])
    assert shown == ["no ", "earlier ", "replies"]  # nothing to compare with: nothing held back


def test_voice_skips_what_he_already_said():
    shown = []
    w = feed(repeats.Watch([S2a], shown.append, every=True),
             ["Nice, Viper on Lotus. ", "Stay high, peek wide. ", "Wall off A main before the hit."])
    assert "".join(shown) == "Nice, Viper on Lotus. Wall off A main before the hit."
    shown = []
    w = feed(repeats.Watch([S2a], shown.append, every=True),
             ["Okay new idea. ", "Set up early, trade in angles. ", "Let me know the map and I'll call you live. ", "Bye."])
    assert w.stopped and "".join(shown) == "Okay new idea. "  # kept going: cut off


def test_redo_skips_owning_up_to_the_note():
    shown = []
    feed(repeats.Watch([S1a], shown.append, redo=True), ["My bad! ", "Jett ", "wants ", "the dash ready."])
    assert "".join(shown) == "Jett wants the dash ready."


def test_stop_button_shows_what_was_held():
    shown = []
    w = repeats.Watch([S1a], shown.append)
    w.feed("one two ")
    w.flush()
    assert "".join(shown) == "one two "


def test_brain_never_sees_its_old_repeats():
    h = [{"role": "user", "content": "wsp coach"}, {"role": "assistant", "content": S1a},
         {"role": "user", "content": "wsp coach"}, {"role": "assistant", "content": S1b},
         {"role": "user", "content": "yoru"}, {"role": "assistant", "content": S2a},
         {"role": "user", "content": "I do hear a coach."}, {"role": "assistant", "content": S2b}]
    kept = repeats.dedupe(h)
    assert [m["content"] for m in kept if m["role"] == "assistant"] == [S1a, S2a]
    assert [m["content"] for m in kept if m["role"] == "user"] == ["wsp coach", "wsp coach", "yoru", "I do hear a coach."]
    assert repeats.dedupe(kept) == kept  # stable: the same chat always reads the same (the brain's cache stays good)


def test_user_repeating_and_asking_again():
    assert repeats.same_message("wsp coach", "Wsp coach!")
    assert not repeats.same_message("wsp coach", "coach me on jett")
    assert repeats.asks_again("say that again?") and repeats.asks_again("explain it simpler")
    assert not repeats.asks_again("how do I hold B on Bind")


def test_strip_and_fallback():
    assert repeats.strip("Fresh idea: play Viper. Stay high, peek wide.", [S2a]) == "Fresh idea: play Viper."
    used = "you said that already 😭 what's up for real?"
    for _ in range(20):
        assert repeats.fallback(True, [used]) != used
    assert repeats.fallback(False, []) in repeats.FALLBACK["other"]


def test_small_talk_gets_no_coaching_pitch():
    for msg in ("wsp coach", "yo bro", "lol ok", "hey flip!", "thanks man", "WSP"):
        r = router.route(msg, "valorant")
        assert r.kind == "chat" and "small talk" in r.note, msg
    assert router.route("yo what's the best agent for ascent?", "auto").kind == "valorant"
    assert router.route("coach me on jett", "auto").kind == "valorant"


def test_the_builds_stricter_check():
    assert repeats.too_similar(S1b, [S1a]) and repeats.too_similar(S2b, [S2a])
    assert repeats.too_similar("WSP? Totally different stuff about Viper walls today.", [S1a])  # same opener
    assert repeats.too_similar("Honestly though, set up early, trade in angles and swing.", [S2a])  # reused line
    assert not repeats.too_similar("Nah you're good, reset and play your first contact slower.", [S2a])
    assert not repeats.too_similar("Viper on Lotus? Wall off A main, orb Tree.", [S1a, S2a])


def test_redo_drops_talk_about_not_repeating():
    shown = []
    feed(repeats.Watch([S1a], shown.append, redo=True),
         ["Ayy, I'm not going to repeat myself — but let's pivot. ", "Rankedmeta has ", "Clove on top right now."])
    assert "".join(shown) == "Rankedmeta has Clove on top right now."


def test_a_real_answer_beats_a_canned_line(monkeypatch):
    import store
    from brain import Brain

    first = "Jett's kit: Cloudburst smokes, Updraft goes up, Tailwind dashes. Jett is all about entry and dash timing."
    close = "You main Jett, so Cloudburst, Updraft and Tailwind are your kit. Entry with the dash."

    class Backend:
        calls = 0

        def answer(self, system, history, tools, run_tool, on_text=None, stop=None, **kw):
            Backend.calls += 1
            text = first if Backend.calls == 1 else close
            on_text(text)
            return text, False

    if store.account is None:
        store.use_account(store.create_account("canned", "password1"))
    store.use_profile(store.profiles()[0] if store.profiles() else store.create_profile("Sam"))
    b = Brain({"name": "Flip", "roblox_studio": False}, "You are {name}.", "http://127.0.0.1:9/v1")
    b.backend = Backend()
    b.chat("mainchat", "i main jett, what's her kit?")
    reply, _, _ = b.chat("mainchat", "what agent do I main? one short sentence")
    assert reply == close  # overlaps his last reply, but it answers: no "say that another way?"


def test_redo_with_nothing_to_compare_still_drops_the_acknowledgement():
    shown = []
    feed(repeats.Watch([], shown.append, redo=True), ["My bad, ", "not gonna repeat that. ", "You main Jett."])
    assert "".join(shown) == "You main Jett."


def test_no_talk_about_notes_or_not_repeating():
    r = ("Ayy, those notes were solid. Yoru's Fakeout sells a flank. I'm not gonna say that again, "
         "so try Gatecrash behind them. Check the patch notes too.")
    assert repeats.drop_meta(r) == ("Yoru's Fakeout sells a flank. Check the patch notes too.")
    assert repeats.drop_meta("the notes") == "the notes"  # never empties a reply
    shown = []
    feed(repeats.Watch([S1a], shown.append, every=True), ["Nice. ", "Your notes say Jett. ", "Dash in late."])
    assert "".join(shown) == "Nice. Dash in late."


def test_tool_loops_end_with_an_answer():
    import types

    from brain import MAX_TOOL_STEPS, LocalBackend

    b = LocalBackend.__new__(LocalBackend)
    b.model, b.context = "x", 8192
    asked = []

    class Stream(list):
        def close(self):
            pass

    def create(**kw):  # a brain that calls the calculator whenever it's allowed to
        asked.append(bool(kw.get("tools")))
        if kw.get("tools"):
            call = types.SimpleNamespace(index=0, id="c", function=types.SimpleNamespace(name="math", arguments="{}"))
            delta = types.SimpleNamespace(content=None, tool_calls=[call])
        else:
            delta = types.SimpleNamespace(content="it's 2", tool_calls=None)
        return Stream([types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])])

    b.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    tool = {"name": "math", "description": "calc", "schema": {"type": "object", "properties": {}}}
    reply, stopped = b.answer("sys", [{"role": "user", "content": "hi"}], [tool], lambda name, args: "x" * 3000)
    assert reply == "it's 2" and not stopped
    assert asked[-1] is False and len(asked) < MAX_TOOL_STEPS  # stopped offering tools before the chat overflowed


def test_reworded_first_sentence_in_a_call_is_caught_before_it_is_said():
    before = "I'm in coach mode now—ready to go into the game. Let's get that bot frag thing fixed up for you."
    shown = []
    w = feed(repeats.Watch([before], shown.append, every=True),
             ["I'm in the right mode now—ready for that coach session. ", "Let's get started!"])
    assert w.stopped and shown == []  # (from a real voice call in the Windows build)


def test_live_callouts_stay_short():
    r = ("Hold tree. Smoke hut. Flash off contact. Clear root. Drop. Play crossfire. Don't give 1v1.\n\n"
         "Lotus, Phoenix — attack A. B is small site. Rotate doors loud. Watch")  # (from the Windows build)
    assert repeats.brief(r) == "Hold tree. Smoke hut. Flash off contact. Clear root. Drop. Play crossfire. Don't give 1v1."
    assert len(repeats.words(repeats.brief(r))) <= 22
    assert repeats.brief("Hold tree.") == "Hold tree."
    long = "Two on A, one heaven, so stack B with the whole team and hit fast before they rotate through mid and doors."
    assert repeats.brief(long) == long  # one sentence always stays


def test_a_reply_cut_by_its_limit_ends_on_a_whole_sentence():
    assert repeats.whole_sentences("Nice. Stay high, peek wide. Then when they") == "Nice. Stay high, peek wide."
    assert repeats.whole_sentences("All good 🔥") == "All good 🔥"
    assert repeats.whole_sentences("no end at all") == "no end at all"


def test_filler_words_dont_make_a_repeat():
    said = ["Got your map? Just wait for that first move. What do you need right now? Let me know what's on your mind."]
    assert not repeats.too_similar("Bet, which agent tonight? I'll call the first fight with you.", said)


def test_just_chatting_in_a_valorant_chat_gets_no_strats():
    r = router.route("beforre u get bored or before i get bored", "valorant")  # (from the user's screenshot)
    assert "doesn't mention the game" in r.note and "Valorant: help with exactly this" not in r.note
    r = router.route("how should we hit A on Ascent?", "valorant")
    assert "Valorant: help with exactly this" in r.note
