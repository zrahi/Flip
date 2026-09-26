"""Decides how Flip handles each message, without an extra AI call: what it's about (Valorant, math,
code…), which know-how and tools come along, and how long and in what style he answers.

Modes: auto (Flip decides), fast, think, math, valorant, code. A mode is a push in one direction;
auto still picks the right tools.
"""

import re

MODES = ("auto", "fast", "think", "math", "valorant", "code", "image", "video")

AGENTS = ["jett", "reyna", "raze", "phoenix", "yoru", "neon", "iso", "waylay", "sova", "breach", "skye", "kayo",
          "kay/o", "fade", "gekko", "tejo", "brimstone", "brim", "omen", "viper", "astra", "harbor", "clove", "sage",
          "cypher", "killjoy", "chamber", "deadlock", "vyse", "veto", "vip", "kj", "cyph", "chamb", "reyn"]
MAPS = ["ascent", "bind", "haven", "split", "lotus", "sunset", "icebox", "breeze", "pearl", "fracture", "abyss",
        "corrode"]
VAL_WORDS = ["valorant", "valo", "spike", "planted", "defuse", "defusing", "eco round", "anti eco", "anti-eco",
             "force buy", "full buy", "bonus round", "vandal", "phantom", "operator", "sheriff", "spectre", "odin",
             "judge", "marshal", "outlaw", "ult", "ults", "retake", "post plant", "post-plant", "lurk", "entry",
             "duelist", "initiator", "controller", "sentinel", "radiant", "immortal", "ascendant", "diamond",
             "platinum", "ranked", "rr", "credits", "clutch", "callout", "callouts", "crosshair", "heaven", "hookah",
             "a site", "b site", "c site", "a main", "b main", "mid", "rotate", "stack", "flank", "last guy",
             "buy or save", "save or buy", "eco", "force", "one tap", "peek", "peeking", "util", "utility",
             "pistol", "pistol round", "save round", "plant", "rifle round", "full save", "agent", "agents",
             "ultimate", "abilities", "ability", "coach me", "coaching", "need a coach", "want a coach",
             "be my coach", "need coaching"]
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


GREETING = (r"yo+|ay+o*|hey+|hi+|hello+|sup|wsp|wsg|wassup|wazzup|what'?s ?(up|good|poppin)|wyd|hbu|hru|"
            r"how (are|r) (you|u|ya)( doing)?|how'?s it going|gm|gn|good (morning|night|evening|afternoon)|lol+|"
            r"lmao+|haha+|ok(ay)?|k+|bet|thanks?( you)?|ty|thx|nice|cool|damn|bruh+|fr|real|facts|true|gg|"
            r"i'?m back|back")
FILLER = r"bro|bruh|man|dude|coach|flip|buddy|g|fam|homie|twin|gang|my (guy|g|dude|boy)|again"


def small_talk(text):
    """Just a greeting or a reaction ("wsp coach", "yo bro", "lol ok"): nothing to coach or explain."""
    t = re.sub(r"[^\w\s']", " ", text.lower())
    if not t.strip() or len(t.split()) > 6:
        return False
    t = re.sub(rf"\b({GREETING})\b", " ", t)
    t = re.sub(rf"\b({FILLER})\b", " ", t)
    return not t.strip()


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
    return (_has(MATH_WORDS, t) and bool(re.search(r"\d", t))) or word_problem(text)


def is_valorant(text):
    t = text.lower()
    return (_has(AGENTS + MAPS + VAL_WORDS + ["op", "opper", "oper"], t) or bool(POSITION.search(t))
            or bool(re.search(r"\b[1-5]\s*(v|vs)\s*[1-5]\b", t)))


POSITION = re.compile(r"\b(one|two|three|four|five|\d)\s+(a|b|c|mid|heaven|main|site|long|short|link|market|hookah|"
                      r"tree|garden|elbow|window|ramps|rafters|lobby|spawn|cat|catwalk|showers|hell|top|bottom)\b"
                      r"(?!\s+(sentence|sentences|answer|reply|word|words|question|thing|things|time|second|seconds|"
                      r"minute|minutes|sec|way|story|joke|line|lines|paragraph|version|list|summary|message|text))")
STRONG_LIVE = re.compile(r"\b\d\s*(v|vs)\s*\d\b|\bplanted\b|\bspike (down|planted)\b|\blast (guy|one|enemy)\b|"
                         r"\bflank(ing|ed)?\b|\b\d(\.\d)?\s*k\b|\b\d{3,4}\s*(credits|creds|cred)\b|\bdefusing\b|"
                         r"\b(keeps?|they'?re|enemy|enemies) (push|pushing|rushing|peeking|holding)")
# asking to learn something, not reporting the round ("sova lineups for ascent a site")
NOT_LIVE = re.compile(r"\b(lineups?|line ups?|setups?|strats?|strategy|guide|tips?|explain|teach|learn|tutorial|"
                      r"practice|review|meta|tier list|patch)\b")
QUESTION = re.compile(r"^(how|why|explain|what|whats|what's|which|where|when|who|any|is there|best|good|can you|"
                      r"could you|tell me|teach|give me|tips|help me understand|is it|should i learn|compare)\b")


def is_live(text, recent_valorant):
    """A quick mid-match update like "2 A, one heaven" or "Lotus, Phoenix, attack, 3.4k"."""
    t = text.lower().strip()
    words = len(t.split())
    if words > 16 or (QUESTION.search(t) and words > 4) or NOT_LIVE.search(t) or PLANNING.search(t):
        return False
    strong = bool(STRONG_LIVE.search(t) or POSITION.search(t))
    setup = _has(MAPS, t) + _has(AGENTS, t) + bool(re.search(r"\b(atk|def|attack|defense|defence|attacking|defending)\b", t))
    return (strong and words <= 12) or setup >= 2 or (recent_valorant and words <= 8 and (strong or _has(LIVE_WORDS, t)))


WORD_PROBLEM = re.compile(r"\b(then|after|each|every|per|rate|together|total|remaining|remainder|how (long|many|much|far)|"
                          r"hours?|minutes?|days?|km|miles?|speed|price|costs?|profit|interest|percent|times as|"
                          r"more than|less than|twice|half)\b", re.I)


def word_problem(text):
    """A multi-step problem told as a story (not just "59382 × 912")."""
    numbers = len(re.findall(r"\d+(?:\.\d+)?|\b(?:two|three|four|five|six|seven|eight|nine|ten|twice|half)\b", text, re.I))
    asks = re.search(r"\?|\b(how (long|many|much|far|fast)|what (is|was|will|total|time|percent)|find|calculate)\b", text, re.I)
    return numbers >= 2 and len(text) > 80 and bool(asks) and len(WORD_PROBLEM.findall(text)) >= 2


# ---------- things to look up, and match reviews ----------

# Things that change with patches or that his notes can't hold: look them up before answering.
FRESH = re.compile(r"\b(patch|patches|patch notes|meta|nerf|nerfs|nerfed|buff|buffs|buffed|new agent|newest|latest|"
                   r"current|currently|right now|this (act|episode|season|patch|year)|tier ?list|vct|champions|"
                   r"masters|pros? (play|plays|use|uses|run|runs|pick|picks|do)|pro (players?|teams?|comps?|play)|"
                   r"lineups?|line ups?|one ?ways?|setups? for)\b")
LOOKUP = re.compile(r"^\W*(?:(?:hey|yo|pls|please|flip|bro|can you|could you)\W+)*(?:search|look up|google)\b\s*"
                    r"(?:the web|online|the internet)?\s*(?:for)?\s*(.+)", re.I)
REVIEW = re.compile(r"\b(review|break ?down|breakdown|analy[sz]e|rate|grade|critique|roast|judge)\b.{0,30}\b(game|match|"
                    r"games|matches|round|rounds|stats|scoreboard|performance|gameplay|vod|play|this)\b|"
                    r"\bwhat went wrong\b|\bwhy (did )?(i|we) (lose|lost|throw|threw|choke|choked)\b|"
                    r"\bhow did (i|we) (do|play)\b|\bhow was my (game|match)\b|"
                    r"\bwhere (did )?(i|we) (go wrong|mess up|messed up)\b")
REVIEW_NOTE = ("(Match review: go over my game like a real coach would. Use only what's in the picture or what I told "
               "you (map, agent, score, K/D/A, ACS, ADR, first bloods/deaths, plants, econ). Format:\n"
               "**Verdict:** one honest line.\n"
               "**What lost rounds:** the 2-3 biggest problems, each with its evidence (a stat or what I said) and "
               "the exact fix.\n"
               "**What went well:** one thing to keep doing.\n"
               "**Next game:** one focus and one drill.\n"
               "Don't invent numbers you can't see; if something's unreadable or missing, ask for it in one line at "
               "the end. Save my main weakness with the remember tool.)")


# ---------- making pictures and videos ----------

MAKE = r"(?:make|makes|making|generate|create|draw|paint|sketch|design|render|produce|animate|give|show|send|imagine|film|shoot)"
PIC = (r"(?:images?|pictures?|pics?|photos?|drawings?|art|artwork|wallpapers?|logos?|icons?|posters?|thumbnails?|"
       r"avatars?|pfps?|profile pic(?:ture)?s?|banners?|memes?|stickers?|illustrations?|portraits?|emotes?|renders?)")
VID = r"(?:videos?|vids?|clips?|animations?|animated|gifs?|movies?|films?|reels?|cutscenes?|trailers?)"
PLAIN = {"image", "images", "picture", "pictures", "pic", "pics", "photo", "photos", "video", "videos", "vid", "vids", "clip",
         "clips"}
SAY = {"pfp": "profile picture", "pfps": "profile pictures", "gif": "short looping clip", "gifs": "short looping clips"}
UI_WORDS = ["imagelabel", "imagebutton", "decal", "texture id", "asset id", "surfacegui", "billboardgui", "screengui",
            "gui", "html", "css", "img tag"]
ASKING = re.compile(r"^(how|why|what|whats|what's|when|where|who|which|is|are|was|were|does|do|did|should|have|has)\b")
POLITE = re.compile(r"^\W*(?:(?:hey|yo|ok|okay|pls|please|plz|flip|bro|so|and|now|also|then|quick|real quick)\b\W*)+", re.I)
ASK = re.compile(r"^(?:(?:can|could|would|will) (?:you|u)(?: please| pls)?|(?:i|we) (?:want|need|would like|wanna)(?: you)?(?: to)?|"
                 r"i'?d like(?: you)?(?: to)?|let'?s|go|try to|try and)\s+", re.I)
FOLLOW = re.compile(r"^\W*(?:(?:now|ok|okay|and|but|pls|please|yo|nice|cool|lol)\W+)*(make (?:it|him|her|them|that|this)|"
                    r"change|add|remove|put|give (?:it|him|her|them)|same (?:thing |one )?but|again|another(?: one)?|"
                    r"one more|redo|try again|do (?:it|that) again|more|less|without|with)\b", re.I)
AGAIN_ONLY = re.compile(r"^\W*(?:(?:now|ok|okay|and|pls|please|yo)\W+)*(again|another(?: one)?|one more|redo|try again|"
                        r"do (?:it|that) again)\W*$", re.I)
ANIMATE = re.compile(r"\b(animate|bring (it|this|that|him|her) to life|make (it|this|that|him|her) (move|come alive|dance|"
                     r"talk)|(turn|make) (it|this|that) (into )?an? (video|clip|animation|gif))\b", re.I)
PRONOUN = re.compile(r"^(?:this|that|it|these|those|my (?:pic|picture|photo|image)|this (?:pic|picture|photo|image)|"
                     r"the (?:pic|picture|photo|image))$", re.I)


def clean_prompt(text, kind):
    """What to make, without the asking: "yo can you make me an anime picture of Jett dashing?" → "Jett
    dashing, anime"."""
    t = POLITE.sub("", text.strip())
    t = ASK.sub("", t)
    t = POLITE.sub("", t)
    t = re.sub(rf"^{MAKE}\b\s*", "", t, flags=re.I)
    t = re.sub(r"^(?:me|us|him|her|them)\b\s*", "", t, flags=re.I)
    t = re.sub(r"^(?:an?|the|some|one|my|our|a few|\d+)\s+", "", t, flags=re.I)
    noun = PIC if kind == "image" else VID
    m = re.match(rf"^((?:[\w'-]+\s+){{0,3}}?)({noun})\b\s*(?:of|showing|where|with|about|for|that shows|that has|in which)?\s*(.*)$",
                 t, re.I | re.S)
    if m:
        style, what, rest = m.group(1).strip(), m.group(2).lower(), m.group(3).strip(" ?!.")
        extra = [x for x in (style, "" if what in PLAIN else SAY.get(what, what)) if x]
        t = ", ".join([rest] + extra) if rest else " ".join(extra)
    t = re.sub(r"[\s?!.]+$", "", t)
    t = re.sub(r"\s*,?\s*\b(please|pls|plz|for me|real quick|rn|right now)\b\s*$", "", t, flags=re.I).strip(" ,")
    return "" if PRONOUN.match(t) else t


def media_request(text, mode="auto", has_picture=False, last=None):
    """("image" | "video", prompt) when they want Flip to make a picture or a video, else None.
    last: {"kind", "prompt"} of what his last reply made, for "make it darker" / "another one"."""
    t = (text or "").strip()
    low = t.lower()
    if mode in ("image", "video"):
        prompt = clean_prompt(t, mode) or t
        return (mode, prompt) if prompt or (mode == "video" and has_picture) else None
    if ANIMATE.search(low) and last and last["kind"] == "image" and not has_picture and not ASKING.match(low):
        return "video", last["prompt"]  # bring the picture he just made to life (the app passes it along)
    follow = FOLLOW.match(low) if last and not ASKING.match(low) and len(low.split()) <= 12 else None
    loose = follow and follow.group(1) in ("more", "less", "with", "without", "add", "remove", "change", "put")
    if follow and not (loose and len(low.split()) > 8) and (
            not low.rstrip().endswith("?") or follow.group(1).startswith(("make", "again", "another", "one more", "redo",
                                                                          "try again", "do "))):
        if AGAIN_ONLY.match(low):
            return last["kind"], last["prompt"]
        change = re.sub(r"^make (?:it|him|her|them|that|this)\s+", "", POLITE.sub("", t), flags=re.I).strip(" ?!.")
        return last["kind"], f"{last['prompt']}, {change}"
    if re.search(r"\bvideo ?games?\b", low) or _has(CODE_WORDS + UI_WORDS, low):
        return None
    if ASKING.match(low):
        return None  # "how do I make a video?", "what's in this picture?"
    animate = has_picture and ANIMATE.search(low)
    video = re.search(rf"\b{MAKE}\b(?:\W+[\w'-]+){{0,5}}?\W+{VID}\b", low) or animate
    image = re.search(rf"\b{MAKE}\b(?:\W+[\w'-]+){{0,5}}?\W+{PIC}\b", low) or re.match(
        r"^\W*(?:(?:hey|yo|pls|please|flip|bro|ok|okay)\W+)*(?:(?:can|could|would) (?:you|u)\W+)?(?:draw|paint|sketch)\b", low)
    kind = "video" if video else "image" if image else None
    if not kind:
        return None
    prompt = clean_prompt(t, kind)
    if animate and (not prompt or re.match(r"^(it|this|that|him|her)\b", prompt, re.I)):
        return kind, "bring this picture to life with natural, cinematic motion"
    if not prompt:
        return None  # "can you make pictures?" is a question about him, not a request
    return kind, prompt


GO_AHEAD = re.compile(r"^\W*(?:(?:ok(?:ay)?|k|yes|yeah|yea|yep|ya|sure|bet|pls|please|now|so|then|just|bro|fr)\W*)*"
                      r"(?:(?:do|make|generate|create|send|show|film|draw|paint) (?:it|that|one|this|the (?:video|vid|clip|"
                      r"picture|pic|image))|go(?: ahead| for it)?|whatever (?:you|u) (?:decide|want|think|pick)|surprise me|"
                      r"your (?:call|choice)|you (?:decide|pick|choose)|ok(?:ay)?|yes|yeah|yea|yep|sure|bet|pls|please)?"
                      r"(?:\W+(?:whatever (?:you|u) (?:decide|want|think|pick)|(?:then|now|already|pls|please|bro)))*\W*$", re.I)
OFFER = re.compile(r"\b(?:make|generate|create|draw|film|do)\b[^.?!\n]{0,30}?\b(video|vid|clip|picture|pic|image|drawing)"
                   r"\b of\s+([^.?!\n—]{3,80})", re.I)


MEDIA_TALK = re.compile(r"\b(videos?|vids?|clips?|pictures?|pics?|images?|animate|generat\w*|render\w*)\b", re.I)
MEDIA_NOTE = "(Pictures and videos are made by the app"
# (only checked when pictures/videos are the topic: then "just made it" can only be a made-up claim)
MEDIA_CLAIM = re.compile(r"\b(?:just |already )?(?:made|generated|created|filmed|rendered|finished)\b|(?:video|vid|clip|picture|pic|"
                         r"image)['’]?s? (?:is )?(?:in|up|ready|done|right here)|here['’]?s (?:the|your) (?:video|clip|picture|pic|"
                         r"image)|can['’]?t (?:generate|make|create) (?:videos?|pictures?|images?)|not generating|let me generate",
                         re.I)


def pending_request(text, messages):
    """"ok generate it, whatever u decide" after asking for a video (or after he offered one): what to make
    now, (kind, prompt), or None. Only while nothing was made since."""
    if not GO_AHEAD.match((text or "").strip()) or len(text.split()) > 9:
        return None
    recent = []
    for m in reversed(messages[-6:]):
        if m.get("role") == "assistant" and any(a.get("made") for a in m.get("attachments") or []):
            break  # he made it already: "ok" is just "ok"
        content = m.get("shown") or m.get("content") or ""
        if isinstance(content, str):
            recent.append((m.get("role"), content))
    for role, content in recent:  # what they asked for comes first
        want = media_request(content) if role == "user" else None
        if want:
            return want
    for role, content in recent:  # then what he offered ("I'll make a picture of her mid-throw")
        offer = OFFER.search(content) if role == "assistant" else None
        if offer:
            kind = "video" if offer.group(1).lower() in ("video", "vid", "clip") else "image"
            return kind, offer.group(2).strip(" ,")
    return None


LONGEST = {"code": 2500, "roblox": 2500, "math": 1200, "review": 1000}  # tokens; everything else 800


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
        self.search = ""             # look this up on the web first (patch, meta, lineups…)
        self.casual = False          # small talk in the middle of game talk: no strats in the reply

    def __repr__(self):
        return f"Route({self.kind}, tags={sorted(self.tags)}, math={self.math_tool}, max={self.max_tokens}, think={self.think})"


ASKED_AGENT = re.compile(r"\bagent (?:called |named )?([A-Za-z][\w/]{2,})|\b([A-Za-z][\w/]{2,})['’]s (?:ult|ultimate|ulti|"
                         r"abilities|ability|kit|util|utility|q|e|c|x|signature|passive)\b", re.I)
NOT_NAMES = {"my", "your", "his", "her", "their", "our", "the", "this", "that", "whose", "which", "what", "who", "its",
             "team", "enemy", "enemies", "duelist", "controller", "initiator", "sentinel", "valorant", "riot", "an",
             "every", "each", "one", "someone", "somebody", "anyone", "agent", "agents", "new", "best"}


TILT = re.compile(r"\b(tilt\w*|flam(e|es|ed|ing)|toxic|rag(e|ing)|so (mad|angry|annoyed|frustrated)|losing streak|"
                  r"lose streak|wanna (quit|uninstall)|want to (quit|uninstall)|bad day|i'?m done with (this|valorant))\b",
                  re.I)


GAME_ASK = re.compile(r"\b(beat|counter|deal with|play (vs|against)|how (do|should|can) (i|we) (play|hold|win|hit|stop|"
                      r"beat|counter|take|retake))\b", re.I)


SCREEN_ASK = re.compile(r"\b(see|look at|seeing|watch|watching)\b.{0,20}\bscreen\b", re.I)
GAME_FOLLOW = re.compile(r"\?|^\W*(and|but|so|ok|okay|what|how|why|where|which|when|who|should|can|could|would|is|"
                         r"are|do|does|did|then|also|more|else|next|now)\b|\b(hold|push|peek|play|playing|buy|save|"
                         r"smoke|flash|site|round|rank|ranked|agent|map|util|entry|aim|crosshair|sens|comp|team|enemy|"
                         r"enemies|attack|defen[cs]e|win|lose|lost|won|tips?|help|teach|improve|main|"
                         r"(?:need|want|be my|get) (?:a |my )?coach|coach me|coaching|"
                         r"duel|clutch|rotate|lurk|trade|eco|force)\b", re.I)
# a planning question isn't a mid-round callout ("I'm Omen on Bind attack, where do I smoke for a B split?")
PLANNING = re.compile(r"\b(where (do|should|can) (i|we)|how (do|should|can) (i|we)|what should (i|we) (buy|play|do "
                      r"on|use)|which|best way|smoke for|set ?up)\b", re.I)


def unknown_agent(text):
    """"What does the agent Zephyrus's ultimate do?": a name that isn't a Valorant agent (or None)."""
    try:
        import livedata
        live = {k for k, a in livedata.art().items() if a["kind"] == "agent"}
    except Exception:
        live = set()
    for m in ASKED_AGENT.finditer(text):
        name = (m.group(1) or m.group(2)).lower().replace("’", "'").removesuffix("'s")
        if name not in NOT_NAMES and name not in AGENTS and name not in live and name.replace("/", "") not in AGENTS:
            return name
    return None


def route(text, mode="auto", recent="", voice=False, pictures=0):
    """recent: the last few messages of the chat (for follow-ups like "and B?"). pictures: how many came with it."""
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

    # Just "wsp coach" or "lol ok": no coaching note (it made him recite what he'd do instead of saying hi).
    chit = small_talk(text) and mode not in ("math", "code")
    # In a Valorant chat a short follow-up ("ok what else?", "and on defense?") keeps the coaching going; "man
    # i'm so tired today" is just chat, even there (it got a Yoru setup)
    val = not chit and not SCREEN_ASK.search(t) and (is_valorant(t) or ((mode == "valorant" or (recent_val and len(t.split()) <= 12))
                                           and bool(GAME_FOLLOW.search(t))))
    math_q = not chit and (mode == "math" or looks_like_math(text))
    roblox = _has(ROBLOX_WORDS, t) or (_has(ROBLOX_WORDS, recent.lower()) and _has(CODE_WORDS, t))
    code = not chit and (mode == "code" or roblox or "```" in text or _has(CODE_WORDS, t))
    if not chit and not val and recent_val and not math_q and not code and not SCREEN_ASK.search(t):
        r.casual = True  # "before u get bored…" after a Bind question: chat back, no strats
        r.max_tokens = 80
        notes.append("(This is casual chat, not about the game. Reply to exactly what I said in 1-2 short lines like a "
                     "friend. No game advice, no strats.)")
    if chit:
        r.max_tokens = 50  # a long answer to "wsp" only has room to ramble (and repeat itself)
        notes.append("(Just small talk: reply like a friend would, in one short natural line. No pitch about what "
                     "you can do.)")

    asked = LOOKUP.match(text)
    if asked:
        r.search = asked.group(1).strip(" ?!.")[:150]
    elif val and FRESH.search(t) and not is_live(text, recent_val or mode == "valorant"):
        r.search = (text if "valorant" in t or "valo" in t else "valorant " + text)[:150]

    if not chit and REVIEW.search(t) and (val or pictures or recent_val) and not code:
        # "what went wrong?", "review my game" + a scoreboard: a real breakdown, not a quick answer
        r.kind = "review"
        r.tags |= {"valorant", "review"}
        r.temperature = 0.5
        notes.append(REVIEW_NOTE)
        val = math_q = False

    if val and not (math_q and mode != "valorant" and not is_valorant(t)):
        r.tags.add("valorant")
        r.kind = "valorant"
        if is_live(text, recent_val or mode == "valorant") and not math_q:
            r.kind = "live"
            r.tags.add("live")
            r.max_tokens = 70
            r.temperature = 0.5
            read = read_situation(text)
            notes.append("(Live match: " + (read + " " if read else "") + "Reply with 1-3 short imperative callouts "
                         "for exactly this situation, under 20 words total, using the match state and only this "
                         "map's real callouts. No greetings, emojis or generic advice.)")
        elif not is_valorant(t) and not FRESH.search(t) and not REVIEW.search(t):
            # "before u get bored or before i get bored" is not a question about the game: forcing the coaching
            # note on every short message in a Valorant chat got it an A-site execute
            notes.append("(We've been talking Valorant, but this message doesn't mention the game. If it clearly "
                         "follows on from what we were just discussing, keep helping with that. If it's just chat, "
                         "reply to what I actually said, like a friend. If you can't tell what I mean, ask me in one "
                         "short line. Never answer with game advice I didn't ask for.)")
        elif unknown_agent(text):
            name = unknown_agent(text).title()
            notes.append(f"(There is no Valorant agent called {name}. Say that plainly in one short line and don't "
                         f"make up abilities. If I probably meant a real agent with a similar name, ask if I meant that "
                         f"one.)")
        else:
            notes.append(COACH_NOTE_START + " your first sentence is the answer itself (the spot, the util, the timing), "
                         "with no intro before it. Help with exactly this, "
                         "confidently, like a coach who's also "
                         "my duo: concrete spots, util and timing for my situation, and why. Don't talk about how "
                         "you coach, just do it. Short unless I ask for detail. Use your notes; don't make up "
                         "abilities or patch numbers.)")
    if MEDIA_TALK.search(t) or MEDIA_TALK.search(recent.lower()):
        notes.append(MEDIA_NOTE + ", not by your reply: when I ask for one it gets made and "
                     "shows up in the chat. Never say you made, sent or are making one, and never say you can't make "
                     "them. If I want one, tell me to say \"make a video of …\" or \"make a picture of …\".)")
    if TILT.search(t) and r.kind in ("chat", "valorant") and not r.search and not GAME_ASK.search(t):
        r.tags.add("valorant")  # his notes on tilt and flame
        r.max_tokens = 100
        notes = [n for n in notes if not n.startswith(COACH_NOTE_START)]
        notes.append("(They're tilted or getting flamed: be a real friend first, in 1-3 short lines. Take their side a "
                     "bit, then one thing that helps them reset. No strats unless they ask.)")
    if math_q:
        r.math_tool = True
        if word_problem(text) and not voice and mode != "fast":
            r.think = True  # several steps: work it out privately first, then answer
            r.status = "working it out…"
            notes.append("(Word problem: think it through privately inside <think> </think> first (I won't see it): "
                         "list what's given and what's asked, set up each step, and do EVERY calculation with the math "
                         "tool (several expressions at once, separated by ;). Check the answer against the story. Then "
                         "give short clear steps and the final answer in bold.)")
        if r.kind not in ("valorant", "live"):
            r.kind = "math"
        r.temperature = 0.3
        r.status = "calculating…"
        notes.append("(Math: use the math tool for any calculation that isn't already worked out below, then check "
                     "the result makes sense. Show short clear steps unless I said to just answer. Write math with "
                     "LaTeX: $...$ inline, $$...$$ for equations on their own line.)")
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
        r.max_tokens = min(r.max_tokens or 120, 120)
    if r.think:
        r.max_tokens = 3000  # room to work it out
    # Every reply has an end: a small brain that falls into a loop otherwise writes until its memory is
    # full (the build saw a 10-minute "what's 59382 × 912?" on a processor).
    r.max_tokens = r.max_tokens or LONGEST.get(r.kind, 800)
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


COUNTS = re.compile(r"\b([1-5])\s*(?:v|vs|versus)\s*([1-5])\b", re.I)
SHOWN = re.compile(r"\b(one|two|three|four|five|[1-5])\s+(a|b|c|mid|heaven|main|long|short|site|hookah|market|garage)\b", re.I)
NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


COACH_NOTE_START = "(Valorant:"
GAME_TALK = re.compile(r"\b(smoke|flash|plant|rotate|execute|heaven|ramps|a main|b main|retake|util|lineup|"
                       r"crossfire|site|entry|peek|b on|a on|mid control)\w*", re.I)


def read_situation(text):
    """What a mid-round update means, so a small brain calls the right thing instead of a stock line
    ("2 A, one heaven" got "Save here. Rifles next round.")."""
    t = text.lower()
    reads = []
    if re.search(r"\b(we|i) (planted|plant)|\bspike('s| is)? (down|planted)\b", t) and not re.search(r"\bthey\b.{0,12}plant", t):
        reads.append("We planted: it's post-plant. Play off the spike from crossfires, don't swing for kills, "
                     "listen for the tap and stop the defuse.")
    elif re.search(r"\bthey\b.{0,12}plant", t):
        reads.append("They planted: it's a retake. Group up, util in first, trade each other, clear the plant spot.")
    m = COUNTS.search(t)
    if m:
        us, them = int(m.group(1)), int(m.group(2))
        if us < them and reads:  # down, with the spike in play
            reads.append(f"We're down {us}v{them}: no solo fights, play time and trade together.")
        elif us < them:
            reads.append(f"We're down {us}v{them}: no solo fights, stay together and trade, or save if it's lost.")
        elif us > them:
            reads.append(f"We're up {us}v{them}: play slow and together, trade, don't give free picks.")
    hit = re.search(r"\b(hitting|pushing|rushing|going|on) (a|b|c)\b", t)
    if hit and re.search(r"\b(def|defense|defence|defending)\b", t):
        reads.append(f"They're hitting {hit.group(2).upper()}: don't fight it alone. Delay with util, fall back "
                     f"and retake {hit.group(2).upper()} together.")
    shown = [(NUM.get(a, None) or int(a), b) for a, b in SHOWN.findall(t)]
    if shown:
        where = ", ".join(f"{n} {spot.upper() if len(spot) == 1 else spot}" for n, spot in shown)
        if re.search(r"\b(def|defense|defence|defending)\b", t):
            reads.append(f"Enemies spotted: {where}. Call the rotate or the stack toward them, keep one on the other site.")
        else:
            reads.append(f"Enemies spotted: {where}. That spot is heavy, so say what to do about it (hit the other "
                         f"site, or trade into it together).")
    return " ".join(reads)


def describe_match(s):
    if not s:
        return ""
    parts = [f"{k}: {v}" for k, v in s.items() if v not in (None, "")]
    return "(Match state so far — " + "; ".join(parts) + ".)"
