"""Free web search and page reading, no key or account (DuckDuckGo's plain HTML pages).

Used for things that change: patch notes, the meta, new agents, lineups, pro play. Results are cached
for an hour, so asking twice doesn't search twice.
"""

import html
import logging
import re
import time
import urllib.parse
import urllib.request

log = logging.getLogger("flip")

SEARCH = "https://html.duckduckgo.com/html/"
LITE = "https://lite.duckduckgo.com/lite/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Flip/1.0", "Accept-Language": "en-US,en;q=0.8"}
_cache = {}

TOOL = {
    "name": "web_search",
    "description": "Search the web for things that change or that you don't know: patch notes, the current meta, new "
                   "agents or maps, lineups, pro play, news. Returns the top results and the text of the best one.",
    "schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}


def _fetch(url, data=None, timeout=20, limit=2_000_000):
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(limit)
        charset = r.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, "replace")


def _text(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _real_url(href):
    """DuckDuckGo links go through a redirect (//duckduckgo.com/l/?uddg=<the real link>)."""
    href = html.unescape(href)
    if "uddg=" in href:
        return urllib.parse.unquote(re.search(r"uddg=([^&]+)", href).group(1))
    return "https:" + href if href.startswith("//") else href


def parse_results(page):
    """[{"title", "url", "snippet"}] from DuckDuckGo's HTML (or lite) results page."""
    out = []
    for m in re.finditer(r"<(a|td)\s([^>]*)>(.*?)</\1>", page, re.S):  # (results never nest these)
        attrs, inner = m.group(2), m.group(3)
        cls = re.search(r"class=['\"]([^'\"]+)['\"]", attrs)
        classes = cls.group(1).split() if cls else []
        href = re.search(r"href=['\"]([^'\"]+)['\"]", attrs)
        if href and ("result__a" in classes or "result-link" in classes):
            out.append({"title": _text(inner), "url": _real_url(href.group(1)), "snippet": ""})
        elif ("result__snippet" in classes or "result-snippet" in classes) and out and not out[-1]["snippet"]:
            out[-1]["snippet"] = _text(inner)
    return [r for r in out if r["url"].startswith("http") and "duckduckgo.com/y.js" not in r["url"]]


def search(query, n=5):
    query = " ".join(str(query).split())[:200]
    hit = _cache.get(query)
    if hit and time.time() - hit[0] < 3600:
        return hit[1][:n]
    results = []
    for url in (SEARCH, LITE):
        try:
            results = parse_results(_fetch(url, urllib.parse.urlencode({"q": query}).encode()))
        except Exception as e:
            log.warning("Web search failed (%s): %s", url, e)
        if results:
            break
    _cache[query] = (time.time(), results)
    return results[:n]


def read(url, limit=6000):
    """The readable text of a web page (no scripts, menus or styling), cut to limit characters."""
    page = _fetch(url, timeout=20)
    page = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|form|iframe)[^>]*>.*?</\1>", " ", page)
    main = re.search(r"(?is)<(article|main)[^>]*>(.*)</\1>", page)
    page = main.group(2) if main else page
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr)>", "\n", page)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    text = "\n".join(line for line in lines if len(line) > 1)
    return text[:limit]


def lookup(query, read_top=True, limit=2500):
    """Search results as text for the brain, with the best result's page text when it can be read."""
    results = search(query)
    if not results:
        return "(web search found nothing or isn't reachable right now)"
    lines = [f"{i + 1}. {r['title']} — {r['snippet']} ({r['url']})" for i, r in enumerate(results)]
    if read_top:
        for r in results[:3]:
            if re.search(r"youtube\.com|youtu\.be|tiktok\.com|reddit\.com/r/.+/comments", r["url"]):
                continue  # videos and threads don't read well as text
            try:
                text = read(r["url"], limit)
            except Exception:
                continue
            if len(text) > 300:
                lines.append(f"\nFrom {r['url']}:\n{text}")
                break
    return "\n".join(lines)
