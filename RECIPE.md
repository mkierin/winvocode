# SPEC — WinVoCode

## 0. Runner contract
You are a fresh Claude session rebuilding "WinVoCode" from this spec with no prior
context. Fill every {{SLOT}} first (ask the user or infer from provided image).
Execute phases in order. After each phase, run its done-check before continuing.
Do not skip verification. When done, run the Verify loop in §5.

## 1. Intent
A tiny one-file Windows desktop app: click a button, talk, click again, and the
transcript lands on the clipboard. Voice → Groq Whisper (`whisper-large-v3-turbo`)
→ clipboard, no disk writes, no streaming. It is the v2 successor to an earlier
app called `voicepad` (retro CRT look, same pipeline) — the point of v2 is a
proper multi-theme skin (Winamp 2.x is the flagship look) and quality-of-life
features (settings panel, persisted mic/theme/key). North star: launch fast via
a slash command (`/wvc`), record, get clean text, paste anywhere — zero friction
for a non-technical user on Windows who has never opened a terminal before.

## 2. Architecture
- **Stack**: Python 3.10+, single file `winvocode.py`, runs under **Windows**
  Python (not WSL — WSL has no audio device access; the file lives on the
  Windows filesystem, e.g. under `%USERPROFILE%`, and is launched via
  `powershell.exe` from WSL, or directly from a Windows terminal).
- **Deps**: `sounddevice`, `soundfile`, `numpy`, `requests`, `pyperclip`,
  `pillow` (for the smooth-corner pill render), tkinter (stdlib).
- **Data model / key entities**: no persistent data beyond three tiny local
  state files written next to the script (all git-ignored): `.groqkey` (API
  key if entered in-app), `.theme` (last-used theme name), and a saved mic
  index/label (persisted via `save_mic`/`load_mic`). No audio is ever written
  to disk — captured audio stays in memory, is encoded to WAV bytes, POSTed,
  discarded.
- **Module map** (all in `winvocode.py`, ~940 lines):
  - `get_key()` / `save_key(k)` — read `GROQ_API_KEY` from env first, else
    from `.groqkey`; `save_key` persists what the user enters in-app.
  - `load_mic()` / `save_mic(idx)` — persist the chosen input device across
    launches (Windows likes to flip a headset into a tinny hands-free
    profile when the default device is used — always let the user pin one).
    File format for the persisted mic choice is unspecified by the original
    build (state file only, not inspected in the sessions) — a small JSON
    blob `{"index": int, "label": str}` is a reasonable choice (label lets
    you re-match the device by name if the index shifts after a
    reboot/replug). Added by the cold-build verify pass, not the sessions.
  - `transcribe(wav_bytes) -> str` — POST to Groq Whisper API
    (`https://api.groq.com/openai/v1/audio/transcriptions`, OpenAI-compatible
    multipart contract: `Authorization: Bearer <key>`, fields `file` +
    `model=whisper-large-v3-turbo`), parse `resp.json()["text"]`. **Do not
    guess this shape from memory when rebuilding** — confirm against
    console.groq.com/docs/speech-to-text (or current Groq docs) before
    writing the call; this exact contract was independently verified twice:
    once by reading it off Groq's live docs during the cold-build verify
    pass, and it matched the real shipped code almost verbatim.
  - `load_theme()` / `save_theme(theme)` — persist which of the 3 skins is
    active.
  - `round_rect_pts`, `_hex`, `_load_font` — small drawing/geometry helpers.
  - `class LayeredWindow` — wraps a Win32 per-pixel-alpha layered window
    (`UpdateLayeredWindow`) so the pill themes can have genuinely
    anti-aliased rounded corners instead of the jagged 1-bit
    `-transparentcolor` mask tkinter gives you natively.
  - `class WinVoCode` — the app. Key methods: `_build` (theme dispatch),
    `_build_winamp` / `_winamp_titlebar` / `_winamp_lcd` /
    `_init_winamp_bars` / `_winamp_mic` / `_winamp_transport` (Winamp skin),
    `_build_pill` / `_build_pill_canvas` / `_render_pill` (pill skins, shared
    by dark and light palettes), `start()` / `stop()` / `_finish(audio)` /
    `_on_audio(...)` (recording lifecycle — capture callback, stop, worker
    thread does the Groq call, `root.after` marshals results back to the UI
    thread), `_ask_key()` (first-run / settings key prompt), `_open_settings()`
    (gear panel: API key / theme / mic), `_tick` / `_tick_winamp` /
    `_tick_pill` (per-frame UI updates: timer, spectrum bars, blink).
- **Key decisions (with reasons)**:
  - **One file, no build step** — because the target user "has never opened
    a terminal" (v1/voicepad framing); a single `.py` you `python foo.py` is
    the lowest-friction distribution for a non-technical user.
  - **API key from env var OR in-app prompt, never hardcoded** — env var
    (`GROQ_API_KEY`) is the fast path for the author (injected per-launch by
    the `/wvc` slash command from a shared `.env`); the in-app prompt +
    `.groqkey` file exists so a stranger who clones the public repo can run
    it with zero setup beyond pasting a key. `.groqkey`/`.env`/`.theme` are
    git-ignored — confirmed clean before every push (`grep -n "gsk_"` swept
    for real keys, only the README placeholder matched).
  - **Transcription on a worker thread, UI only touched via `root.after`** —
    tkinter is not thread-safe; blocking the UI thread on the Groq HTTP call
    would freeze the window while "TRANSCRIBING" should be animating.
  - **Per-pixel-alpha layered window for the pill themes, not
    `-transparentcolor`** — `-transparentcolor` is a 1-bit mask (pixel fully
    transparent or fully opaque), so curved corners stair-step badly. PIL
    renders the pill at 3× then downsamples with Lanczos into a real alpha
    bitmap pushed via `UpdateLayeredWindow`, giving smooth corners. Falls
    back silently to the plain canvas pill if that Win32 path is
    unavailable on a given machine, so it never hard-crashes.
  - **Marquee (scrolling LCD text) removed from the Winamp theme** — user
    feedback: "remove the scrolling text as distracting." Status now shows
    on a static LCD line instead.
  - **Theme-shape bug → reset geometry on every theme switch** — the pill
    theme sets a fixed small window geometry; switching back to Winamp
    without clearing it left Winamp squished into the pill's footprint.
    Fix: `_recenter` now sizes off the *requested* (content) size, not the
    current window size, every time `_build` runs.
  - **Settings teardown must skip `Toplevel` windows** — `_build()` used to
    destroy all root children on theme switch, which also killed the
    settings panel (itself a `Toplevel`) if you changed theme from inside
    it. Fixed by excluding `Toplevel` instances from the teardown.
  - **rec_ticks resets in `stop()`, not on next-recording-start** — bug: the
    elapsed-time display froze at the previous recording's length between
    recordings because the counter only zeroed when a *new* recording
    began. Fixed so the timer snaps to `00:00` the instant you hit stop.
  - **Winamp skin sized down to "actually Winamp-sized"** — first pass was
    oversized (spectrum panel especially); shrunk spectrum `300×72→228×30`,
    LCD font `22pt→15pt`, transport buttons `13pt/width-6/bd-3→11pt/
    width-4/bd-2`, mic/status rows to 7–8pt, tighter paddings throughout, to
    match a real 90s Winamp footprint instead of "a poster."
  - **Public GitHub repo, `private` avoided as default only because a public
    repo already existed** — author explicitly asked to push; a repo
    `mkierin/winvocode` already existed publicly from an earlier push, so
    the build reconciled onto that history rather than creating a new one,
    preserving its existing `LICENSE`.

## 3. Slots (fill before building)
- `{{DESIGN:image}}` — three looks to reproduce, no screenshot bundled with
  this spec; infer from the description below. Ask the user for a reference
  image of classic Winamp 2.x (for the flagship skin) and a "WhisperFlow"-style
  minimal recording pill (for the other two) if photorealistic fidelity
  matters. Design intent, distilled from the sessions:
  - **Winamp** — borderless window (`overrideredirect`) with its own beveled
    dark-steel-blue title bar, gold `WINVOCODE` wordmark, working ✕ close,
    draggable by the title bar, always on top. Static (non-scrolling) LCD
    status line: `RECORDING` / `TRANSCRIBING` / `COPIED TO CLIPBOARD` / error
    text. LCD `MM:SS` elapsed timer in phosphor green, blinking `●` while
    recording. 19-bar log-spaced spectrum analyzer, green→yellow→red segments
    with amber peak-hold caps and gravity fall (flat when idle). `16KHZ` /
    `MONO` decorative-but-accurate format indicators. Beveled 3D ⏺/⏹ transport
    buttons (⏹ disabled idle, ⏺ disabled while recording). MIC dropdown.
    Palette: window `#23233b`, light bevel `#5c5c8a`, dark bevel `#0e0e18`,
    gold `#d9b30c`, LCD green `#00e800` on `#000000`. Compact — actually
    Winamp-sized, not oversized.
  - **Pill (dark)** — minimal WhisperFlow-style rounded pill: one button
    (click starts recording + resets/starts the talk-timer, click again stops
    + transcribes), centered voice-reactive bars, elapsed-time readout.
    Genuinely smooth anti-aliased rounded corners via the layered-window
    trick, not a same-color-corner fake.
  - **Pill-Light** — same pill, light/cream palette; dark text/bars on light
    (author flagged a bug where light-theme text stayed the wrong shade —
    ensure text/bar contrast is correct per-palette, not copy-pasted from dark).
  - A ⚙ settings button (both skins) opens a panel: change Groq API key,
    switch theme, pick default mic. Theme choice and mic choice persist
    across launches; the pill's old ⇄ theme-cycle button was replaced by ⚙
    once settings existed.
- `{{SECRET:GROQ_API_KEY}}` — Groq Cloud API key (free tier at
  console.groq.com/keys). Original sourced it from a shared `.env` outside the
  repo (`{{ENV_FILE_PATH}}`, e.g. a personal tools `.env`) and injected it as a
  process env var at launch time via the launcher; falls back to an in-app
  prompt that persists to `.groqkey` (gitignored) for anyone else running the
  app from a clean clone.
- `{{LAUNCH_DIR}}` — where the script lives on the Windows filesystem, e.g.
  `%USERPROFILE%\WinVoCode`. Must be Windows-native Python (audio device
  access does not work from WSL).
- `{{SLASH_COMMAND_NAME}}` — optional: a launcher command (original used
  `/wvc`) that pulls the key from the shared `.env`, sets it as a PowerShell
  env var, and launches `python winvocode.py` in the background from WSL.

## 4. Build sequence
### Phase 1 — Core recorder, Winamp skin, spec, working key pipeline
- Files: `winvocode.py`, `SPEC.md`, `requirements.txt`, `.gitignore` (created
  later, see Phase 2), `LICENSE`, `README.md`
- Do: Build one file with tkinter for the window (always-on-top,
  `overrideredirect` borderless with a custom Winamp-style title bar), a
  Record/Stop transport that captures mic audio via `sounddevice` at 16kHz
  mono, encodes to WAV in memory via `soundfile`, POSTs to the Groq Whisper
  API (`whisper-large-v3-turbo`) via `requests` on a worker thread, and copies
  the result to the clipboard via `pyperclip`. Read `GROQ_API_KEY` from the
  environment. Add the LCD marquee/status line, elapsed-time display, 19-bar
  spectrum analyzer, MIC device dropdown (persist choice — Windows can flip a
  headset into hands-free profile on the OS default device). Before building,
  check the target machine's Python + package install state and walk a
  first-time user through getting a free Groq key and setting the env var —
  this app assumes zero prior setup.
- Done-check: `python -m py_compile winvocode.py` passes on the Windows
  interpreter; launching the app opens a top-most, draggable Winamp-skinned
  window; clicking ⏺ animates the spectrum and starts the LCD timer; clicking
  ⏹ transitions the status through `TRANSCRIBING` to `COPIED TO CLIPBOARD` and
  Ctrl+V pastes real spoken words (this was verified against the live Groq
  API, not a mock, in the original build).

### Phase 2 — Theme system: dark pill + light pill, smooth corners, in-app key, publish
- Files: `winvocode.py` (major rewrite), `.gitignore`, `README.md`
- Do: Refactor into a shared audio engine plus a theme dispatch (`_build`
  picks `_build_winamp` or `_build_pill` by `self.theme`, loaded/saved via
  `load_theme`/`save_theme`). Remove the scrolling marquee from Winamp
  (replace with a static status line — it was reported as distracting). Add
  a minimal "pill" theme: one toggle button, centered voice bars, a
  talk-timer that resets on each new recording. Add a second "pill-light"
  palette variant. Implement smooth rounded corners for the pills via a
  `LayeredWindow` class wrapping Win32's per-pixel-alpha layered window API
  (PIL renders at 3× supersampling, downsamples with Lanczos, pushes via
  `UpdateLayeredWindow`); fall back to the plain canvas pill if that path
  isn't available. Fix the `pill-light` theme falling through to the Winamp
  tick handler (exact `==` check needed to become `startswith`). Add an
  in-app key entry dialog (`_ask_key`) so a key can be entered and saved to
  `.groqkey` instead of requiring an env var. Write `.gitignore` (ignore
  `.groqkey`, `.env`, `.theme`, `__pycache__`) and `README.md`. Before
  pushing to git: grep the diff for `gsk_` to confirm no real key is
  staged. Push to the public GitHub repo (reconcile onto existing history —
  don't clobber an existing `LICENSE`); add `pillow` to `requirements.txt`
  (needed for the smooth pill render, was missing).
- Done-check: all three themes launch without a traceback on the real
  Windows interpreter; toggling themes shows no stair-stepped/jagged pill
  corners; `git diff`/`git show` for the pushed commit contains no `gsk_`
  value outside the README placeholder; `requirements.txt` includes `pillow`.

### Phase 3 — Bugfix: talk-timer reset on stop
- Files: `winvocode.py`
- Do: `rec_ticks` was only zeroed when the *next* recording started, so the
  timer froze at the previous recording's length in between. Reset
  `rec_ticks` inside `stop()` instead, so both the Winamp and pill themes
  (which both read `rec_ticks // 10`) snap to `00:00` immediately on stop.
- Done-check: commit `a66d6262` — "Reset talk-timer to 0 when recording
  stops"; relaunch and confirm the display reads `00:00` right after ⏹, not
  the prior recording's length.

### Phase 4 — Settings panel, mic persistence, theme-shape bugfix, Winamp resize
- Files: `winvocode.py`
- Do: Fix a real bug first — the pill theme sets a fixed small window
  geometry (`256×60`), and switching back to Winamp never cleared it, so
  Winamp rendered squished into the pill's footprint; fix `_recenter` to
  size off the requested/content size on every `_build`, not the current
  window size. Add a ⚙ settings button (replacing the old ⇄ theme-cycle
  button on both Winamp titlebar and pill) opening a `Toplevel` panel for:
  changing the Groq API key, switching theme, and picking the default mic
  (persisted via `save_mic`/`load_mic`, read back by `_pick_default_device`).
  Fix teardown-on-theme-switch to skip `Toplevel` windows so opening the
  panel and then switching theme from inside it doesn't kill the panel.
  Finally, shrink the Winamp skin's oversized elements (author: "make it
  more 90s retro" — the first pass looked like "a poster"): spectrum
  `300×72→228×30`, LCD font `22pt→15pt`, transport buttons `13pt/width-6/
  bd-3→11pt/width-4/bd-2`, mic/status rows to 7–8pt, tighter padding.
- Done-check: switching Winamp→pill→Winamp preserves each theme's own
  correct window size (no squish); the gear panel opens on both skins,
  changing the mic there is remembered on next launch; the Winamp skin's
  on-screen footprint is visibly compact/retro, not oversized.

## 5. Verify loop (scored)
1. Build from this spec in a clean directory.
2. Diff against §6 Manifest: for each listed file, did the cold build produce
   it, with units (defs/classes/headers) matching by name/role? Run any test
   commands (there are none automated — `python -m py_compile` /
   `python -c "import ast; ast.parse(...)"` stand in for a test suite here;
   real verification is launching on Windows Python and exercising all three
   themes + a live Groq transcription).
3. **Score = fraction of manifest files reproduced with a matching outline.**
   List per-file misses explicitly. Do not round up.
4. For each gap, patch the phase or slot that caused it. Repeat. The spec is
   DONE only when a fresh agent reaches the target score (aim 100%; state the
   number).

## 6. Manifest (golden anchor — paste from git-anchor.py output)
- `.gitignore` (10 lines) — outline: `# secrets — never commit`; `# local
  state`; `# python`. Ignores `.groqkey`, `.env`, `.theme`, `__pycache__/`,
  `*.pyc`.
- `LICENSE` (21 lines) — preserved from the pre-existing public repo, not
  authored in these sessions.
- `README.md` (38 lines) — outline: `# WinVoCode`; `## Setup`; `## Groq API
  key`; `## Usage`. Documents the three themes, `pip install` line, and both
  key-setup paths (env var or in-app).
- `SPEC.md` (60 lines) — outline: `# WinVoCode — Spec v1`; `## What it does`;
  `## Winamp look (the point of v2)`; `## Non-goals`; `## Tech`; `## Run`;
  `## Acceptance`. This is the *author's own* forward spec, written in
  Phase 1 before any code — kept for cross-reference; this distilled SPEC.md
  supersedes it as the retroactive, build-order-anchored version.
- `requirements.txt` (6 lines): `sounddevice`, `soundfile`, `numpy`,
  `requests`, `pyperclip`, `pillow`.
- `winvocode.py` (938 lines) — outline (module-level): `get_key()`,
  `save_key(k)`, `load_mic()`, `save_mic(idx)`, `transcribe(wav_bytes)`,
  `seg_color(seg_idx, lit)`, `load_theme()`, `save_theme(theme)`,
  `round_rect_pts(...)`, `_hex(c)`, `_load_font(names, size)`; classes
  `LayeredWindow` (`__init__`, `update`, `destroy`) and `WinVoCode`
  (`__init__`, `_build`, `_recenter`, `switch_theme`, `_quit`, `_drag_start`,
  `_drag_move`, `_build_winamp`, `_winamp_titlebar`, `_winamp_lcd`,
  `_init_winamp_bars`, `_winamp_mic`, `_winamp_transport`, `_on_mic_change`,
  `_build_pill`, `_build_pill_canvas`, `_canvas_ctl`, `_pill_press`,
  `_pill_motion`, `_pill_release`, `toggle`, `_render_pill`,
  `_input_devices`, `_pick_default_device`, `start`, `_ask_key`,
  `_open_settings`, `_on_audio`, `stop`, `_finish`, `_after_finish`,
  `_sync_ui`, `_spectrum`, `_tick`, `_tick_winamp`, `_tick_pill`,
  `_tick_pill_canvas`, `_pill_status_text`).

_manifest: 6 files · ~1073 lines total (from git-anchor.py against the real
repo's 3 commits)._

## Provenance
Distilled with spec2prod (spec capture + spec distill) from the four real build
sessions that produced this app (2026-07-01 to 2026-07-08), cross-checked
against the repo's git history. The commits answer "what shipped when"; the
sessions answer "why it does X" — this recipe is the distilled golden path.
Note: the final session's changes (settings panel, mic persistence, theme-shape
fix, Winamp resize) shipped from the working tree without a matching commit —
Phase 4 is anchored to the session transcript, not a git commit.

## Verify loop result (2026-07-14)
Cold-build run: a fresh Claude session (sonnet, no prior context, this spec as
its entire prompt) built from this spec in
a clean directory, with no access to the
real project, no Windows/audio runtime, and instructed to verify the Groq
Whisper contract against real docs rather than guess.
- **Score: 6/6 manifest files reproduced** (`.gitignore`, `LICENSE`,
  `README.md`, `SPEC.md`, `requirements.txt`, `winvocode.py`).
- **Outline match: 51/51 named units** (11 module functions, `LayeredWindow`'s
  3 methods, `WinVoCode`'s 37 methods) present by name in the cold-built
  `winvocode.py`, confirmed via AST walk, not eyeballing.
- **API contract independently verified**: the cold-build agent looked up
  `console.groq.com/docs/speech-to-text` itself (WebSearch + WebFetch) rather
  than trusting this spec's prose, and produced a `transcribe()` that matches
  the real shipped `winvocode.py`'s implementation almost line-for-line
  (same endpoint, same auth header, same multipart fields, same response
  parse).
- **Static checks only**: `python -m py_compile` and `ast.parse` passed; no
  live Windows/tkinter/audio/Groq call was possible from WSL — this is an
  environment limitation, not a build gap, and is the correct honest ceiling
  for this verify pass.
- **Highest residual risk**: the `LayeredWindow` Win32 per-pixel-alpha path
  (smooth pill corners) was written from documented struct layout but never
  compiled/run against real `ctypes.windll` — untestable outside Windows.
  It fails safe (falls back to the jagged canvas pill on any exception), so
  a Windows-side smoke test is the one thing a human should still do before
  fully trusting this spec's Phase 2.
- **One spec gap found and patched**: the `.mic` persisted-device file format
  was never pinned by the original sessions; the module-map entry for
  `load_mic`/`save_mic` above now specifies a JSON blob so future rebuilds
  don't have to guess.
