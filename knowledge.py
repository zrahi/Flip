"""Know-how Flip reads only when a message needs it (Valorant, Roblox…).

Each .md file in the knowledge folders is split into "## " sections. A section's "KEYS:" line lists
words that pull it in; a key starting with * is a tag the router adds (like *valorant or *live).
Built-in files live next to the app; files the user drops into Flip's data folder (for example the
latest patch notes) are read too, so the knowledge can be kept current without an update.
"""

import logging
import re

from paths import DATA, RES

log = logging.getLogger("flip")

FOLDERS = (RES / "knowledge", DATA / "knowledge")


def parse(text, source=""):
    sections = []
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, rest = block.partition("\n")
        keys = []
        body = rest
        m = re.match(r"\s*KEYS:(.*)\n", rest)
        if m:
            keys = [k.strip().lower() for k in m.group(1).split(",") if k.strip()]
            body = rest[m.end():]
        sections.append({"title": title.strip(), "keys": keys, "text": body.strip(), "source": source})
    return sections


def load():
    sections = []
    for folder in FOLDERS:
        for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            try:
                sections += parse(f.read_text(encoding="utf-8"), f.stem)
            except OSError:
                log.exception("Couldn't read %s", f)
    return sections


def _hits(key, text):
    if key.startswith("*"):
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", text) is not None


def pick(sections, text, tags=(), budget=5000):
    """The sections that fit this message, best matches first, within budget characters.
    text: the message plus a bit of recent chat (lowercase)."""
    text = text.lower()
    scored = []
    for i, s in enumerate(sections):
        tagged = [k[1:] for k in s["keys"] if k.startswith("*") and k[1:] in tags]
        hits = sum(_hits(k, text) for k in s["keys"])
        if tagged or hits:
            # a mode's own notes (live callouts, reviews) first, then what the message is about, then the basics
            rank = 0 if any(t != "valorant" for t in tagged) else 1 if hits else 2
            scored.append((rank, -hits, i, s))
    chosen, used = [], 0
    for *_, s in sorted(scored):
        size = len(s["text"]) + len(s["title"]) + 8
        if used + size > budget:
            continue
        chosen.append(s)
        used += size
    return chosen


def render(chosen):
    return "\n\n".join(f"[{s['title']}]\n{s['text']}" for s in chosen)
