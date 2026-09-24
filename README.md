# Flip 🐸🧢

Your own animated AI buddy that lives on your PC. Hype, funny, Gen Z, and a cracked Roblox dev.

## Get it

1. Go to **[Releases](../../releases/latest)** and download **Flip.exe**.
2. Double-click it.
   - If Windows says "Windows protected your PC", click **More info → Run anyway**. It shows up because the app isn't signed.
3. The first time, he downloads his brain (a few GB, one time only). After that he starts right away and works offline, except for his voice.

## What he can do

- **Chat**: type to him, or click the mic to say a message.
- **Voice chat**: tap the voice button next to the text box and just talk, like a phone call. Tap him to cut him off, and tap ✕ to hang up.
- **Memory**: he remembers things about you across every chat. Menu ☰ → 🧠 What I remember lets you see, add or delete memories.
- **Multiple chats**: menu ☰ shows all your chats. ✏️ starts a new one.
- **Desktop pet**: click the 🖥 button and he hops onto your desktop, always on top.
  - Hover over him: he waves and his eyes follow your mouse.
  - Drag him anywhere, and click him to open the chat.
  - Close the chat window and he stays on your desktop. Use the tray icon (by the clock) to open the chat, show or hide him, or quit.
- **Roblox Studio**: if you have the Roblox Studio MCP set up, he connects to Studio and can work on your game. The dot next to his name turns green when he's connected.

## His brain

Everything runs on your PC. Flip checks your graphics card and downloads the smartest model it can run:

| Graphics card memory | Brain |
|---|---|
| 14 GB or more | Qwen3 14B |
| 7–14 GB | Qwen3 8B |
| less, or no graphics card | Qwen3 4B |

## Change him

Menu ☰ → ⚙️ Settings sets his name, voice and Roblox connection. Everything else is in his folder (Settings → open my folder):

- `personality.txt`: how he talks and acts
- `settings.json`: all other settings (`llm_url` points him at LM Studio or Ollama instead of his built-in brain, and `local_model` sets a specific Hugging Face GGUF repo)
- `chats/`, `memory.json`: your chats and his memory
- `flip.log`, `brain.log`: send these to whoever is helping you if something breaks

## Build it yourself

GitHub builds `Flip.exe` automatically on every push to `main` (see `.github/workflows/build.yml`). To run it from source on Windows:

```
pip install -r requirements.txt
python app.py
```
