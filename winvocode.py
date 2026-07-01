"""WinVoCode — Winamp-style voice-to-clipboard.

Click ⏺, talk, click ⏹: the transcript lands on your clipboard via Groq Whisper.

Run on Windows:  python winvocode.py
Needs:  pip install sounddevice soundfile pyperclip requests numpy
Key:    setx GROQ_API_KEY "gsk_..."   (then reopen the terminal)
"""
import os
import io
import threading

import numpy as np
import sounddevice as sd
import soundfile as sf
import pyperclip
import requests
import tkinter as tk

SAMPLE_RATE = 16000
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"

# ---- Winamp 2.x palette ----
STEEL    = "#23233b"   # window body
STEEL_D  = "#1a1a2c"   # darker panel
BEV_HI   = "#5c5c8a"   # bevel highlight (top/left)
BEV_LO   = "#0e0e18"   # bevel shadow (bottom/right)
GOLD     = "#d9b30c"   # title-bar lettering
LCD_BG   = "#000000"
LCD_GRN  = "#00e800"   # phosphor green
LCD_DIM  = "#054a05"
AMBER    = "#ffb000"
RED      = "#ff3b1f"

N_BARS = 19
N_SEG  = 10
BAR_GREEN, BAR_YEL, BAR_RED = "#00ff45", "#ffcc00", "#ff3b1f"
DIM_GREEN, DIM_YEL, DIM_RED = "#032e10", "#332b04", "#330f06"

IDLE_TEXT = "WINVOCODE *** VOICE TO CLIPBOARD *** GROQ WHISPER *** "


def transcribe(wav_bytes: bytes) -> str:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY NOT SET")
    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {key}"},
        files={"file": ("audio.wav", wav_bytes, "audio/wav")},
        data={"model": GROQ_MODEL},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("text", "").strip()


def seg_color(seg_idx, lit):
    frac = seg_idx / (N_SEG - 1)
    if frac > 0.8:
        return BAR_RED if lit else DIM_RED
    if frac > 0.55:
        return BAR_YEL if lit else DIM_YEL
    return BAR_GREEN if lit else DIM_GREEN


def bevel(parent, **kw):
    """A raised Winamp-style beveled frame."""
    f = tk.Frame(parent, bg=STEEL, bd=2, relief="raised",
                 highlightthickness=0, **kw)
    return f


class WinVoCode:
    def __init__(self, root):
        self.root = root
        self.frames = []
        self.stream = None
        self.latest = None
        self.bars = np.zeros(N_BARS)
        self.peaks = np.zeros(N_BARS)
        self.rec_ticks = 0            # elapsed 100ms ticks while recording
        self.marquee = IDLE_TEXT
        self.mq_pos = 0
        self.blink = False

        root.overrideredirect(True)   # no OS chrome — we draw our own
        root.configure(bg=BEV_LO)
        root.attributes("-topmost", True)

        body = tk.Frame(root, bg=STEEL, bd=2, relief="raised")
        body.pack(fill="both", expand=True, padx=1, pady=1)

        self._build_titlebar(body)
        self._build_lcd_cluster(body)
        self._build_mic_row(body)
        self._build_transport(body)

        # center on screen
        root.update_idletasks()
        w, h = root.winfo_width(), root.winfo_height()
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 3
        root.geometry(f"+{x}+{y}")

        self._tick()

    # ---- title bar ----
    def _build_titlebar(self, parent):
        tb = tk.Frame(parent, bg=STEEL_D, bd=1, relief="raised", height=22)
        tb.pack(fill="x", padx=2, pady=(2, 3))
        tb.pack_propagate(False)
        title = tk.Label(tb, text="◄ W I N V O C O D E ►",
                         font=("Small Fonts", 8, "bold") if os.name == "nt"
                         else ("Consolas", 9, "bold"),
                         fg=GOLD, bg=STEEL_D)
        title.pack(side="left", padx=8)
        close = tk.Label(tb, text="✕", font=("Consolas", 9, "bold"),
                         fg=GOLD, bg=STEEL_D, cursor="hand2", padx=6)
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self._quit())
        # drag anywhere on the bar
        for w in (tb, title):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _quit(self):
        if self.stream is not None:
            try:
                self.stream.stop(); self.stream.close()
            except Exception:
                pass
        self.root.destroy()

    # ---- LCD cluster: time + indicators + marquee + analyzer ----
    def _build_lcd_cluster(self, parent):
        lcd = tk.Frame(parent, bg=LCD_BG, bd=2, relief="sunken")
        lcd.pack(fill="x", padx=6, pady=(0, 4))

        top = tk.Frame(lcd, bg=LCD_BG)
        top.pack(fill="x", padx=6, pady=(6, 0))
        self.dot = tk.Label(top, text=" ", font=("Consolas", 16, "bold"),
                            fg=RED, bg=LCD_BG)
        self.dot.pack(side="left")
        self.time = tk.Label(top, text="00:00", font=("Consolas", 22, "bold"),
                             fg=LCD_GRN, bg=LCD_BG)
        self.time.pack(side="left", padx=(2, 10))
        ind = tk.Frame(top, bg=LCD_BG)
        ind.pack(side="right")
        tk.Label(ind, text="16KHZ", font=("Consolas", 8, "bold"),
                 fg=LCD_GRN, bg=LCD_BG).pack(anchor="e")
        tk.Label(ind, text="MONO", font=("Consolas", 8, "bold"),
                 fg=LCD_GRN, bg=LCD_BG).pack(anchor="e")

        self.mq = tk.Label(lcd, text="", font=("Consolas", 10, "bold"),
                           fg=LCD_GRN, bg=LCD_BG, anchor="w", width=34)
        self.mq.pack(fill="x", padx=6, pady=(2, 4))

        self.W, self.H = 300, 72
        self.canvas = tk.Canvas(lcd, width=self.W, height=self.H, bg=LCD_BG,
                                highlightthickness=0)
        self.canvas.pack(padx=6, pady=(0, 6))
        self._init_bars()

    def _init_bars(self):
        self.rects = []
        gap = 4
        bw = (self.W - gap * (N_BARS + 1)) / N_BARS
        sh = (self.H - 6) / N_SEG
        for b in range(N_BARS):
            x0 = gap + b * (bw + gap)
            col = []
            for s in range(N_SEG):
                y1 = self.H - 3 - s * sh
                y0 = y1 - sh + 2
                col.append(self.canvas.create_rectangle(
                    x0, y0, x0 + bw, y1, fill=seg_color(s, False), width=0))
            self.rects.append(col)
        self.cap = [self.canvas.create_rectangle(0, 0, 0, 0, fill=AMBER, width=0)
                    for _ in range(N_BARS)]
        self._bw, self._gap, self._sh = bw, gap, sh

    # ---- mic row ----
    def _build_mic_row(self, parent):
        row = tk.Frame(parent, bg=STEEL)
        row.pack(fill="x", padx=6, pady=(0, 4))
        tk.Label(row, text="MIC", font=("Consolas", 8, "bold"),
                 fg=GOLD, bg=STEEL).pack(side="left", padx=(2, 6))
        # avoid headsets flipping into the tinny hands-free profile: let the
        # user pick any input device explicitly
        self.mic_map = self._input_devices()
        labels = list(self.mic_map.keys()) or ["(default)"]
        try:
            default_idx = sd.default.device[0]
        except Exception:
            default_idx = None
        default_label = next(
            (l for l, i in self.mic_map.items() if i == default_idx), labels[0])
        self.mic_var = tk.StringVar(value=default_label)
        self.mic_menu = tk.OptionMenu(row, self.mic_var, *labels)
        self.mic_menu.config(font=("Consolas", 8), fg=LCD_GRN, bg=STEEL_D,
                             activebackground="#2e2e4a", activeforeground=GOLD,
                             highlightthickness=0, bd=1, relief="raised", anchor="w")
        self.mic_menu["menu"].config(font=("Consolas", 8), fg=LCD_GRN, bg=STEEL_D,
                                     activebackground="#2e2e4a", activeforeground=GOLD)
        self.mic_menu.pack(side="left", fill="x", expand=True)

    def _input_devices(self):
        out = {}
        try:
            for i, d in enumerate(sd.query_devices()):
                if d.get("max_input_channels", 0) > 0:
                    out[f"{i}: {d['name']}"] = i
        except Exception:
            pass
        return out

    # ---- transport ----
    def _build_transport(self, parent):
        bar = tk.Frame(parent, bg=STEEL)
        bar.pack(pady=(2, 8))
        style = dict(font=("Consolas", 13, "bold"), width=6, bd=3,
                     relief="raised", bg=STEEL_D,
                     activebackground="#2e2e4a")
        self.btn_rec = tk.Button(bar, text="⏺", fg=RED,
                                 activeforeground=RED,
                                 command=self.start, **style)
        self.btn_rec.pack(side="left", padx=3)
        self.btn_stop = tk.Button(bar, text="⏹", fg=LCD_GRN,
                                  activeforeground=LCD_GRN, state="disabled",
                                  command=self.stop, **style)
        self.btn_stop.pack(side="left", padx=3)

    # ---- recording ----
    def start(self):
        self.frames = []
        device = self.mic_map.get(self.mic_var.get())
        try:
            self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                         dtype="float32", device=device,
                                         callback=self._on_audio)
            self.stream.start()
        except Exception as e:
            self.stream = None
            self._set_marquee(f"MIC ERROR *** {e} *** ")
            return
        self.rec_ticks = 0
        self.mic_menu.config(state="disabled")
        self.btn_rec.config(state="disabled", relief="sunken")
        self.btn_stop.config(state="normal")
        self._set_marquee("RECORDING *** SPEAK NOW *** ")

    def _on_audio(self, indata, frames, time_info, status):
        self.frames.append(indata.copy())
        self.latest = indata[:, 0].copy()

    def stop(self):
        self.stream.stop(); self.stream.close(); self.stream = None
        self.latest = None
        self.mic_menu.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_rec.config(relief="raised")
        self._set_marquee("TRANSCRIBING *** GROQ WHISPER *** ")
        audio = np.concatenate(self.frames) if self.frames else np.zeros((1, 1), "float32")
        threading.Thread(target=self._finish, args=(audio,), daemon=True).start()

    def _finish(self, audio):
        try:
            buf = io.BytesIO()
            sf.write(buf, audio, SAMPLE_RATE, format="WAV")
            text = transcribe(buf.getvalue())
            if text:
                pyperclip.copy(text)
                self._set_marquee("COPIED TO CLIPBOARD *** PASTE WITH CTRL+V *** ")
            else:
                self._set_marquee("NOTHING HEARD *** TRY AGAIN *** ")
        except Exception as e:
            self._set_marquee(f"ERROR *** {e} *** ")
        finally:
            self.root.after(0, lambda: self.btn_rec.config(state="normal"))

    def _set_marquee(self, text):
        def apply():
            self.marquee = text
            self.mq_pos = 0
        self.root.after(0, apply)

    # ---- spectrum ----
    def _spectrum(self):
        chunk = self.latest
        if chunk is None or len(chunk) < 64:
            return np.zeros(N_BARS)
        w = chunk * np.hanning(len(chunk))
        mag = np.abs(np.fft.rfft(w))
        idx = np.logspace(0, np.log10(len(mag) - 1), N_BARS + 1).astype(int)
        out = np.zeros(N_BARS)
        for i in range(N_BARS):
            a, b = idx[i], max(idx[i] + 1, idx[i + 1])
            out[i] = mag[a:b].mean()
        out = np.log10(out * 18 + 1)
        return np.clip(out / 2.2, 0, 1)

    # ---- 100ms UI heartbeat: analyzer, marquee scroll, clock, blink ----
    def _tick(self):
        target = self._spectrum()
        self.bars = np.where(target > self.bars, target, self.bars * 0.74)
        self.peaks = np.maximum(self.peaks - 0.03, self.bars)
        for b in range(N_BARS):
            lit = int(round(self.bars[b] * N_SEG))
            for s in range(N_SEG):
                self.canvas.itemconfig(self.rects[b][s],
                                       fill=seg_color(s, s < lit))
            ps = min(N_SEG - 1, int(self.peaks[b] * N_SEG))
            x0 = self._gap + b * (self._bw + self._gap)
            y1 = self.H - 3 - ps * self._sh
            self.canvas.coords(self.cap[b], x0, y1 - 2, x0 + self._bw, y1)

        # marquee scroll
        doubled = self.marquee + self.marquee
        self.mq.config(text=doubled[self.mq_pos:self.mq_pos + 34])
        self.mq_pos = (self.mq_pos + 1) % max(1, len(self.marquee))

        # clock + blinking rec dot
        if self.stream is not None:
            self.rec_ticks += 1
        m, s = divmod(self.rec_ticks // 10, 60)
        self.time.config(text=f"{m:02d}:{s:02d}")
        self.blink = not self.blink
        self.dot.config(text="●" if (self.stream is not None and self.blink) else " ")

        self.root.after(100, self._tick)


if __name__ == "__main__":
    root = tk.Tk()
    WinVoCode(root)
    root.mainloop()
