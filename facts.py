"""Catches made-up Valorant names in his replies: an agent that doesn't exist ("play a mid-tier agent like
Cerberus") or a gun that doesn't ("go for a Silent"). A small brain makes those up with total confidence, and
a coach who names a fake agent is worse than one who says less. A name counts as real if it's in his Valorant
notes (the built-in ones, or the live ones with every current agent, ability, map, callout and gun)."""

import functools
import re

import router

NAME = r"([A-Z][A-Za-z'’/-]{2,})"
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
    n = name.lower().replace("’", "'").removesuffix("'s").strip("'-/")
    return n in known or n.replace("/", "") in known or all(p in known for p in re.split(r"[/-]", n) if p)


def made_up(sentence):
    """The first name in sentence that sits where an agent or a gun goes but isn't one (or None)."""
    for slot in SLOTS:
        for m in slot.finditer(sentence):
            if not _real(m.group(1)):
                return m.group(1)
    return None


def reset():
    """Forget the known names (the live notes were just rewritten)."""
    _known.cache_clear()
