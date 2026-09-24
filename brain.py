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

    def answer(self, system, history, tools, run_tool):
        messages = [{"role": "system", "content": system}] + history
        spec = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["schema"]}} for t in tools]
        for _ in range(MAX_TOOL_STEPS):
            kwargs = {"model": self._pick_model(), "messages": messages}
            if spec:
                kwargs["tools"] = spec
            msg = self.client.chat.completions.create(**kwargs).choices[0].message
            if not msg.tool_calls:
                return clean_reply(msg.content or "")
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [{"id": c.id, "type": "function",
                                "function": {"name": c.function.name, "arguments": c.function.arguments}}
                               for c in msg.tool_calls],
            })
            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except ValueError:
                    args = {}
                messages.append({"role": "tool", "tool_call_id": call.id, "content": run_tool(call.function.name, args)})
        return "bro I did like 15 steps and got lost 😭 tell me to keep going"


# ---------- Flip himself ----------

class Brain:
    def __init__(self, settings, personality, local_url):
        self.name = settings["name"]
        self.personality = personality.replace("{name}", self.name)
        self.on_tool = lambda name: None
        self.roblox = RobloxLink(settings["roblox_command"]) if settings.get("roblox_studio") else None

        self.backend = LocalBackend(local_url)

    def roblox_status(self):
        return self.roblox.status if self.roblox else "off"

    def _system(self, voice):
        parts = [self.personality]
        mems = store.memories()
        if mems:
            parts.append("THINGS YOU REMEMBER ABOUT THE USER (from past chats):\n" +
                         "\n".join(f"- [{m['id']}] {m['text']}" for m in mems))
        else:
            parts.append("You don't remember anything about the user yet. Use the remember tool when you learn about them.")
        parts.append(time.strftime("Right now it's %A, %B %d %Y, %I:%M %p."))
        if voice:
            parts.append("You're in a live voice call right now. Reply in 1-2 short spoken sentences. "
                         "No code blocks, lists or emojis unless they ask.")
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

    def chat(self, chat_id, text, voice=False):
        chat = store.load_chat(chat_id) or store.new_chat(chat_id)
        history = [{"role": m["role"], "content": m["content"]} for m in chat["messages"][-MAX_HISTORY:]]
        history.append({"role": "user", "content": text})
        reply = self.backend.answer(self._system(voice), history, self._tools(), self._run_tool)
        reply = reply or "💀 my brain blanked, say that again?"
        if not chat["messages"]:
            chat["title"] = store.title_from(text)
        chat["messages"] += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        chat["updated"] = time.time()
        store.save_chat(chat)
        return reply, chat
