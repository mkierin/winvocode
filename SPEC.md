# WinVoCode — Spec v1

Voice → Groq Whisper → clipboard, skinned like classic Winamp 2.x.
Successor to `../voicepad` (v1, retro CRT look). Same core pipeline, new shell.

## What it does

1. Click **⏺** (REC) → captures the selected microphone (16 kHz mono float32).
2. Click **⏹** (STOP) → audio is encoded to WAV in memory, POSTed to the Groq
   Whisper API (`whisper-large-v3-turbo`), and the transcript is copied to the
   Windows clipboard.
3. Marquee shows status; you paste anywhere with Ctrl+V.

## Winamp look (the point of v2)

- **Borderless window** (`overrideredirect`) with its own title bar:
  beveled dark steel-blue, gold `WINVOCODE` title, working ✕ close button,
  draggable by the title bar. Always on top.
- **Marquee**: scrolling green-on-black LCD text strip (like the track title
  in Winamp). Shows status: `WINVOCODE *** VOICE TO CLIPBOARD ***`, `RECORDING`,
  `TRANSCRIBING`, `COPIED TO CLIPBOARD`, or the error text.
- **Big LCD time display**: `MM:SS` elapsed recording time, phosphor green,
  blinks a `●` while recording.
- **Spectrum analyzer**: 19 log-spaced bars, green→yellow→red segments with
  amber peak-hold caps, gravity fall. Idle = flat.
- **`16KHZ` / `MONO` indicators** lit in the LCD cluster (pure decoration,
  they state the actual capture format).
- **Transport row**: beveled ⏺ / ⏹ buttons Winamp-style (raised 3D bevels,
  pressed state). ⏹ disabled while idle, ⏺ disabled while recording.
- **MIC selector**: dropdown of all input devices (avoids Windows flipping a
  headset into the tinny hands-free profile — carried over from voicepad).
- Palette: window `#23233b` / bevels `#5c5c8a` light, `#0e0e18` dark,
  gold `#d9b30c`, LCD green `#00e800` on `#000000`.

## Non-goals

- No hotkeys, no tray icon, no settings file, no audio saved to disk.
- No streaming transcription; one-shot on stop.

## Tech

- **One file**: `winvocode.py`. Python 3.10+ on Windows.
- Deps: `sounddevice`, `soundfile`, `numpy`, `requests`, `pyperclip`, tkinter (stdlib).
- API key from env var `GROQ_API_KEY` only. Never hardcoded, never logged.
- Transcription runs on a worker thread; UI thread only touched via `root.after`.
- Errors (no key, mic busy, API failure) surface on the marquee, app keeps running.

## Run

```powershell
cd $env:USERPROFILE\WinVoCode
python winvocode.py
```

## Acceptance

- [ ] Window appears top-most, draggable, closable via ✕.
- [ ] REC → bars dance, timer counts, ● blinks.
- [ ] STOP → marquee `TRANSCRIBING`, then `COPIED TO CLIPBOARD`; Ctrl+V pastes the words spoken.
- [ ] Unset `GROQ_API_KEY` → marquee shows the error, no crash.
