"""Flip's brain: talks to the AI model on your PC, remembers things, and uses tools."""

import asyncio
import json
import logging
import threading
import time

import store

log = logging.getLogger("flip")

MAX_HISTORY = 30       # messages from the current chat the AI sees
MAX_TOOL_STEPS = 15    # tool uses per message before he stops
MAX_TOOL_OUTPUT = 8000 # characters of tool output the AI gets to see

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


class NoModelError(Exception):
    pass


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
                        {"name": t.name, "description": t.description or "",
                         "schema": _field(t, "input_schema", "inputSchema") or {"type": "object", "properties": {}}}
                        for t in (await session.list_tools()).tools
                    ]
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

    def answer(self, system, history, tools, run_tool, on_text=None, stop=None):
        """Runs the model (and any tools it asks for). Streams text through on_text as it's written.
        Returns (reply, stopped)."""
        messages = [{"role": "system", "content": system}] + history
        spec = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["schema"]}} for t in tools]
        shown = ""
        for _ in range(MAX_TOOL_STEPS):
            kwargs = {"model": self._pick_model(), "messages": messages, "stream": True}
            if spec:
                kwargs["tools"] = spec
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
        self.personality = personality.replace("{name}", self.name)
        self.skills = list(skills)
        self.on_tool = lambda name: None
        self.roblox = RobloxLink(settings["roblox_command"]) if settings.get("roblox_studio") else None

        self.backend = LocalBackend(local_url)

    def roblox_status(self):
        return self.roblox.status if self.roblox else "off"

    def _system(self):
        parts = [self.personality]
        if store.current:
            parts.append(f"You're talking to {store.current['name']} (that's the name on their profile).")
        mems = store.memories()
        if mems:
            parts.append("THINGS YOU REMEMBER ABOUT THE USER (from past chats):\n" +
                         "\n".join(f"- [{m['id']}] {m['text']}" for m in mems))
        else:
            parts.append("You don't remember anything about the user yet. Use the remember tool when you learn about them.")
        parts.extend(self.skills)
        # Only the date (not the time): keeping this text the same between messages lets the
        # brain reuse its work on the chat so far instead of re-reading everything each time.
        parts.append(time.strftime("Today is %A, %B %d %Y."))
        return "\n\n".join(parts)

    def _tools(self):
        tools = list(MEMORY_TOOLS)
        if self.roblox and self.roblox.status == "connected":
            tools += self.roblox.tools
        return tools

    def _run_tool(self, name, args):
        self.on_tool(name)
        try:
            if name == "remember":
                mem = store.remember(args.get("fact", ""))
                return f"saved as [{mem['id']}]" if mem else "already remembered (or empty)"
            if name == "forget":
                return "forgotten" if store.forget(str(args.get("id", ""))) else "no memory with that id"
            text = self.roblox.call(name, args) if self.roblox else "ERROR: unknown tool"
        except Exception as e:
            text = f"ERROR: {e}"
        if len(text) > MAX_TOOL_OUTPUT:
            text = text[:MAX_TOOL_OUTPUT] + "\n...(cut off)"
        return text

    def chat(self, chat_id, text, voice=False, on_text=None, stop=None):
        chat = store.load_chat(chat_id) or store.new_chat(chat_id)
        history = [{"role": m["role"], "content": m["content"]} for m in chat["messages"][-MAX_HISTORY:]]
        prompt = text
        if voice:
            prompt += ("\n\n(We're in a live voice call: answer in 1-2 short spoken sentences, "
                       "no code blocks, lists or emojis unless I ask.)")
        history.append({"role": "user", "content": prompt})
        reply, stopped = self.backend.answer(self._system(), history, self._tools(), self._run_tool, on_text, stop)
        if not reply:
            reply = "(stopped)" if stopped else "💀 my brain blanked, say that again?"
        if not chat["messages"]:
            chat["title"] = store.title_from(text)
        chat["messages"] += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        chat["updated"] = time.time()
        store.save_chat(chat)
        return reply, chat, stopped
