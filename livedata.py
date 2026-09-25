"""Keeps Flip's Valorant knowledge current, for free.

Once a day (and whenever the game's version changes) it downloads the live lists from valorant-api.com
(a free community API that mirrors the game's own files): every agent with their current abilities, the
maps with their official callouts, the guns with prices and damage, and the shields. It also looks up the
latest patch notes on the web. Everything goes into a notes file in Flip's knowledge folder
(knowledge/valorant-current.md), in the same "## Title / KEYS:" format as his other notes, so a new agent
or a rework the day it ships is in his notes the next time he starts, without an app update.
"""

import json
import logging
import re
import time
import urllib.request

from paths import DATA

log = logging.getLogger("flip")

API = "https://valorant-api.com/v1/"
NOTES = DATA / "knowledge" / "valorant-current.md"
STATE = DATA / "knowledge" / "valorant-current.json"
MAX_AGE = 24 * 3600
SLOT = {"Ability1": "Q", "Ability2": "E", "Grenade": "C", "Ultimate": "X (ult)", "Passive": "Passive"}
HEADERS = {"User-Agent": "Flip/1.0"}


def _get(path):
    with urllib.request.urlopen(urllib.request.Request(API + path, headers=HEADERS), timeout=30) as r:
        return json.load(r)["data"]


def _short(text, limit=260):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _key(name):
    return re.sub(r"[^a-z0-9/' -]", "", str(name).lower()).strip()


def version_text(v):
    """"release-11.06-shipping-…" or "11.06.00.123" → "11.06"."""
    m = re.search(r"(\d+)\.(\d+)", str(v.get("riotClientVersion") or v.get("version") or ""))
    return f"{int(m.group(1))}.{m.group(2)}" if m else ""


def agent_notes(agents):
    by_role, sections = {}, []
    for a in sorted(agents, key=lambda a: a.get("displayName", "")):
        if not a.get("isPlayableCharacter", True) or not a.get("displayName"):
            continue
        name = a["displayName"]
        role = (a.get("role") or {}).get("displayName") or "Agent"
        by_role.setdefault(role, []).append(name)
        order = {s: i for i, s in enumerate(SLOT)}
        kit = sorted((ab for ab in a.get("abilities") or [] if ab.get("displayName")),
                     key=lambda ab: order.get(ab.get("slot"), 9))
        lines = [f"- {SLOT.get(ab.get('slot'), ab.get('slot') or '?')}: {ab['displayName']}: {_short(ab.get('description'))}"
                 for ab in kit]
        keys = [_key(name)] + [_key(ab["displayName"]) for ab in kit]
        sections.append((f"{name} ({role}), current kit", keys, "\n".join(lines)))
    roster = "\n".join(f"- {role}s: {', '.join(names)}" for role, names in sorted(by_role.items()))
    return roster, sections


def map_notes(maps):
    sections = []
    for m in sorted(maps, key=lambda m: m.get("displayName", "")):
        sites = m.get("tacticalDescription") or ""
        callouts = m.get("callouts") or []
        if "site" not in sites.lower() or not callouts:
            continue  # the range, deathmatch and skirmish maps
        areas = {}
        for c in callouts:
            region, area = c.get("regionName"), c.get("superRegionName") or "Other"
            if region and region not in areas.setdefault(area, []):
                areas[area].append(region)
        text = f"Sites: {sites}. Official callouts by area:\n" + "\n".join(
            f"- {area}: {', '.join(names)}" for area, names in sorted(areas.items()))
        sections.append((f"{m['displayName']} callouts (current)", [_key(m["displayName"])], text))
    return sections


def weapon_notes(weapons, gear):
    lines, keys = [], ["price", "prices", "cost", "costs", "credits", "buy", "gun", "guns", "weapon", "weapons", "damage"]
    for w in sorted(weapons, key=lambda w: ((w.get("shopData") or {}).get("cost") or 0, w.get("displayName", ""))):
        shop, stats = w.get("shopData") or {}, w.get("weaponStats") or {}
        if not w.get("displayName"):
            continue
        keys.append(_key(w["displayName"]))
        parts = [f"{shop.get('cost', 0)} credits" if shop else "free"]
        if shop.get("category"):
            parts.append(str(shop["category"]).rstrip("s"))
        if stats.get("magazineSize"):
            parts.append(f"{stats['magazineSize']} rounds")
        ranges = stats.get("damageRanges") or []
        if ranges:
            r = ranges[0]
            parts.append(f"head/body/legs {round(r.get('headDamage', 0))}/{round(r.get('bodyDamage', 0))}/"
                         f"{round(r.get('legDamage', 0))} at {r.get('rangeStartMeters', 0)}-{r.get('rangeEndMeters', 0)} m")
        lines.append(f"- {w['displayName']}: {', '.join(parts)}")
    shields = []
    for g in gear or []:
        if g.get("displayName"):
            cost = (g.get("shopData") or {}).get("cost")
            shields.append(f"- {g['displayName']}{f' ({cost} credits)' if cost else ''}: {_short(g.get('description'), 160)}")
    return keys, "\n".join(lines), "\n".join(shields)


def build(version, agents, maps, weapons, gear, patch=None):
    """The notes file's text from the live data."""
    day = time.strftime("%B %d %Y")
    roster, agent_sections = agent_notes(agents)
    wkeys, guns, shields = weapon_notes(weapons, gear)
    out = [f"# Valorant, current data (downloaded {day}, game version {version or 'unknown'})", "",
           "## Current agents and version (live)", "KEYS: *valorant",
           f"LIVE DATA from the game's files ({day}, version {version or 'unknown'}). This beats any older agent list "
           f"or kit in your notes. These are ALL the agents right now:", roster]
    for title, keys, text in agent_sections:
        out += ["", f"## {title}", "KEYS: " + ", ".join(keys), text]
    for title, keys, text in map_notes(maps):
        out += ["", f"## {title}", "KEYS: " + ", ".join(keys), text]
    out += ["", "## Guns and prices (current)", "KEYS: " + ", ".join(dict.fromkeys(wkeys)), guns]
    if shields:
        out += ["", "## Shields (current)", "KEYS: shield, shields, armor, armour, light, heavy, regen", shields]
    if patch:
        out += ["", f"## Patch notes {patch['version']} (latest)", "KEYS: " + ", ".join(patch["keys"]),
                f"From {patch['url']} ({day}):", patch["text"]]
    return "\n".join(out) + "\n"


def patch_notes(version, names):
    """The latest patch notes' main points (a web search; best effort). names: agent/map/gun names, which
    become the section's keys when the notes mention them."""
    import web

    if not version:
        return None
    for r in web.search(f"VALORANT patch notes {version}", 6):
        if "playvalorant.com" in r["url"] and "patch" in r["url"].lower():
            text = web.read(r["url"], 9000)
            if len(text) < 500:
                continue
            start = text.lower().find("agent")
            text = _short(text[max(0, start - 200):] if start > 0 else text, 3500)
            low = text.lower()
            keys = ["patch", "patch notes", "nerf", "nerfed", "buff", "buffed", "changes", "changed", "update",
                    "meta", "new"] + [n for n in names if n and re.search(rf"\b{re.escape(n)}\b", low)]
            return {"version": version, "url": r["url"], "text": text, "keys": list(dict.fromkeys(keys))}
    return None


def refresh(force=False):
    """Updates the notes if they're a day old or the game changed version. Returns True if it rewrote them."""
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    if not force and NOTES.exists() and time.time() - state.get("checked", 0) < MAX_AGE:
        return False
    try:
        version = version_text(_get("version"))
        if not force and NOTES.exists() and version and version == state.get("version"):
            STATE.write_text(json.dumps(dict(state, checked=time.time())))
            return False
        agents = _get("agents?isPlayableCharacter=true&language=en-US")
        maps = _get("maps?language=en-US")
        weapons = _get("weapons?language=en-US")
        try:
            gear = _get("gear?language=en-US")
        except Exception:
            gear = []
        names = [_key(x.get("displayName")) for x in agents + maps + weapons]
        try:
            patch = patch_notes(version, names)
        except Exception:
            log.exception("Couldn't get the patch notes")
            patch = None
        text = build(version, agents, maps, weapons, gear, patch)
        NOTES.parent.mkdir(parents=True, exist_ok=True)
        NOTES.write_text(text, encoding="utf-8")
        STATE.write_text(json.dumps({"checked": time.time(), "version": version}))
        log.info("Valorant notes updated: version %s, %d agents (%d characters)", version, len(agents), len(text))
        return True
    except Exception as e:
        log.warning("Couldn't update the Valorant notes (offline?): %s", e)
        return False
