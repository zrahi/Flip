"""Catches made-up Valorant names in his replies: an agent that doesn't exist ("play a mid-tier agent like
Cerberus") or a gun that doesn't ("go for a Silent"). A small brain makes those up with total confidence, and
a coach who names a fake agent is worse than one who says less. A name counts as real if it's in his Valorant
notes (the built-in ones, or the live ones with every current agent, ability, map, callout and gun)."""

import functools
import re

import router

NAME = r"([A-Z][A-Za-z'’/.-]{2,})"
# where only an agent, a gun, a map or an ability fits
SLOTS = [
    re.compile(r"\b(?i:play|playing|pick|picking|lock(?:ing)? in|main|maining|swap to|switch to|go with|instalock)\s+"
               r"(?:an?\s+|the\s+)?" + NAME),
    re.compile(r"\b(?i:agents?|duelists?|controllers?|initiators?|sentinels?|someone|picks?)\s*,?\s+(?:like|such as)\s+"
               + NAME),
    re.compile(NAME + r"(?:'s|’s)?\s+(?:is|as)\s+(?:an?|the|your|our)\s+(?:[\w-]+\s+){0,2}"
               r"(?:duelist|controller|initiator|sentinel|agent)s?\b"),
    re.compile(r"\b(?i:buy|buying|grab|grabbing|go for|pick up|get|full buy|force(?: buy)?)\s+(?:an?\s+|the\s+)?"
               + NAME),
    re.compile(NAME + r"\s+(?:rifle|smg|shotgun|pistol|sniper|gun)s?\b"),
]
EXTRA = {"light", "heavy", "shields", "shield", "armor", "armour", "regen", "one", "some", "every", "any", "your",
         "their", "this", "that", "these", "those", "it", "them", "safe", "full", "valorant", "radiant", "immortal",
         "ascendant", "diamond", "platinum", "gold", "silver", "bronze", "iron", "unrated", "competitive", "ranked",
         "swiftplay", "spike", "rush", "deathmatch", "attack", "defense", "defence", "a", "b", "c", "mid", "site",
         "main", "long", "short", "heaven", "hell", "haven", "classic", "ghost", "free"}


@functools.lru_cache(maxsize=1)
def _known():
    words = set(EXTRA)
    words |= {w for n in router.AGENTS + router.MAPS for w in re.split(r"[/ ]", n)}
    try:
        import knowledge
        for folder in knowledge.FOLDERS:
            for f in folder.glob("valorant*.md") if folder.is_dir() else []:
                # the notes capitalize names; plain words ("silent", "step") aren't names
                for name in re.findall(r"\b[A-Z][A-Za-z0-9'’/-]*", f.read_text(encoding="utf-8")):
                    words.add(name.lower())
                    words |= set(name.lower().split("/"))
    except Exception:
        pass
    try:
        import livedata
        words |= {w for k in livedata.art() for w in re.split(r"[/ ]", k)}
    except Exception:
        pass
    return frozenset(words)


def _real(name):
    known = _known()
    n = name.lower().replace("’", "'").rstrip(".").removesuffix("'s").strip("'-/")
    return n in known or n.replace("/", "") in known or all(p in known for p in re.split(r"[/-]", n) if p)


# "an agent like D." — a sentence cut at the first dot of a made-up "D.V.A." (no agent is one letter)
INITIAL = re.compile(r"\b(?i:agents?|duelists?|controllers?|initiators?|sentinels?|someone)\s*,?\s+(?:like|such as)\s+"
                     r"([A-Z]\.)\s*$")


def join_initials(text):
    """"D.V.A." → "DVA.", so a name with dots stays one name when the text is split into sentences."""
    def joined(m):
        after = text[m.end():]
        ends = not after.strip() or re.match(r"\s+[A-Z]", after)  # the dot also ended the sentence
        return m.group(0).replace(".", "") + ("." if ends else "")
    return re.sub(r"\b(?:[A-Z]\.){2,}", joined, text)


# an eco (saving) round can't afford these; "anti-eco" is the enemy saving, so rifles are fine then
ECO = re.compile(r"(?<![-\w])(?<!anti )(?<!anti-)eco(?: round)?s?\b|\bsave rounds?\b|\bfull save\b", re.I)
PRICEY = re.compile(r"\b(vandal|phantom|operator|odin|guardian|bulldog|outlaw|judge)\b", re.I)
NOT = re.compile(r"\b(don'?t|do not|never|not|no|avoid|skip|instead of|can'?t|won'?t|unless|anti|keep|alive|drop|dropped|picked up|leftover|already have)\b", re.I)


def made_up(sentence):
    """The first name in sentence that sits where an agent or a gun goes but isn't one (or None), or a gun an
    eco round can't buy ("on eco rounds, use a long-range weapon like the Vandal")."""
    if ECO.search(sentence) and not NOT.search(sentence):
        m = PRICEY.search(sentence)
        if m:
            return f"{m.group(1)} on an eco"
    m = INITIAL.search(sentence)
    if m:
        return m.group(1)
    for slot in SLOTS:
        for m in slot.finditer(sentence):
            if not _real(m.group(1)):
                return m.group(1).rstrip(".")
    return None


def reset():
    """Forget the known names (the live notes were just rewritten)."""
    _known.cache_clear()
