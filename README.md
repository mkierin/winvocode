# WinVoCode

A tiny voice-to-clipboard recorder for Windows. Click, talk, click again — your
speech is transcribed by [Groq Whisper](https://console.groq.com) and copied
straight to the clipboard, ready to paste with `Ctrl+V`.

Three switchable looks (toggle with the **⇄** button, it remembers your choice):

- **Winamp** — a classic 2.x skin with an LCD clock and spectrum analyzer.
- **Pill** — a minimal dark WhisperFlow-style pill: talk-timer, centered voice
  bars, one button (click to start, click again to stop + transcribe).
- **Pill-Light** — the same pill in a light/cream palette.

The pills use a per-pixel-alpha layered window for genuinely smooth, anti-aliased
rounded corners (falls back to a plain canvas pill if that path is unavailable).

## Setup

```bash
pip install sounddevice soundfile pyperclip requests numpy pillow
python winvocode.py
```

## Groq API key

You need a Groq API key (free at https://console.groq.com/keys). Two ways to add it:

1. **Environment variable** — `set GROQ_API_KEY=gsk_...` before launching, or
2. **In-app** — just click record the first time and paste your key into the
   prompt. It's saved locally to `.groqkey` (which is git-ignored, never committed).

## Usage

- **Record**: click ⏺ (Winamp) or click the pill. Click again (⏹ / the pill) to
  stop; the transcript lands on your clipboard.
- **Switch theme**: the ⇄ button.
- **Move the window**: drag the title bar (Winamp) or drag the pill.
- **Pick a mic**: the MIC dropdown in the Winamp skin.

## Rebuild it from the recipe (the interesting part)

This repo ships its own **spec recipe**: [`RECIPE.md`](RECIPE.md) — a distilled,
phase-ordered spec that a fresh AI agent can rebuild this entire app from,
without ever seeing this code. Paste the file into Claude Code and say
*"build this"*.

It was created with [spec2prod](https://github.com/mkierin/spec2prod)
(spec capture + spec distill) from the real build sessions, and it is
**cold-build verified**: a fresh agent with no context and no access to this
repo rebuilt all 6 files with 51/51 named functions and classes matching, and
independently re-derived the Groq API contract from the live docs.

The thesis: your prompts are the source code — stop throwing them away.
Don't just clone the app. Rebuild it, restyle it, make it yours.
