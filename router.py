"""Decides how Flip handles each message, without an extra AI call: what it's about (Valorant, math,
code…), which know-how and tools come along, and how long and in what style he answers.

Modes: auto (Flip decides), fast, think, math, valorant, code. A mode is a push in one direction;
auto still picks the right tools.
"""

import re

MODES = ("auto", "fast", "think", "math", "valorant", "code")

AGENTS = ["jett", "reyna", "raze", "phoenix", "yoru", "neon", "iso", "waylay", "sova", "breach", "skye", "kayo",
          "kay/o", "fade", "gekko", "tejo", "brimstone", "brim", "omen", "viper", "astra", "harbor", "clove", "sage",
          "cypher", "killjoy", "chamber", "deadlock", "vyse", "veto"]
MAPS = ["ascent", "bind", "haven", "split", "lotus", "sunset", "icebox", "breeze", "pearl", "fracture", "abyss",
        "corrode"]
VAL_WORDS = ["valorant", "valo", "spike", "planted", "defuse", "defusing", "eco round", "anti eco", "anti-eco",
             "force buy", "full buy", "bonus round", "vandal", "phantom", "operator", "sheriff", "spectre", "odin",
             "judge", "marshal", "outlaw", "ult", "ults", "retake", "post plant", "post-plant", "lurk", "entry",
             "duelist", "initiator", "controller", "sentinel", "radiant", "immortal", "ascendant", "diamond",
             "platinum", "ranked", "rr", "credits", "clutch", "callout", "callouts", "crosshair", "heaven", "hookah",
             "a site", "b site", "c site", "a main", "b main", "mid", "rotate", "stack", "flank", "last guy",
             "buy or save", "save or buy", "eco", "force", "one tap", "peek", "peeking", "util", "utility"]
LIVE_WORDS = ["planted", "flank", "flanking", "last guy", "last one", "rotate", "rotating", "push", "pushing",
              "they're", "theyre", "enemy", "enemies", "we planted", "spike down", "heard", "saw", "spotted", "lit",
              "one shot", "tagged", "attack", "attacking", "defense", "defending", "credits", "save or buy",
              "buy or save", "what now", "what do i do", "help", "going", "left"]
MATH_WORDS = ["solve", "equation", "simplify", "factor", "expand", "derivative", "differentiate", "integral",
              "integrate", "limit", "probability", "percent", "percentage", "fraction", "ratio", "sqrt", "square root",
              "cube root", "average", "mean", "median", "mode", "standard deviation", "variance", "area",
              "perimeter", "volume", "circumference", "hypotenuse", "pythagoras", "triangle", "radius", "diameter",
              "angle", "sin", "cos", "tan", "log", "exponent", "polynomial", "quadratic", "inequality", "slope",
              "gradient", "intercept", "function", "sequence", "series", "arithmetic", "geometric", "calculate",
              "calculator", "how much is", "what is the value", "math", "maths", "homework", "algebra", "geometry",
              "trigonometry", "calculus", "statistics", "interest", "discount", "profit"]
CODE_WORDS = ["code", "script", "function", "bug", "error", "traceback", "exception", "python", "javascript", "js",
              "typescript", "ts", "java", "c#", "csharp", "c++", "cpp", "html", "css", "json", "powershell", "bash",
              "shell", "regex", "api", "class", "compile", "refactor", "debug", "syntax", "variable", "loop",
              "array", "import", "npm", "pip", "sql", "react", "node", "program", "programming", "luau", "lua"]
ROBLOX_WORDS = ["roblox", "luau", "studio", "remoteevent", "remotefunction", "remote event", "remote function",
                "datastore", "data store", "leaderstats", "humanoid", "tweenservice", "marketplaceservice",
                "gamepass", "game pass", "developer product", "pathfindingservice", "replicatedstorage",
                "serverscriptservice", "localscript", "modulescript", "screengui", "obby", "tycoon", "exploiter"]
CHEAT = re.compile(r"\b(hack|hacks|hacked|cheat|cheats|aimbot|aim bot|wall ?hack|wallhacks|triggerbot|trigger bot|esp|"
                   r"injector|executor|exploit|exploits|bypass(ing)? (the )?anti.?cheat|vanguard bypass|spoofer|"
                   r"steal (an |his |her |their |someone'?s )?account|account stealer|phish|phishing|keylogger|"
                   r"malware|ransomware|rat\b|ddos|booter|crack(ed)? (the )?(game|license))\b", re.I)
CHEAT_ASK = re.compile(r"\b(make|give|write|code|create|get|download|send|build|find|use|install|need|want|how (do|can|to))\b", re.I)
CHEAT_OK = re.compile(r"\b(stop|prevent|detect|anti|protect|against|secure|patch|report|ban|block|defend|how do (they|people))\b", re.I)


def _has(words, text):
    return any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text) for w in words)


def looks_like_math(text):
    t = text.lower()
    if re.search(r"\b(won|lost|win|lose|score|scoreline|rounds?|kda|k/d|rank|elo|rr|ping|fps|hz|patch|version|v\d)\b", t) \
            and not re.search(r"\b(solve|calculate|equation|percent|probability)\b", t):
        return False
    if re.search(r"\d\s*[-+*/x×÷^%]\s*\(?\d", t) or re.search(r"\d\s*%|\d\s*\^|√|π|\b[a-z]\s*\^\s*\d|\d[a-z]\s*[-+=]", t):
        return True
    if re.search(r"[a-z0-9)]\s*=\s*[-a-z0-9(]", t) and re.search(r"\d", t) and len(t) < 300:
        return True
    return _has(MATH_WORDS, t) and bool(re.search(r"\d", t))


def is_valorant(text):
    t = text.lower()
    return (_has(AGENTS + MAPS + VAL_WORDS + ["op", "opper", "oper"], t) or bool(POSITION.search(t))
            or bool(re.search(r"\b[1-5]\s*(v|vs)\s*[1-5]\b", t)))


POSITION = re.compile(r"\b(one|two|three|four|five|\d)\s+(a|b|c|mid|heaven|main|site|long|short|link|market|hookah|"
                      r"tree|garden|elbow|window|ramps|rafters|lobby|spawn|cat|catwalk|showers|hell|top|bottom)\b")
STRONG_LIVE = re.compile(r"\b\d\s*(v|vs)\s*\d\b|\bplanted\b|\bspike (down|planted)\b|\blast (guy|one|enemy)\b|"
                         r"\bflank(ing|ed)?\b|\b\d(\.\d)?\s*k\b|\b\d{3,4}\s*(credits|creds|cred)\b|\bdefusing\b|"
                         r"\b(keeps?|they'?re|enemy|enemies) (push|pushing|rushing|peeking|holding)")
QUESTION = re.compile(r"^(how|why|explain|what|whats|what's|which|where|when|who|any|is there|best|good|can you|"
                      r"could you|tell me|teach|give me|tips|help me understand|is it|should i learn|compare)\b")


def is_live(text, recent_valorant):
    """A quick mid-match update like "2 A, one heaven" or "Lotus, Phoenix, attack, 3.4k"."""
    t = text.lower().strip()
    words = len(t.split())
    if words > 16 or (QUESTION.search(t) and words > 4):
        return False
    strong = bool(STRONG_LIVE.search(t) or POSITION.search(t))
    setup = _has(MAPS, t) + _has(AGENTS, t) + bool(re.search(r"\b(atk|def|attack|defense|defence|attacking|defending)\b", t))
    return (strong and words <= 12) or setup >= 2 or (recent_valorant and words <= 8 and (strong or _has(LIVE_WORDS, t)))


class Route:
    def __init__(self):
        self.kind = "chat"           # chat | valorant | live | math | code | roblox | refuse
        self.tags = set()            # knowledge tags (*valorant, *live, *roblox)
        self.math_tool = False
        self.note = ""               # how to answer, added next to the message
        self.max_tokens = None
        self.temperature = 0.7
        self.think = False
        self.status = ""             # what the window shows while he works

    def __repr__(self):
        return f"Route({self.kind}, tags={sorted(self.tags)}, math={self.math_tool}, max={self.max_tokens}, think={self.think})"


def route(text, mode="auto", recent="", voice=False):
    """recent: the last few messages of the chat (for follow-ups like "and B?")."""
    mode = mode if mode in MODES else "auto"
    t = text.lower()
    r = Route()
    recent_val = is_valorant(recent)
    notes = []

    if CHEAT.search(t) and CHEAT_ASK.search(t) and not CHEAT_OK.search(t):
        r.kind = "refuse"
        r.note = ("(This asks for cheats/hacks/account theft/malware. Decline in one short sentence, no lecture, "
                  "then offer a legit alternative: e.g. building that mechanic in their own game, anti-cheat, "
                  "or getting better legitimately.)")
        r.max_tokens = 120
        return r

    val = mode == "valorant" or is_valorant(t) or (recent_val and len(t.split()) <= 12)
    math_q = mode == "math" or looks_like_math(text)
    roblox = _has(ROBLOX_WORDS, t) or (_has(ROBLOX_WORDS, recent.lower()) and _has(CODE_WORDS, t))
    code = mode == "code" or roblox or "```" in text or _has(CODE_WORDS, t)

    if val and not (math_q and mode != "valorant" and not is_valorant(t)):
        r.tags.add("valorant")
        r.kind = "valorant"
        if is_live(text, recent_val or mode == "valorant") and not math_q:
            r.kind = "live"
            r.tags.add("live")
            r.max_tokens = 70
            r.temperature = 0.5
            notes.append("(Live match: reply with 1-3 short imperative callouts, under 20 words total, using the "
                         "match state and the map's real callouts. No greetings, emojis or generic advice.)")
        else:
            notes.append("(Valorant: answer like a sharp coach who's also your duo: specific positions, util, "
                         "timings and the why. Short unless they ask for detail. Don't invent abilities, callouts or "
                         "patch numbers that aren't in your notes; say if you're unsure.)")
    if math_q:
        r.math_tool = True
        if r.kind not in ("valorant", "live"):
            r.kind = "math"
        r.temperature = 0.3
        r.status = "calculating…"
        notes.append("(Math: use the math tool for every calculation, even easy ones, then check the result makes "
                     "sense. Show short clear steps unless I said to just answer. Write math with LaTeX: $...$ inline, "
                     "$$...$$ for equations on their own line.)")
    if code and r.kind == "chat":
        r.kind = "roblox" if roblox else "code"
        r.temperature = 0.3
        notes.append("(Coding: be precise and complete. Put code in fenced blocks with the language. Explain the fix "
                     "briefly; for Roblox, validate on the server and say where each script goes.)")
    if roblox:
        r.tags.add("roblox")

    if mode == "think":
        r.think = True
        r.math_tool = True
        r.status = "thinking it through…"
        r.temperature = 0.4
        notes.append("(Think mode: first work it out privately inside <think> </think> tags (the user won't see "
                     "that), check your work, then write the final answer.)")
    elif mode == "fast" and r.kind != "live":
        r.max_tokens = 300
        notes.append("(Quick mode: keep it short, 1-2 sentences unless I ask for more.)")
    if voice and r.kind != "live":
        r.max_tokens = min(r.max_tokens or 160, 160)
    r.note = "\n\n".join(notes)
    return r


# ---------- live match state ----------

SIDE = {"atk": "attack", "attack": "attack", "attacking": "attack", "t side": "attack", "def": "defense",
        "defense": "defense", "defence": "defense", "defending": "defense", "ct": "defense"}
NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def update_match(state, text):
    """Keeps track of what they've said about the current match (map, side, agent, money, spike, players).
    Returns the new state dict."""
    s = dict(state or {})
    t = text.lower()
    for m in MAPS:
        if re.search(rf"\b{m}\b", t):
            if s.get("map") and s["map"] != m.title():  # a new map means a new match
                s = {}
            s["map"] = m.title()
    for a in AGENTS:
        if re.search(rf"(?<![a-z]){re.escape(a)}(?![a-z])", t) and re.search(rf"\b(i'?m|im|playing|as|me)\b[^.]*{re.escape(a)}|^{re.escape(a)}\b|, {re.escape(a)}\b", t):
            s["agent"] = a.title().replace("Kay/O", "KAY/O")
            break
    for k, v in SIDE.items():
        if re.search(rf"\b{k}\b", t):
            s["side"] = v
    m = re.search(r"\b(\d(?:\.\d)?)\s*k\b", t) or re.search(r"\b(\d{3,4})\s*(?:credits|creds|cred)\b", t)
    if m:
        v = m.group(1)
        s["credits"] = int(float(v) * 1000) if "." in v or len(v) == 1 else int(v)
    m = re.search(r"\b(\d)\s*(?:v|vs)\s*(\d)\b", t)
    if m:
        s["players"] = f"{m.group(1)}v{m.group(2)}"
    if re.search(r"\blast (guy|one|enemy)\b", t):
        s["players"] = s.get("players", "?v1").split("v")[0] + "v1" if "v" in s.get("players", "") else "?v1"
    m = re.search(r"\b(?:we )?planted(?: on)? ?(a|b|c)?\b|\bspike (?:down|planted)(?: on)? ?(a|b|c)?\b", t)
    if m:
        site = (m.group(1) or m.group(2) or "").upper()
        s["spike"] = f"planted {site}".strip()
    if re.search(r"\bdefus(ed|ing)\b", t):
        s["spike"] = "defusing" if "defusing" in t else "defused"
    enemies = re.findall(r"\b(one|two|three|four|five|\d)\s+(a|b|c|mid|heaven|main|site|long|short|link|market|"
                         r"hookah|tree|garden|elbow|window|ramps|rafters|lobby|spawn)\b", t)
    if enemies:
        s["enemies"] = ", ".join(f"{NUM.get(n, n)} {w.upper() if len(w) == 1 else w}" for n, w in enemies)
    if re.search(r"\b(new round|next round|round over|we won|we lost|won the round|lost the round)\b", t):
        for k in ("spike", "players", "enemies"):
            s.pop(k, None)
    return s


def describe_match(s):
    if not s:
        return ""
    parts = [f"{k}: {v}" for k, v in s.items() if v not in (None, "")]
    return "(Match state so far — " + "; ".join(parts) + ".)"
