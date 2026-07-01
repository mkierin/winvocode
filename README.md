# WinVoCode

A tiny **Winamp-styled voice-to-clipboard** tool for Windows. Click ⏺, talk, click ⏹ —
your speech is transcribed by [Groq Whisper](https://console.groq.com/) and dropped on your
clipboard. Paste anywhere with Ctrl+V.

Built live on YouTube with Claude Code (and Fable 5) as a total-beginner "zero → real app"
walkthrough. One file, ~5 dependencies, one free API key.

## What it does

1. **⏺ REC** captures your microphone (16 kHz mono).
2. **⏹ STOP** encodes the audio, sends it to Groq Whisper (`whisper-large-v3-turbo`), and
   copies the transcript to your clipboard.
3. A scrolling LCD marquee, elapsed-time display, and a 19-bar spectrum analyzer give it the
   classic Winamp 2.x look.

## Setup (Windows)

```powershell
# 1. install the dependencies
pip install -r requirements.txt

# 2. get a FREE key at https://console.groq.com/keys , then:
setx GROQ_API_KEY "gsk_your_key_here"
#    (reopen the terminal so the variable is picked up)

# 3. run it
python winvocode.py
```

The key is read **only** from the `GROQ_API_KEY` environment variable — never hardcoded,
never logged.

## Files

- `winvocode.py` — the whole app, single file.
- `SPEC.md` — the design spec it was built from.

## License

MIT
