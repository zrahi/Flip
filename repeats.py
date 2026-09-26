"""Keeps Flip from saying the same thing twice.

Small brains love to copy their own earlier replies, usually reworded a little:
    "WSP? Let's go live. What map are we on? … Just say the map or "call me.""
    "WSP? Let's get real. What map are we on? … Just say the map or "call me"."
Comparing letters misses that, so replies are compared by what they say:
- sentences: a sentence counts as said before when (nearly) the same words are in an earlier reply;
- meaningful words: a reply is a repeat when most of them were all in one earlier reply.
Code blocks and math are left out: a fixed version of a script is supposed to look like the old one.

Watch checks a reply while it's being written; verdict() judges a finished one.
"""

import difflib
import random
import re

STOP = set("""
a an the and or but so if then than that this these those to of in on at by for with from up down out over into
about as is are was were be been being am do does did done have has had having i me my mine you your yours we us
our they them their he him his she her it its what which who whom whose when where why how all any both each few
more most other some such no nor not only own same too very can will just should now would could might must shall
may also there here yeah yes yo ok okay lol im ive id ill youre youve youd youll weve were theyre theyve dont doesnt
didnt cant wont isnt arent wasnt werent thats whats lets gonna wanna gotta get got like really
let know right through feel feeling go going need want tell sure well still even much ayy man bro dude
hows wheres whos whens whys heres theres one good today day time thing things stuff lot cool nice great
""".split())

CODE = re.compile(r"```.*?(?:```|$)", re.S)
MATH = re.compile(r"\$\$.+?\$\$|\\\[.+?\\\]|\\\(.+?\\\)|\$[^$\n]+\$", re.S)
# Where a reply splits into parts that get compared: sentence ends, new lines, dashes and semicolons.
PARTS = re.compile(r"(?<=[.!?…])[\"'”’)\]*_]*\s+|\n+|\s[—–-]+\s|[—–]|;\s")
# Where a sentence ends while it streams in (the dash parts are split later, when it's judged).
END = re.compile(r"[.!?…]+[\"'”’)\]*_]*\s+|\n+")
# A redo that opens by owning up to the note he got ("my bad", "got it, something new:") instead of just answering.
ACK = re.compile(r"^\W*(my bad|my fault|oops|sorry|you'?re right|fair( enough| point)?|noted|understood|got it|gotcha|"
                 r"(ok(ay)?|alright|aight)\W+(here'?s |something |a )*(new|different|fresh))\b|here'?s (something|a) "
                 r"(new|different|fresh)|(not|won'?t|never) (going to |gonna )?repeat|let'?s pivot|"
                 r"(same|that) (thing|answer) (again|twice)", re.I)
# Talk about what the user never sees: his notes, or the note telling him not to repeat himself.
META = re.compile(r"\b(my|your|those|these|the) notes\b|\b(not|won'?t|never) (gonna |going to )?(say|repeat) "
                  r"(that|this|it|myself|what)|\bnot gonna repeat\b", re.I)
# The user asking to hear it again: repeating is the point then.
AGAIN = re.compile(r"\b(again|repeat|one more time|say (that|it) (again|back)|what did you (just )?say|what was that|"
                   r"simpler|rephrase|in other words|explain (it|that|this)|recap|summar|tl;?dr|remind me)\b", re.I)

REDO_NOTE = ("(Hold on: that's basically what you already told me earlier in this chat. Say something new instead: "
             "a different opener, different words and a new point, or ask me one specific thing you haven't asked "
             "yet. Don't apologize or mention this note.)")
SHORT_NOTE = ("(Still the same as before. Reply in one short sentence that answers only my last message, in "
              "different words. Don't apologize or mention this note.)")
ECHO_NOTE = ("(Hold on: that just repeated your instructions and my message back. Answer my message itself now, "
             "like a coach who knows the game. Don't apologize or mention this note.)")
USER_REPEATED = ("(I sent the same message as last time. Don't answer it the same way again: react to me repeating "
                 "it, or take the chat somewhere new.)")
# Last resort when even the redo repeats: short, and never one he already used in this chat.
FALLBACK = {
    "repeated": ["you said that already 😭 what's up for real?", "déjà vu 👀 what do you actually need?",
                 "we're going in circles 😭 hit me with something new", "same message twice, I see you 👀 what's the move?"],
    "casual": ["haha fair 😭", "lowkey same", "real 😭 what's up though?", "haha I'm not going anywhere"],
    "other": ["wait, what do you mean? 👀", "run that back, what exactly do you need?",
              "say that another way? I don't wanna give you the same answer twice", "hmm, what do you want to work on?"],
}


def _stem(w):
    if len(w) > 4 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith(("ed", "ly")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _plain(text):
    return MATH.sub(" ", CODE.sub(" ", text or ""))


def _raw_words(text):
    return re.findall(r"[a-z0-9]+", _plain(text).lower().replace("’", "'").replace("'", ""))


def words(text):
    """The words of a text, lowercase and roughly stemmed ("smokes" → "smoke"), without code or math."""
    return [_stem(w) for w in _raw_words(text)]


def content(text):
    """The meaningful words (no "the", "you're", "gonna"…)."""
    return {_stem(w) for w in _raw_words(text) if w not in STOP and len(w) > 1}


def sentences(text):
    """[(words, is_question)] for each part of a text."""
    out = []
    for part in PARTS.split(_plain(text)):
        w = words(part)
        if w:
            out.append((w, part.rstrip(" \"'”’)]*_").endswith("?")))
    return out


def _covered(a, b):
    """How much of a is in b, counting only runs of 2+ words in the same order."""
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(bl.size for bl in m.get_matching_blocks() if bl.size >= 2) / len(a)


def same(a, b):
    """Two sentences (word lists) that say the same thing."""
    if a == b:
        return True
    if len(a) < 3 or len(b) < 2:
        return False
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.75 or (len(a) >= 4 and _covered(a, b) >= 0.8)


def _real(w):
    """A part worth comparing on its own: has actual letters (not "1." from a list)."""
    return re.search(r"[a-z]{2}", " ".join(w)) is not None


def verdict(reply, earlier):
    """Why this reply repeats one of the earlier ones ("" if it doesn't)."""
    new = sentences(reply)
    total = sum(len(w) for w, _ in new)
    if not total:
        return ""
    old = [s for e in earlier for s in sentences(e)]
    recent_questions = [w for e in earlier[-2:] for w, q in sentences(e) if q]
    repeated = 0
    for w, question in new:
        if len(w) < 3 and not _real(w):
            continue
        if any(same(w, o) for o, _ in old):
            repeated += len(w)
            if question and len(w) >= 3 and any(same(w, q) for q in recent_questions):
                return f"asks again: {' '.join(w)}"
    share = repeated / total
    if repeated >= 6 and share >= 0.4:
        return f"{round(share * 100)}% said before"
    mine = content(reply)
    for e in earlier:
        theirs = content(e)
        if len(mine) >= 6:
            overlap = len(mine & theirs) / len(mine)
            if overlap >= (0.6 if len(mine) < 25 else 0.7) or (share >= 0.3 and overlap >= 0.45):
                return f"{round(overlap * 100)}% the same words"
        elif total <= 12:
            w, ew = words(reply), words(e)
            if w and ew and difflib.SequenceMatcher(None, w, ew, autojunk=False).ratio() >= 0.8:
                return "same short reply"
    return ""


def too_similar(reply, earlier):
    """A stricter check than verdict(), for tests: why the reply is even close to an earlier one ("" if not).
    Same opener, any reused sentence of 4+ words (reworded counts), or half its meaningful words shared."""
    why = verdict(reply, earlier)
    if why:
        return why
    new = sentences(reply)
    if not new:
        return ""
    for e in earlier:
        old = sentences(e)
        if old and _real(new[0][0]) and new[0][0] == old[0][0]:
            return f"same opener: {' '.join(new[0][0])}"
        for w, _ in new:
            if len(w) >= 4 and any(same(w, o) for o, _ in old):
                return f"reused: {' '.join(w)}"
        mine, theirs = content(reply), content(e)
        if len(mine) >= 4 and len(mine & theirs) / len(mine) >= 0.5:
            return f"{round(100 * len(mine & theirs) / len(mine))}% the same words"
    return ""


def asks_again(text):
    return AGAIN.search(text or "") is not None


def same_message(a, b):
    """The user sent (nearly) the same thing twice in a row."""
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return False
    return wa == wb or (len(wa) >= 3 and difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio() >= 0.85)


def dedupe(history):
    """The chat as the brain reads it: replies that repeated an even earlier reply are left out (seeing its
    own repeats teaches a small brain to keep repeating). A message's fate only depends on the messages
    before it, so the brain can keep reusing its work on the chat so far."""
    out, said = [], []
    for m in history:
        if m["role"] == "assistant" and isinstance(m["content"], str) and "```" not in m["content"]:
            if said and verdict(m["content"], said):
                continue
            said.append(m["content"])
        out.append(m)
    return out


def _keep(reply, keep):
    """reply with only the sentences keep(sentence) says yes to (code blocks stay as they are)."""
    pieces = re.split(r"(```.*?(?:```|$))", reply, flags=re.S)
    kept = []
    for i, piece in enumerate(pieces):
        if i % 2:  # a code block
            kept.append(piece)
            continue
        kept += [s for s in re.findall(r"[^.!?…\n]*(?:[.!?…]+[\"'”’)\]*_]*\s*|\n+|$)", piece) if keep(s)]
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


def strip(reply, earlier):
    """The reply without the sentences that were already said."""
    old = [w for e in earlier for w, _ in sentences(e)]

    def new(sentence):
        parts = [w for w, _ in sentences(sentence)]
        n = sum(len(w) for w in parts)
        said = sum(len(w) for w in parts if len(w) >= 3 and any(same(w, o) for o in old))
        return not (n and said * 2 >= n)
    return _keep(reply, new)


def drop_meta(reply):
    """The reply without sentences about his hidden notes or about (not) repeating himself."""
    kept = _keep(reply, lambda s: not META.search(s))
    return kept if words(kept) else reply


def brief(reply, most=22):
    """A mid-round callout: the first sentences, up to about most words (a small brain keeps going and
    reads its notes back: "Lotus, Phoenix, attack A. B is small site…")."""
    total, done = [0], [False]
    kept = _keep(reply, lambda s: not is_callout_list(s))
    reply = kept if words(kept) else reply

    def fits(sentence):
        n = len(_raw_words(sentence))
        if done[0] or (total[0] and (total[0] + n > most or (n and not sentence.strip()))):
            done[0] = True
            return False
        if not sentence.strip() and "\n\n" in sentence:
            done[0] = bool(total[0])  # a new paragraph after the callout: that's where he starts rambling
            return False
        total[0] += n
        if total[0] and re.search(r"\n\s*\n\s*$", sentence):
            done[0] = True
        return True
    return re.sub(r"\s*\n\s*", " ", _keep(reply, fits)).strip() or reply


def echoes(reply, sources):
    """Why the reply is parroting its instructions or the user's message back ("" if it isn't): a small
    brain sometimes answers with "You're talking to Sam (that's the name on their profile). I keep dying…"."""
    new = [w for w, _ in sentences(reply) if len(w) >= 5]
    if not new:
        return ""
    old = [w for src in sources for w, _ in sentences(src) if len(w) >= 5]
    copied = [w for w in new if any(same(w, o) for o in old)]
    # (one borrowed phrase like "let me use the math tool" is fine: parroting is most of the reply)
    if len(copied) >= 2 and len(copied) * 2 >= len(new) or (len(new) == 1 and copied and len(copied[0]) >= 8):
        return f"echoes its instructions: {' '.join(copied[0])[:60]}"
    return ""


OPENER = re.compile(r"^\s*(ay+|ayo+|yo+|aye+|okay|ok|got it|bet|welp)\b(?:,?\s*(?:sam|bro|man|dude)\b)?[\s,!.…—–-]*", re.I)


def fresh_opener(reply, earlier):
    """reply without its "Ayy —" when one of his last replies opened the same way."""
    m = OPENER.match(reply)
    if not m or not reply[m.end():].strip():
        return reply
    word = m.group(1).lower().rstrip("y").rstrip("o")
    for e in earlier[-3:]:
        n = OPENER.match(e or "")
        if n and n.group(1).lower().rstrip("y").rstrip("o") == word:
            rest = reply[m.end():]
            return rest[:1].upper() + rest[1:]
    return reply


PREAMBLE = re.compile(r"^\W*(?:ay+,?\s*)?(?:(?:sam|bro|man)\W+)?(you'?re (?:on the right track|right on track|in the right "
                      r"spot|asking about)|let'?s (?:break (?:it|this) down|get (?:into it|real|started)|go straight|take it)|"
                      r"got (?:it|you)|good question|great question|i see you'?re|okay|alright)\b[^.!?\n—–]{0,90}[.!?—–-]*\s*",
                      re.I)


def drop_preamble(reply):
    """The answer without an intro sentence ("You're on the right track with that retake plan."), if the
    rest still says something."""
    out = reply
    for _ in range(2):  # "Ayy, Sam, you're asking about retakes? Let's break this down like a pro."
        m = PREAMBLE.match(out)
        if not m:
            break
        rest = out[m.end():].lstrip(" —–-:\n")
        if len(words(rest)) < 6:
            break
        out = rest[:1].upper() + rest[1:]
    return out


def is_callout_list(sentence):
    """"A Main, A Ramps, B Alley, B Back, B Link": reading the map's callout list instead of making a call."""
    items = [x.strip() for x in re.split(r",|/|&|\band\b", sentence) if x.strip()]
    return len(items) >= 4 and sum(len(x.split()) <= 3 for x in items) >= len(items) - 1 and not re.search(
        r"\b(smoke|flash|hold|push|fall|retake|save|rotate|stack|trade|play|wait|don'?t|go|hit|clear|watch)\b",
        items[0], re.I)


def whole_sentences(reply):
    """reply without an unfinished sentence at the end (if that leaves something)."""
    if re.search(r"[.!?…)\]*_\"'”’\U0001F300-\U0001FAFF]\s*$", reply) or "```" in reply:
        return reply
    ends = [m.end() for m in END.finditer(reply)]
    return reply[:ends[-1]].strip() if ends and words(reply[:ends[-1]]) else reply


def fallback(user_repeated, earlier, casual=False):
    lines = FALLBACK["casual" if casual else "repeated" if user_repeated else "other"]
    fresh = [l for l in lines if not any(same(words(l), words(e)) or words(l) == words(e) for e in earlier)]
    return random.choice(fresh or lines)


def _cut(text):
    """Where the first finished sentence ends in text that's still streaming in (0 = not yet)."""
    for m in END.finditer(text):
        if re.search(r"[^\W\d_]{2}", text[:m.start()]):  # "1." at the start of a list isn't a sentence
            return m.end()
    if len(text) > 160:  # one giant sentence: judge it by its start
        i = text.rfind(" ", 0, 160)
        return i + 1 if i > 0 else len(text)
    return 0


class Watch:
    """Watches a reply while it's written and passes on what's fine to show.

    The first sentence is held back until it's complete: if it goes like an earlier reply did, the reply is
    stopped right there, before anything is shown or said, so it can be redone. In voice calls (every=True)
    every sentence is checked, since he can't take back what he said: ones he already said are skipped, and
    if he keeps at it he's stopped. It's also the stop signal for the brain (is_set)."""

    def __init__(self, earlier, emit, every=False, redo=False, strict=False):
        self._old = [s for e in earlier for s in sentences(e)]
        self._contents = [content(e) for e in earlier]
        self._strict = strict
        self._openers = [ss[0][0] for ss in (sentences(e) for e in earlier[-3:]) if ss]
        self._emit = emit
        self._redo = redo
        self._held = ""
        self._lead = ""       # bits with no words (an emoji line) waiting for the first real sentence
        self._started = not self._old and not redo  # nothing to compare or drop: nothing to hold back
        self._every = every and bool(self._old)
        self._skipped = 0
        self.shown = ""
        self.stopped = False
        self.why = ""

    def is_set(self):
        return self.stopped

    def text(self):
        return self.shown.strip()

    def feed(self, piece):
        if self.stopped:
            return
        if self._started and not self._every:
            self._show(piece)
            return
        self._held += piece
        while not self.stopped:
            cut = _cut(self._held)
            if cut and self._strict and not self._started:
                # the same message again: judge the first two sentences together ("just got a patch update" +
                # "want to see the new meta?" is a rehash neither one shows alone)
                second = _cut(self._held[cut:])
                if not second:
                    return
                cut += second
            if not cut:
                return
            part, self._held = self._held[:cut], self._held[cut:]
            self._judge(part)
            if self._started and not self._every:
                rest, self._held = self._held, ""
                if rest:
                    self._show(rest)
                return

    def finish(self):
        """The reply is done: whatever's still held back gets the same checks."""
        if not self.stopped and self._held:
            rest, self._held = self._held, ""
            self._judge(rest)
        if not self.stopped and self._lead:
            self._show(self._lead)
            self._lead = ""

    def flush(self):
        """The stop button: what he was in the middle of saying still goes out, unchecked."""
        rest, self._lead, self._held = self._lead + self._held, "", ""
        if rest and not self.stopped:
            self._show(rest)

    def _show(self, text):
        self.shown += text
        self._emit(text)

    def _stop(self, why):
        self.stopped, self.why = True, why

    def _judge(self, part):
        if "```" in part:  # code from here on: nothing to compare
            self._started, self._every = True, False
            self._show(self._lead + part)
            self._lead = ""
            return
        parts = sentences(part)
        if parts and META.search(part):
            return  # about his notes or about not repeating: the user never sees those, so it's just noise
        if not parts:
            if self._started:
                self._show(part)
            else:
                self._lead += part
            return
        if not self._started:
            if self._redo and ACK.search(part.strip()) and len(parts[0][0]) <= 8:
                return  # "my bad, here's something new:" — just skip to the answer
            first = parts[0][0]
            if _real(first) and first in self._openers:
                return self._stop(f"opens like before: {' '.join(first)}")
            why = ""
            for w, _ in parts:
                if len(w) >= 3 and any(same(w, o) for o, _ in self._old):
                    why = f"said before: {' '.join(w)}"
                    break
            # reworded: "I'm in coach mode now, ready to go" → "I'm in the right mode now, ready for that coach session"
            mine = content(part)
            least, share = (4, 0.5) if self._strict else (5, 0.6)
            if not why and len(mine) >= least and any(len(mine & c) / len(mine) >= share for c in self._contents):
                why = f"same words as before: {part.strip()[:60]}"
            if why and self._every and not self._strict:
                # a new question in a call: a new answer can share words with the last one ("explain Sova" after
                # "who should I play on Ascent?"), and saying nothing is the worst answer: skip just that sentence
                self._skipped += 1
                self._lead = ""
                if self._skipped >= 2:
                    return self._stop("kept repeating: " + why)
                return
            if why:
                return self._stop(why)
            self._started = True
            self._show(self._lead + part)
            self._lead = ""
            return
        n = sum(len(w) for w, _ in parts)
        said = sum(len(w) for w, _ in parts if len(w) >= 3 and any(same(w, o) for o, _ in self._old))
        if said * 2 >= n:
            self._skipped += 1
            if self._skipped >= 2:
                self._stop("kept repeating")
            return
        self._show(part)
