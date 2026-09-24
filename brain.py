"""Flip's brain: talks to the AI model on your PC, remembers things, and uses tools."""

import asyncio
import json
import re
import logging
import threading
import time

import knowledge
import mathtool
import router
import store
import usage

log = logging.getLogger("flip")

MAX_HISTORY = 30       # messages from the current chat the AI sees
MAX_TOOL_STEPS = 15    # tool uses per message before he stops
MAX_TOOL_OUTPUT = 4000 # characters of tool output the AI gets to see

MEMORY_TOOLS = [
    {
        "name": "remember",
        "description": "Save a fact about the user to your long-term memory so you still know it in future chats "
                       "(their name, what they like, what they're working on, goals, preferences). "
                       "Use it whenever you learn something worth remembering. One short fact per call.",
        "schema": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]},
    },
    {
        "name": "forget",
        "description": "Delete a memory by its id, when it's wrong, outdated, or the user asks you to forget it.",
        "schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
]


REPLY_ROOM = 1500      # tokens kept free for his answer

# Words that mean the chat is about Roblox, so Roblox Studio's tools should come along.
ROBLOX_WORDS = ["roblox", "studio", "luau", "lua", "script", "houseflipper", "house flipper", "workspace",
                "part", "model", "gui", "remote", "datastore", "leaderstat", "npc", "tween", "humanoid",
                "baseplate", "terrain", "place", "obby", "tycoon", "game", "code", "bug", "error", "build"]


class NoModelError(Exception):
    pass


def estimate_tokens(content):
    """Rough token count (the brain reads about 3.5 characters per token; a screenshot is ~1000)."""
    if isinstance(content, list):
        return sum(estimate_tokens(p.get("text", "")) if p.get("type") == "text" else 1000 for p in content)
    return len(content) // 3 + 1


def short(text, limit):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def slim_schema(schema):
    """Tool schemas can carry long descriptions for every field; keep the structure, trim the words."""
    if isinstance(schema, dict):
        return {k: (short(v, 120) if k == "description" and isinstance(v, str) else slim_schema(v))
                for k, v in schema.items() if k not in ("examples", "$comment")}
    if isinstance(schema, list):
        return [slim_schema(v) for v in schema]
    return schema


def _field(obj, new_name, old_name):
    # The mcp library renamed fields in v2 (inputSchema -> input_schema); support both.
    return getattr(obj, new_name, None) if hasattr(obj, new_name) else getattr(obj, old_name, None)


def clean_reply(text):
    # Reasoning models put their thinking in <think> tags; don't show or say it.
    if "</think>" in text:
        text = text.split("</think>")[-1]
    return text.strip()


class RobloxLink:
    """Runs the Roblox Studio MCP server in a background thread."""

    def __init__(self, command):
        self.status = "starting"
        self.tools = []
        self._command = command
        self._session = None
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_until_complete, args=(self._run(),), daemon=True).start()

    async def _run(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        try:
            params = StdioServerParameters(command=self._command[0], args=self._command[1:])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.tools = [
                        {"name": t.name, "description": short(t.description or "", 220),
                         "schema": slim_schema(_field(t, "input_schema", "inputSchema") or {"type": "object", "properties": {}})}
                        for t in (await session.list_tools()).tools
                    ]
                    log.info("Roblox tools take about %d tokens", estimate_tokens(json.dumps(self.tools)))
                    self._session = session
                    self.status = "connected"
                    log.info("Roblox Studio connected, %d tools", len(self.tools))
                    await asyncio.Event().wait()  # keep the connection open
        except Exception as e:
            log.exception("Roblox Studio link failed")
            self.status = f"error: {e}"
        self._session = None

    def call(self, name, args):
        if self._session is None:
            return "ERROR: Roblox Studio isn't connected."
        future = asyncio.run_coroutine_threadsafe(self._session.call_tool(name, args), self._loop)
        result = future.result(timeout=180)
        text = "\n".join(getattr(c, "text", None) or f"[{c.type}]" for c in result.content) or "(no output)"
        if _field(result, "is_error", "isError"):
            text = "ERROR: " + text
        return text


# ---------- the AI model ----------

class LocalBackend:
    """Any OpenAI-style server: the built-in llama.cpp brain, LM Studio, Ollama…"""

    def __init__(self, url, api_key=""):
        from openai import OpenAI

        self.client = OpenAI(base_url=url, api_key=api_key or "local", timeout=600)
        self.model = ""

    def _pick_model(self):
        if not self.model:
            ids = [m.id for m in self.client.models.list().data if "embed" not in m.id.lower()]
            if not ids:
                raise NoModelError()
            self.model = ids[0]
        return self.model

    @staticmethod
    def _spec(tools):
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["schema"]}} for t in tools]

    def _kwargs(self, messages, spec, max_tokens=None, temperature=0.7):
        kwargs = {"model": self._pick_model(), "messages": messages,
                  # Qwen's recommended settings for chatting.
                  "temperature": temperature, "top_p": 0.8, "presence_penalty": 1.0,
                  "extra_body": {
                      # Qwen3 brains have a hidden "thinking" mode that writes a long essay before every
                      # answer. Turn it off: answers come way faster.
                      "chat_template_kwargs": {"enable_thinking": False},
                      "top_k": 20, "repeat_penalty": 1.05,
                      # DRY: makes it costly to copy word sequences that are already anywhere in the chat,
                      # so he can't paste his earlier replies again.
                      "dry_multiplier": 0.8, "dry_base": 1.75, "dry_allowed_length": 3, "dry_penalty_last_n": 8192,
                  }}
        if spec:
            kwargs["tools"] = spec
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        return kwargs

    def warm_up(self, system, tools):
        """Reads the system text once in advance, so the first real message is quick."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": "hi"}]
        self.client.chat.completions.create(**self._kwargs(messages, self._spec(tools), max_tokens=1))

    def answer(self, system, history, tools, run_tool, on_text=None, stop=None, max_tokens=None, temperature=0.7):
        """Runs the model (and any tools it asks for). Streams text through on_text as it's written.
        Returns (reply, stopped)."""
        messages = [{"role": "system", "content": system}] + history
        spec = self._spec(tools)
        shown = ""
        for _ in range(MAX_TOOL_STEPS):
            kwargs = self._kwargs(messages, spec, max_tokens, temperature)
            kwargs["stream"] = True
            stream = self.client.chat.completions.create(**kwargs)
            text, calls = "", {}
            try:
                for chunk in stream:
                    if stop is not None and stop.is_set():
                        return clean_reply(shown + text), True
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        before = visible(text)
                        text += delta.content
                        after = visible(text)
                        if on_text and len(after) > len(before):
                            on_text(after[len(before):])
                    for tc in delta.tool_calls or []:
                        c = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                        c["id"] = tc.id or c["id"]
                        if tc.function:
                            c["name"] += tc.function.name or ""
                            c["args"] += tc.function.arguments or ""
            finally:
                stream.close()
            if not calls:
                return clean_reply(shown + text), False
            shown += visible(text)
            if visible(text).strip() and on_text:
                on_text("\n\n")
                shown += "\n\n"
            messages.append({
                "role": "assistant",
                "content": text,
                "tool_calls": [{"id": c["id"] or f"call_{i}", "type": "function",
                                "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                               for i, c in sorted(calls.items())],
            })
            for i, c in sorted(calls.items()):
                try:
                    args = json.loads(c["args"] or "{}")
                except ValueError:
                    args = {}
                messages.append({"role": "tool", "tool_call_id": c["id"] or f"call_{i}",
                                 "content": run_tool(c["name"], args)})
        return clean_reply(shown) + "\n\nbro I did like 15 steps and got lost 😭 tell me to keep going", False


def window_start(n):
    """Where the part of the chat the brain sees starts. It moves forward in steps of 10 messages
    instead of one per message: the brain keeps what it already read of the chat (its cache) as long
    as the start stays put, so a sliding window made every single reply re-read the whole chat."""
    if n <= MAX_HISTORY:
        return 0
    return ((n - MAX_HISTORY) // 10 + 1) * 10


def _repeats(reply, earlier):
    """True if the reply is (nearly) one of his earlier replies, or starts the same way."""
    import difflib

    norm = lambda t: re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()
    r = norm(reply)
    for e in earlier:
        e = norm(e)
        if not e:
            continue
        if difflib.SequenceMatcher(None, r, e).ratio() > 0.6 or (len(r) > 20 and r[:25] == e[:25]):
            return True
    return False


def parse_skill(text):
    """A skill file can start with a line like "KEYWORDS: valorant, jett, ..."; it's only used when
    the chat mentions one of them. Without that line it's always used."""
    first, _, rest = text.partition("\n")
    if first.upper().startswith("KEYWORDS:"):
        keywords = [k.strip().lower() for k in first.split(":", 1)[1].split(",") if k.strip()]
        return {"keywords": keywords, "text": rest.strip()}
    return {"keywords": [""], "text": text.strip()}


def visible(text):
    """The part of a streamed reply that's okay to show (hides <think>…</think> blocks)."""
    if "<think>" in text:
        before, _, rest = text.partition("<think>")
        return before + (rest.split("</think>", 1)[1] if "</think>" in rest else "")
    if "</think>" in text:
        return text.split("</think>", 1)[1]
    return text


# ---------- Flip himself ----------

class Brain:
    def __init__(self, settings, personality, local_url, skills=()):
        self.name = settings["name"]
        self.settings = settings
        self.personality = personality.replace("{name}", self.name)
        self.skills = [parse_skill(s) for s in skills]
        self.knowledge = knowledge.load()
        self.last_route = None
        self.last_stats = {}
        self.on_tool = lambda name: None
        self.on_route = lambda way: None
        self.roblox = RobloxLink(settings["roblox_command"]) if settings.get("roblox_studio") else None

        self.backend = LocalBackend(local_url)

    def warm_up(self):
        try:
            self.backend.warm_up(self._system(), self._tools())
            log.info("Brain warmed up")
        except Exception as e:  # e.g. the brain was restarting (fast mode switch); it's only a head start
            log.warning("Warm-up skipped: %s", e)

    def roblox_status(self):
        return self.roblox.status if self.roblox else "off"

    def _system(self, topic=""):
        parts = [self.personality]
        if store.current:
            parts.append(f"You're talking to {store.current['name']} (that's the name on their profile).")
        mems = store.memories()
        if mems:
            parts.append("THINGS YOU REMEMBER ABOUT THE USER (from past chats):\n" +
                         "\n".join(f"- [{m['id']}] {m['text']}" for m in mems))
        else:
            parts.append("You don't remember anything about the user yet. Use the remember tool when you learn about them.")
        # Extra know-how (like Valorant) only goes in when the chat is about it: every word here has to
        # be read before he can answer, so a shorter text means a faster reply.
        parts.extend(sk["text"] for sk in self.skills if sk["keywords"] == [""])
        # Only the date (not the time): keeping this text the same between messages lets the
        # brain reuse its work on the chat so far instead of re-reading everything each time.
        parts.append(time.strftime("Today is %A, %B %d %Y."))
        return "\n\n".join(parts)

    def _tools(self, topic=""):
        tools = list(MEMORY_TOOLS) + [mathtool.TOOL]  # always there, so the brain's cached work stays valid
        # Roblox Studio's tools are big, so they only come along when the chat is about Roblox.
        if self.roblox and self.roblox.status == "connected" and any(k in topic.lower() for k in ROBLOX_WORDS):
            tools += self.roblox.tools
        return tools

    def _fit(self, system, history, tools):
        """Makes sure everything fits in what the brain can read at once (its context).
        Drops the oldest messages first, then Roblox tools. Returns (history, tools)."""
        budget = int(self.settings.get("context", 8192)) - REPLY_ROOM
        fixed = estimate_tokens(system) + estimate_tokens(json.dumps(tools))
        if fixed > budget * 0.7 and len(tools) > len(MEMORY_TOOLS) + 1:
            log.warning("Tools too big (%d tokens), leaving Roblox tools out", fixed)
            tools = list(MEMORY_TOOLS) + [mathtool.TOOL]
            fixed = estimate_tokens(system) + estimate_tokens(json.dumps(tools))
        kept = list(history)
        while len(kept) > 1 and fixed + sum(estimate_tokens(m["content"]) for m in kept) > budget:
            kept.pop(0)
        if kept and kept[0]["role"] == "assistant" and len(kept) > 1:
            kept.pop(0)
        last = kept[-1]
        room = budget - fixed - sum(estimate_tokens(m["content"]) for m in kept[:-1])
        if isinstance(last["content"], str) and estimate_tokens(last["content"]) > room:  # one giant message: keep its end
            kept[-1] = {"role": last["role"], "content": "…" + last["content"][-max(200, room * 3):]}
        return kept, tools

    def _run_tool(self, name, args):
        self.on_tool(name)
        usage.record(tool=name)
        try:
            if name == "remember":
                mem = store.remember(args.get("fact", ""))
                return f"saved as [{mem['id']}]" if mem else "already remembered (or empty)"
            if name == "forget":
                return "forgotten" if store.forget(str(args.get("id", ""))) else "no memory with that id"
            if name == "math":
                text = mathtool.run(args)
                log.info("math %s -> %s", args, text)
                return text
            text = self.roblox.call(name, args) if self.roblox else "ERROR: unknown tool"
        except Exception as e:
            text = f"ERROR: {e}"
        if len(text) > MAX_TOOL_OUTPUT:
            text = text[:MAX_TOOL_OUTPUT] + "\n...(cut off)"
        return text

    def chat(self, chat_id, text, voice=False, on_text=None, stop=None, image=None, image_label="", on_reset=None):
        chat = store.load_chat(chat_id) or store.new_chat(chat_id)
        history = [{"role": m["role"], "content": m["content"]} for m in chat["messages"][window_start(len(chat["messages"])):]]
        recent = " ".join(str(m["content"]) for m in history[-4:])
        topic = recent + " " + text
        mode = self.settings.get("mode") or ("fast" if self.settings.get("fast_mode") else "auto")
        way = router.route(text, mode, recent, voice)
        self.last_route = way
        log.info("%s", way)
        self.on_route(way)
        prompt = text
        notes = []
        if way.kind in ("valorant", "live"):
            chat["match"] = router.update_match(chat.get("match"), text)
            if way.kind == "live":
                notes.append(router.describe_match(chat["match"]))
        tags = set(way.tags)
        chosen = knowledge.pick(self.knowledge, text + " " + (recent[-600:] if way.kind != "chat" else ""), tags,
                                budget=1000 if voice or way.kind == "live" else 5000) if tags or way.kind != "chat" else []
        low = (text + " " + recent[-300:]).lower()
        extra = [sk["text"] for sk in self.skills if sk["keywords"] != [""] and any(k in low for k in sk["keywords"])]
        if chosen or extra:
            notes.insert(0, "(Your notes for this — use them, don't quote them:\n" + "\n\n".join(
                ([knowledge.render(chosen)] if chosen else []) + extra) + ")")
        if way.math_tool:
            done = mathtool.precompute(text)
            if done:
                self.on_tool("math")
                usage.record(tool="math")
                notes.append("(Calculator results for this message — exact, use these numbers: " +
                             "; ".join(f"{q} → {a}" for q, a in done) + ")")
        if way.note:
            notes.append(way.note)
        if voice:
            notes.append("(Voice call, transcribed from my voice, so ignore missing punctuation. Answer first, in 1-3 "
                         "short spoken sentences. No intro, no filler like \"Sure!\" or \"Great question\", don't repeat "
                         "my question, no emojis, lists, code, LaTeX or markdown. More detail only if I ask.)")
        if notes:
            prompt += "\n\n" + "\n\n".join(notes)
        earlier = [m["content"] for m in history if m["role"] == "assistant"][-4:]
        if earlier:
            # small brains love to paste their last reply again; a nudge right next to the message helps most
            prompt += "\n\n(Reply to exactly this message. Don't reuse lines from your earlier replies, and don't open with \"Ayy\", \"Yo\" or my name.)"
        if not image and re.search(r"\b(see|look at|seeing)\b.*\bscreen\b", text, re.I):
            prompt += "\n\n(I'm not sharing my screen right now, so you can't see it. Tell me to hit the share screen button.)"
        if image:
            # a picture of what they're sharing right now; only the newest one is sent, to keep it quick
            prompt += f"\n\n(I'm sharing my screen with you: {image_label or 'my screen'}. The picture is what's on it right now.)"
            history.append({"role": "user", "content": [{"type": "text", "text": prompt},
                                                        {"type": "image_url", "image_url": {"url": image}}]})
        else:
            history.append({"role": "user", "content": prompt})
        limit = way.max_tokens
        started, first = time.time(), [None]

        def stream_text(piece):
            if first[0] is None:
                first[0] = time.time()
            if on_text:
                on_text(piece)

        system = self._system(topic)
        history, tools = self._fit(system, history, self._tools(topic))
        try:
            reply, stopped = self.backend.answer(system, history, tools, self._run_tool,
                                                 stream_text, stop, max_tokens=limit, temperature=way.temperature)
        except Exception as e:
            if "exceed_context_size" not in str(e) and "context" not in str(e).lower():
                raise
            log.warning("Still too long for the brain, retrying short: %s", e)  # guesses were off; go minimal
            reply, stopped = self.backend.answer(self._system(), history[-2:], list(MEMORY_TOOLS), self._run_tool,
                                                 stream_text, stop, max_tokens=limit, temperature=way.temperature)
        # (not in voice calls: he's already saying it out loud, and a redo costs a whole reply of time)
        if not stopped and reply and not voice and _repeats(reply, earlier):
            # Still said the same thing as before: throw it away and try again, told plainly this time.
            log.info("Reply repeated an earlier one, retrying: %s", reply[:80])
            if on_reset:
                on_reset()
            last = history[-1]
            nudge = (f"\n\n(Your first try repeated what you said earlier: \"{short(reply, 120)}\". "
                     f"That's not allowed. Write a completely different reply that actually responds to: \"{text}\")")
            content = last["content"]
            if isinstance(content, list):
                content = [dict(content[0], text=content[0]["text"] + nudge)] + content[1:]
            else:
                content += nudge
            retry = history[:-1] + [{"role": "user", "content": content}]
            reply, stopped = self.backend.answer(system, retry, tools, self._run_tool, stream_text, stop,
                                                 max_tokens=limit, temperature=1.0)
        done = time.time()
        self.last_times = {"request": started, "first_token": first[0] or done, "done": done}
        self.last_stats = {"secs": round(done - started, 1),
                           "first": round((first[0] or done) - started, 1), "kind": way.kind}
        usage.record(chat=1, think=int(way.think), kind=way.kind,
                     read_tokens=sum(estimate_tokens(m["content"]) for m in history) + estimate_tokens(system),
                     written_tokens=estimate_tokens(reply or ""))
        log.info("Reply took %.1fs (first words after %.1fs)", done - started, (first[0] or done) - started)
        if not reply:
            reply = "(stopped)" if stopped else "💀 my brain blanked, say that again?"
        if not chat["messages"]:
            chat["title"] = store.title_from(text)
        chat["messages"] += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        chat["updated"] = time.time()
        store.save_chat(chat)
        return reply, chat, stopped
