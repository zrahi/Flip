# Flip 🐸🧢

Your own animated AI buddy that lives on your PC. Hype, funny, Gen Z, and a cracked Roblox dev.

## Get it

1. Go to **[Releases](../../releases/latest)** and download **FlipSetup.exe**.
2. Run it. It installs Flip for you (no admin needed) and puts him on your desktop and Start menu.
   - If Windows says "Windows protected your PC", click **More info → Run anyway**. It shows up because the app isn't signed.
3. The first time, he downloads his brain (about 6 GB, one time only).
4. After that, updates come through the green **⬆ Update** button in Flip.

To remove him: Windows Settings → Apps → Installed apps → Flip → Uninstall. It asks whether to delete his brain and chats too.

## What he can do

- **Chat** like ChatGPT or Claude. His replies type out word by word, and **■ stop** cuts him off. ⚡ **Fast** gives short, quick replies.
- **Modes** (button at the top): ✨ Auto picks for you, ⚡ Fast, 🧠 Think (works it out carefully first), 🧮 Math (exact calculator + clean formulas), 🎯 Valorant (coach mode; short live callouts when you feed him the round: "Lotus, Phoenix, attack, 3.4k" → "2 A, one heaven"), 💻 Code (incl. Roblox/Luau).
- **Pictures and videos, free**: say "draw a…", "make a picture of…" or "make a video of…" (or pick 🎨 Image / 🎬 Video in the mode button). Drop in a picture and say "animate this", or say "now animate it" after he paints something. Pictures take a few seconds; videos take 1-3 minutes on free shared GPUs (Wan 2.2), which have a daily limit per person. When it's used up, he offers Google Flow or Kling (free daily videos) and copies your prompt. No account, no key, nothing extra to download. Every picture and video has a save button.
- **Know-how that stays current**: Flip's Valorant and Roblox notes live in `knowledge/*.md`. Drop your own `.md` files (like the latest patch notes, same `## Title` / `KEYS:` format) into his folder's `knowledge` folder and he uses them.
- **Voice chat**: tap the voice button next to the text box and just talk, like a phone call. He talks while he types, and you can talk over him to cut him off (or tap him). ✕ hangs up.
- **Sidebar**: new chat, search, 📌 pinned chats, and rename or delete chats. Click the chat name at the top to rename it.
- **Accounts + profiles**: log in with a username and password, then pick who's chatting. Every profile has its own chats and memory, plus an optional PIN.
- **Memory**: he remembers things about you across chats (your profile menu → 🧠 What I remember).
- **Valorant coach**: he knows the mechanics, economy and roles, and thinks like a pro.
- **Roblox dev**: with the Roblox Studio MCP set up, he connects to Studio and can work on your game.
- **Desktop pet**: 🖥 puts him on your desktop with no window around him.
  - Hover to see his buttons: 💬 chat, ✕ hide, 🎤 voice chat right from the desktop, 📌 keep him on top.
  - Tap him to poke him, and drag him anywhere.

## His brain

Everything runs on your PC. Flip checks your graphics card and downloads the smartest model it can run:

| Graphics card memory | Brain |
|---|---|
| 14 GB or more | Qwen3 14B |
| 7–14 GB | Qwen3 8B |
| less, or no graphics card | Qwen3 4B |

## Change him

Your profile menu → ⚙️ Settings sets his name, voice (cute, normal or deep) and Roblox connection. Everything else is in his folder (Settings → open my folder):

- `personality.txt`: how he talks and acts
- `skills/`: put `.txt` files here to teach him more (built in: Valorant)
- `settings.json`: all other settings (`llm_url` points him at LM Studio or Ollama instead of his built-in brain, and `local_model` sets a specific Hugging Face GGUF repo)
- `chats/`, `memory.json`: your chats and his memory
- `flip.log`, `brain.log`: send these to whoever is helping you if something breaks

## Build it yourself

GitHub builds `Flip.exe` automatically on every push to `main` (see `.github/workflows/build.yml`). To run it from source on Windows:

```
pip install -r requirements.txt
python app.py
```
