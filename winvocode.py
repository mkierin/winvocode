"""WinVoCode — voice-to-clipboard with switchable themes.

Three looks, one engine:
  • Winamp     — the classic skin: LCD clock, spectrum analyzer, ⏺ / ⏹ transport.
  • Pill       — minimal dark WhisperFlow-style pill: talk-timer, centered voice
                 bars, one button (click to start, click again to stop + transcribe).
  • Pill-Light — the same pill in a light/cream palette.

The pills use a per-pixel-alpha layered window (PIL + Win32) for genuinely smooth,
anti-aliased rounded corners. If that path is unavailable it falls back to a plain
transparent-color canvas pill. Toggle the look with ⇄ (cycles all three).

Run on Windows:  python winvocode.py
Needs:  pip install sounddevice soundfile pyperclip requests numpy pillow
Key:    set GROQ_API_KEY, or just click record once and paste your key into the
        prompt (stored locally in .groqkey). Get a free key at console.groq.com/keys
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

THEME_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".theme")
KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".groqkey")


def get_key():
    """Groq key from the GROQ_API_KEY env var, else the local .groqkey file."""
    k = os.environ.get("GROQ_API_KEY")
    if k and k.strip():
        return k.strip()
    try:
        k = open(KEY_FILE).read().strip()
        return k or None
    except Exception:
        return None


def save_key(k):
    try:
        with open(KEY_FILE, "w") as f:
            f.write(k.strip())
    except Exception:
        pass

# ---- Winamp 2.x palette ----
STEEL    = "#23233b"
STEEL_D  = "#1a1a2c"
GOLD     = "#d9b30c"
LCD_BG   = "#000000"
LCD_GRN  = "#00e800"
AMBER    = "#ffb000"
RED      = "#ff3b1f"

N_BARS = 19
N_SEG  = 10
BAR_GREEN, BAR_YEL, BAR_RED = "#00ff45", "#ffcc00", "#ff3b1f"
DIM_GREEN, DIM_YEL, DIM_RED = "#032e10", "#332b04", "#330f06"

# ---- Pill palettes (minimal, WhisperFlow-ish) ----
PILL_THEMES = {
    "pill": dict(bg="#17181f", edge="#2b2d3a", dim="#4a5064",
                 live="#f2f2fa", acc="#8a84ff", rec="#ff5b6e", status="#5a6076"),
    "pill-light": dict(bg="#f6f5ee", edge="#dcdacd", dim="#bdbbaf",
                       live="#24231d", acc="#5b4fe0", rec="#dd4d64", status="#9a988c"),
}
PILL_N_BARS = 16
TRANSP = "#ff00fe"

THEMES = ["winamp", "pill", "pill-light"]

# ---- optional smooth-corner stack (Windows layered window + PIL) ----
_WIN32_OK = False
try:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        _user32 = ctypes.windll.user32
        _gdi32 = ctypes.windll.gdi32

        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        ULW_ALPHA = 0x02
        AC_SRC_OVER = 0x00
        AC_SRC_ALPHA = 0x01
        GA_ROOT = 2

        class _BMIH(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        class _BMI(ctypes.Structure):
            _fields_ = [("bmiHeader", _BMIH), ("bmiColors", wintypes.DWORD * 3)]

        class _BLEND(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                        ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]

        class _POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class _SIZE(ctypes.Structure):
            _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]

        _user32.GetWindowLongW.restype = wintypes.LONG
        _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        _user32.SetWindowLongW.restype = wintypes.LONG
        _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        _user32.GetAncestor.restype = wintypes.HWND
        _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        _user32.GetDC.restype = wintypes.HDC
        _user32.GetDC.argtypes = [wintypes.HWND]
        _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        _user32.UpdateLayeredWindow.restype = wintypes.BOOL
        _user32.UpdateLayeredWindow.argtypes = [
            wintypes.HWND, wintypes.HDC, ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE),
            wintypes.HDC, ctypes.POINTER(_POINT), wintypes.DWORD,
            ctypes.POINTER(_BLEND), wintypes.DWORD]
        _gdi32.CreateCompatibleDC.restype = wintypes.HDC
        _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        _gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        _gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC, ctypes.POINTER(_BMI), wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        _gdi32.SelectObject.restype = wintypes.HGDIOBJ
        _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        _gdi32.DeleteDC.argtypes = [wintypes.HDC]
        _WIN32_OK = True
except Exception:
    _WIN32_OK = False

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except Exception:
    _PIL_OK = False


def transcribe(wav_bytes: bytes) -> str:
    key = get_key()
    if not key:
        raise RuntimeError("NO GROQ API KEY")
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


def load_theme():
    try:
        t = open(THEME_FILE).read().strip()
        return t if t in THEMES else "winamp"
    except Exception:
        return "winamp"


def save_theme(theme):
    try:
        with open(THEME_FILE, "w") as f:
            f.write(theme)
    except Exception:
        pass


def round_rect_pts(x0, y0, x1, y1, r):
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
            x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
            x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


def _hex(c):
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def _load_font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


class LayeredWindow:
    """Per-pixel-alpha top-level window — smooth AA content via UpdateLayeredWindow."""

    def __init__(self, hwnd, w, h):
        self.hwnd = hwnd
        self.w, self.h = w, h
        self.screen_dc = _user32.GetDC(None)
        self.mem_dc = _gdi32.CreateCompatibleDC(self.screen_dc)
        bmi = _BMI()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BMIH)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h            # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0        # BI_RGB
        self.bits = ctypes.c_void_p()
        self.hbmp = _gdi32.CreateDIBSection(self.screen_dc, ctypes.byref(bmi), 0,
                                            ctypes.byref(self.bits), None, 0)
        self.old = _gdi32.SelectObject(self.mem_dc, self.hbmp)
        ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)

    def update(self, bgra, x, y):
        ctypes.memmove(self.bits, bgra, len(bgra))
        size = _SIZE(self.w, self.h)
        src = _POINT(0, 0)
        dst = _POINT(int(x), int(y))
        blend = _BLEND(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        _user32.UpdateLayeredWindow(self.hwnd, self.screen_dc, ctypes.byref(dst),
                                    ctypes.byref(size), self.mem_dc, ctypes.byref(src),
                                    0, ctypes.byref(blend), ULW_ALPHA)

    def destroy(self):
        try:
            _gdi32.SelectObject(self.mem_dc, self.old)
            _gdi32.DeleteObject(self.hbmp)
            _gdi32.DeleteDC(self.mem_dc)
            _user32.ReleaseDC(None, self.screen_dc)
            ex = _user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
            _user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)
        except Exception:
            pass


class WinVoCode:
    def __init__(self, root):
        self.root = root
        self.theme = load_theme()

        self.frames = []
        self.stream = None
        self.latest = None
        self.busy = False
        self.device = None
        self.mic_map = self._input_devices()
        self._pick_default_device()
        self.rec_ticks = 0
        self.status = "READY"
        self.blink = False
        self.bars = np.zeros(max(N_BARS, PILL_N_BARS))
        self.peaks = np.zeros(N_BARS)
        self.layered = None
        self._ctl_hits = []

        root.overrideredirect(True)
        root.attributes("-topmost", True)

        self._build()
        self._tick()

    # ================= theme scaffolding =================
    def _build(self):
        # tear down any layered pill state before rebuilding
        if self.layered is not None:
            self.layered.destroy()
            self.layered = None
            for seq in ("<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>"):
                self.root.unbind(seq)
        self._ctl_hits = []
        for w in self.root.winfo_children():
            w.destroy()

        if self.theme.startswith("pill"):
            self.pal = PILL_THEMES[self.theme]
            self._build_pill()
        else:
            try:
                self.root.wm_attributes("-transparentcolor", "")
            except Exception:
                pass
            self.root.configure(bg="#0e0e18")
            self._build_winamp()
            self._recenter()
        self._sync_ui()

    def _recenter(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"+{x}+{y}")

    def switch_theme(self):
        self.theme = THEMES[(THEMES.index(self.theme) + 1) % len(THEMES)]
        save_theme(self.theme)
        self._build()

    def _quit(self):
        if self.stream is not None:
            try:
                self.stream.stop(); self.stream.close()
            except Exception:
                pass
        if self.layered is not None:
            self.layered.destroy()
        self.root.destroy()

    def _drag_start(self, e):
        self._dx = e.x_root - self.root.winfo_x()
        self._dy = e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    # ================= WINAMP theme =================
    def _build_winamp(self):
        body = tk.Frame(self.root, bg=STEEL, bd=2, relief="raised")
        body.pack(fill="both", expand=True, padx=1, pady=1)
        self._winamp_titlebar(body)
        self._winamp_lcd(body)
        self._winamp_mic(body)
        self._winamp_transport(body)

    def _winamp_titlebar(self, parent):
        tb = tk.Frame(parent, bg=STEEL_D, bd=1, relief="raised", height=22)
        tb.pack(fill="x", padx=2, pady=(2, 3))
        tb.pack_propagate(False)
        title = tk.Label(tb, text="◄ W I N V O C O D E ►",
                         font=("Small Fonts", 8, "bold") if os.name == "nt"
                         else ("Consolas", 9, "bold"), fg=GOLD, bg=STEEL_D)
        title.pack(side="left", padx=8)
        close = tk.Label(tb, text="✕", font=("Consolas", 9, "bold"),
                         fg=GOLD, bg=STEEL_D, cursor="hand2", padx=6)
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self._quit())
        swap = tk.Label(tb, text="⇄", font=("Consolas", 9, "bold"),
                        fg=GOLD, bg=STEEL_D, cursor="hand2", padx=4)
        swap.pack(side="right")
        swap.bind("<Button-1>", lambda e: self.switch_theme())
        for w in (tb, title):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

    def _winamp_lcd(self, parent):
        lcd = tk.Frame(parent, bg=LCD_BG, bd=2, relief="sunken")
        lcd.pack(fill="x", padx=6, pady=(0, 4))
        top = tk.Frame(lcd, bg=LCD_BG)
        top.pack(fill="x", padx=6, pady=(6, 0))
        self.dot = tk.Label(top, text=" ", font=("Consolas", 16, "bold"), fg=RED, bg=LCD_BG)
        self.dot.pack(side="left")
        self.time = tk.Label(top, text="00:00", font=("Consolas", 22, "bold"),
                             fg=LCD_GRN, bg=LCD_BG)
        self.time.pack(side="left", padx=(2, 10))
        ind = tk.Frame(top, bg=LCD_BG)
        ind.pack(side="right")
        tk.Label(ind, text="16KHZ", font=("Consolas", 8, "bold"), fg=LCD_GRN, bg=LCD_BG).pack(anchor="e")
        tk.Label(ind, text="MONO", font=("Consolas", 8, "bold"), fg=LCD_GRN, bg=LCD_BG).pack(anchor="e")
        self.status_lbl = tk.Label(lcd, text="", font=("Consolas", 10, "bold"),
                                   fg=LCD_GRN, bg=LCD_BG, anchor="w", width=34)
        self.status_lbl.pack(fill="x", padx=6, pady=(2, 4))
        self.W, self.H = 300, 72
        self.canvas = tk.Canvas(lcd, width=self.W, height=self.H, bg=LCD_BG, highlightthickness=0)
        self.canvas.pack(padx=6, pady=(0, 6))
        self._init_winamp_bars()

    def _init_winamp_bars(self):
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

    def _winamp_mic(self, parent):
        row = tk.Frame(parent, bg=STEEL)
        row.pack(fill="x", padx=6, pady=(0, 4))
        tk.Label(row, text="MIC", font=("Consolas", 8, "bold"), fg=GOLD, bg=STEEL).pack(side="left", padx=(2, 6))
        labels = list(self.mic_map.keys()) or ["(default)"]
        cur = next((l for l, i in self.mic_map.items() if i == self.device), labels[0])
        self.mic_var = tk.StringVar(value=cur)
        self.mic_menu = tk.OptionMenu(row, self.mic_var, *labels, command=self._on_mic_change)
        self.mic_menu.config(font=("Consolas", 8), fg=LCD_GRN, bg=STEEL_D,
                             activebackground="#2e2e4a", activeforeground=GOLD,
                             highlightthickness=0, bd=1, relief="raised", anchor="w")
        self.mic_menu["menu"].config(font=("Consolas", 8), fg=LCD_GRN, bg=STEEL_D,
                                     activebackground="#2e2e4a", activeforeground=GOLD)
        self.mic_menu.pack(side="left", fill="x", expand=True)

    def _winamp_transport(self, parent):
        bar = tk.Frame(parent, bg=STEEL)
        bar.pack(pady=(2, 8))
        style = dict(font=("Consolas", 13, "bold"), width=6, bd=3,
                     relief="raised", bg=STEEL_D, activebackground="#2e2e4a")
        self.btn_rec = tk.Button(bar, text="⏺", fg=RED, activeforeground=RED,
                                 command=self.start, **style)
        self.btn_rec.pack(side="left", padx=3)
        self.btn_stop = tk.Button(bar, text="⏹", fg=LCD_GRN, activeforeground=LCD_GRN,
                                  state="disabled", command=self.stop, **style)
        self.btn_stop.pack(side="left", padx=3)

    def _on_mic_change(self, label):
        self.device = self.mic_map.get(label)

    # ================= PILL theme =================
    def _build_pill(self):
        self.PW, self.PH = 256, 60
        self.root.geometry(f"{self.PW}x{self.PH}")
        self.root.update_idletasks()

        # layout constants shared by both render paths
        self._pill_x0 = 84
        self._pill_x1 = self.PW - 44
        self._pill_step = (self._pill_x1 - self._pill_x0) / (PILL_N_BARS - 1)
        self._pill_yc = self.PH / 2
        cx = self.PW - 22
        # control hit boxes in window coords: ✕ top, ⇄ bottom
        self._ctl_hits = [(cx - 11, 9, cx + 11, 31, self._quit),
                          (cx - 11, self.PH - 31, cx + 11, self.PH - 9, self.switch_theme)]

        # try the smooth layered-window path first
        if _WIN32_OK and _PIL_OK:
            try:
                self.root.wm_attributes("-transparentcolor", "")
                hwnd = _user32.GetAncestor(self.root.winfo_id(), GA_ROOT)
                self.layered = LayeredWindow(hwnd, self.PW, self.PH)
                self._f_time = _load_font(["segoeui.ttf", "consola.ttf"], 15 * 3)
                self._f_status = _load_font(["segoeui.ttf", "consola.ttf"], 8 * 3)
                self._f_ctl = _load_font(["seguisym.ttf", "segoeui.ttf"], 11 * 3)
            except Exception:
                self.layered = None

        self._moved = False
        self._consumed = False
        self._recenter()

        if self.layered is not None:
            self.root.bind("<ButtonPress-1>", self._pill_press)
            self.root.bind("<B1-Motion>", self._pill_motion)
            self.root.bind("<ButtonRelease-1>", self._pill_release)
            self._render_pill(False)
        else:
            self._build_pill_canvas()

    # ---- fallback: transparent-color canvas pill (jaggy corners, always works) ----
    def _build_pill_canvas(self):
        pal = self.pal
        try:
            self.root.wm_attributes("-transparentcolor", TRANSP)
        except Exception:
            pass
        self.root.configure(bg=TRANSP)
        self.canvas = tk.Canvas(self.root, width=self.PW, height=self.PH,
                                bg=TRANSP, highlightthickness=0, cursor="hand2")
        self.canvas.pack()
        m, r = 3, 27
        self.canvas.create_polygon(round_rect_pts(m, m, self.PW - m, self.PH - m, r),
                                   smooth=True, fill=pal["bg"], outline=pal["edge"], width=1)
        self.pill_time = self.canvas.create_text(30, self._pill_yc, text="0:00", anchor="w",
                                                 font=("Consolas", 15, "bold"), fill=pal["acc"])
        self.pill_bars = []
        for i in range(PILL_N_BARS):
            x = self._pill_x0 + i * self._pill_step
            self.pill_bars.append(self.canvas.create_line(
                x, self._pill_yc - 2, x, self._pill_yc + 2, width=3, fill=pal["dim"], capstyle="round"))
        self.pill_status = self.canvas.create_text(
            (self._pill_x0 + self._pill_x1) / 2, self.PH - 13, text="", anchor="center",
            font=("Consolas", 7), fill=pal["status"])
        for (x0, y0, x1, y1, cmd) in self._ctl_hits:
            self._canvas_ctl(x0, y0, x1, y1, cmd)
        self.canvas.bind("<ButtonPress-1>", self._pill_press)
        self.canvas.bind("<B1-Motion>", self._pill_motion)
        self.canvas.bind("<ButtonRelease-1>", self._pill_release)

    def _canvas_ctl(self, x0, y0, x1, y1, cmd):
        pal = self.pal
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        glyph = "✕" if cmd == self._quit else "⇄"
        tag = f"ctl{int(cy)}"
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=pal["bg"], outline="", tags=tag)
        self.canvas.create_text(cx, cy, text=glyph, font=("Consolas", 9, "bold"),
                                fill=pal["dim"], tags=tag)

        def hit(_e):
            self._consumed = True
            cmd()
            return "break"
        self.canvas.tag_bind(tag, "<Button-1>", hit)
        self.canvas.tag_bind(tag, "<Enter>", lambda e: self.canvas.itemconfig(tag, fill=pal["acc"]))
        self.canvas.tag_bind(tag, "<Leave>", lambda e: self.canvas.itemconfig(tag, fill=pal["dim"]))

    # ---- pill mouse (shared by both paths) ----
    def _pill_press(self, e):
        self._moved = False
        self._press_x, self._press_y = e.x_root, e.y_root
        for (x0, y0, x1, y1, cmd) in self._ctl_hits:
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                self._consumed = True
                cmd()
                return
        self._drag_start(e)

    def _pill_motion(self, e):
        if abs(e.x_root - self._press_x) > 4 or abs(e.y_root - self._press_y) > 4:
            self._moved = True
        self._drag_move(e)

    def _pill_release(self, e):
        if self._consumed:
            self._consumed = False
            return
        if not self._moved:
            self.toggle()

    def toggle(self):
        if self.stream is None:
            self.start()
        else:
            self.stop()

    # ---- smooth pill render ----
    def _render_pill(self, rec):
        pal = self.pal
        SS = 3
        W, H = self.PW * SS, self.PH * SS
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        m, r = 3 * SS, 27 * SS
        d.rounded_rectangle([m, m, W - m, H - m], radius=r,
                            fill=_hex(pal["bg"]) + (255,),
                            outline=_hex(pal["edge"]) + (255,), width=max(1, SS))
        yc = H / 2
        col = _hex(pal["live"] if rec else pal["dim"]) + (255,)
        hw = 1.6 * SS
        for i in range(PILL_N_BARS):
            h = (2 + self.bars[i] * 22) * SS
            x = (self._pill_x0 + i * self._pill_step) * SS
            d.rounded_rectangle([x - hw, yc - h, x + hw, yc + h], radius=hw, fill=col)
        mm, ss = divmod(self.rec_ticks // 10, 60)
        if self._f_time:
            d.text((30 * SS, yc), f"{mm}:{ss:02d}", font=self._f_time,
                   fill=_hex(pal["rec"] if rec else pal["acc"]) + (255,), anchor="lm")
        if not rec:
            st = self._pill_status_text()
            if st and self._f_status:
                d.text(((self._pill_x0 + self._pill_x1) / 2 * SS, H - 12 * SS), st,
                       font=self._f_status, fill=_hex(pal["status"]) + (255,), anchor="mm")
        if self._f_ctl:
            cx = (self.PW - 22) * SS
            d.text((cx, 20 * SS), "✕", font=self._f_ctl, fill=_hex(pal["dim"]) + (255,), anchor="mm")
            d.text((cx, (self.PH - 20) * SS), "⇄", font=self._f_ctl, fill=_hex(pal["dim"]) + (255,), anchor="mm")

        img = img.resize((self.PW, self.PH), Image.LANCZOS)
        arr = np.asarray(img).astype(np.uint16)
        a = arr[..., 3]
        b = (arr[..., 2] * a // 255).astype(np.uint8)
        g = (arr[..., 1] * a // 255).astype(np.uint8)
        rr = (arr[..., 0] * a // 255).astype(np.uint8)
        bgra = np.dstack([b, g, rr, a.astype(np.uint8)]).tobytes()
        self.layered.update(bgra, self.root.winfo_x(), self.root.winfo_y())

    # ================= shared audio =================
    def _input_devices(self):
        out = {}
        try:
            for i, dv in enumerate(sd.query_devices()):
                if dv.get("max_input_channels", 0) > 0:
                    out[f"{i}: {dv['name']}"] = i
        except Exception:
            pass
        return out

    def _pick_default_device(self):
        try:
            self.device = sd.default.device[0]
        except Exception:
            self.device = None

    def start(self):
        if self.stream is not None or self.busy:
            return
        if get_key() is None:            # first run without a key → ask for one
            self._ask_key()
            return
        self.frames = []
        try:
            self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                         dtype="float32", device=self.device,
                                         callback=self._on_audio)
            self.stream.start()
        except Exception as e:
            self.stream = None
            self.status = f"MIC ERROR: {e}"
            self._sync_ui()
            return
        self.rec_ticks = 0
        self.status = "RECORDING"
        self._sync_ui()

    def _ask_key(self):
        """Tiny modal to paste + save a Groq API key into the local .groqkey file."""
        win = tk.Toplevel(self.root)
        win.title("Groq API Key")
        win.configure(bg=STEEL)
        win.attributes("-topmost", True)
        win.resizable(False, False)
        tk.Label(win, text="Paste your Groq API key", bg=STEEL, fg=GOLD,
                 font=("Consolas", 10, "bold")).pack(padx=16, pady=(14, 2))
        tk.Label(win, text="free key at console.groq.com/keys", bg=STEEL, fg="#9a988c",
                 font=("Consolas", 8)).pack(padx=16, pady=(0, 8))
        var = tk.StringVar()
        ent = tk.Entry(win, textvariable=var, show="•", width=42, font=("Consolas", 10),
                       bg=STEEL_D, fg=LCD_GRN, insertbackground=LCD_GRN, relief="sunken", bd=2)
        ent.pack(padx=16, pady=2)
        ent.focus_set()

        def do_save():
            k = var.get().strip()
            if k:
                save_key(k)
                self.status = "KEY SAVED — CLICK RECORD AGAIN"
                win.destroy()

        btns = tk.Frame(win, bg=STEEL)
        btns.pack(pady=(10, 14))
        style = dict(font=("Consolas", 9, "bold"), bg=STEEL_D, fg=GOLD,
                     activebackground="#2e2e4a", bd=2, width=8)
        tk.Button(btns, text="Save", command=do_save, **style).pack(side="left", padx=5)
        tk.Button(btns, text="Cancel", command=win.destroy, **style).pack(side="left", padx=5)
        ent.bind("<Return>", lambda e: do_save())
        win.update_idletasks()
        win.geometry(f"+{self.root.winfo_x()}+{self.root.winfo_y() + 72}")

    def _on_audio(self, indata, frames, time_info, status):
        self.frames.append(indata.copy())
        self.latest = indata[:, 0].copy()

    def stop(self):
        if self.stream is None:
            return
        try:
            self.stream.stop(); self.stream.close()
        except Exception:
            pass
        self.stream = None
        self.latest = None
        self.busy = True
        self.status = "TRANSCRIBING"
        self._sync_ui()
        audio = np.concatenate(self.frames) if self.frames else np.zeros((1, 1), "float32")
        threading.Thread(target=self._finish, args=(audio,), daemon=True).start()

    def _finish(self, audio):
        try:
            buf = io.BytesIO()
            sf.write(buf, audio, SAMPLE_RATE, format="WAV")
            text = transcribe(buf.getvalue())
            if text:
                pyperclip.copy(text)
                self.status = "COPIED — PASTE WITH CTRL+V"
            else:
                self.status = "NOTHING HEARD — TRY AGAIN"
        except Exception as e:
            self.status = f"ERROR: {e}"
        finally:
            self.root.after(0, self._after_finish)

    def _after_finish(self):
        self.busy = False
        self._sync_ui()

    def _sync_ui(self):
        rec = self.stream is not None
        if self.theme == "winamp" and hasattr(self, "btn_rec"):
            self.btn_rec.config(state="disabled" if (rec or self.busy) else "normal",
                                relief="sunken" if rec else "raised")
            self.btn_stop.config(state="normal" if rec else "disabled")
            self.mic_menu.config(state="disabled" if rec else "normal")

    # ================= spectrum =================
    def _spectrum(self, n):
        chunk = self.latest
        if chunk is None or len(chunk) < 64:
            return np.zeros(n)
        w = chunk * np.hanning(len(chunk))
        mag = np.abs(np.fft.rfft(w))
        idx = np.logspace(0, np.log10(len(mag) - 1), n + 1).astype(int)
        out = np.zeros(n)
        for i in range(n):
            a, b = idx[i], max(idx[i] + 1, idx[i + 1])
            out[i] = mag[a:b].mean()
        out = np.log10(out * 18 + 1)
        return np.clip(out / 2.2, 0, 1)

    # ================= 100ms heartbeat =================
    def _tick(self):
        self.blink = not self.blink
        if self.stream is not None:
            self.rec_ticks += 1
        if self.theme.startswith("pill"):
            self._tick_pill()
        else:
            self._tick_winamp()
        self.root.after(100, self._tick)

    def _tick_winamp(self):
        target = self._spectrum(N_BARS)
        self.bars[:N_BARS] = np.where(target > self.bars[:N_BARS], target, self.bars[:N_BARS] * 0.74)
        self.peaks = np.maximum(self.peaks - 0.03, self.bars[:N_BARS])
        for b in range(N_BARS):
            lit = int(round(self.bars[b] * N_SEG))
            for s in range(N_SEG):
                self.canvas.itemconfig(self.rects[b][s], fill=seg_color(s, s < lit))
            ps = min(N_SEG - 1, int(self.peaks[b] * N_SEG))
            x0 = self._gap + b * (self._bw + self._gap)
            y1 = self.H - 3 - ps * self._sh
            self.canvas.coords(self.cap[b], x0, y1 - 2, x0 + self._bw, y1)
        self.status_lbl.config(text=self.status[:34])
        m, s = divmod(self.rec_ticks // 10, 60)
        self.time.config(text=f"{m:02d}:{s:02d}")
        self.dot.config(text="●" if (self.stream is not None and self.blink) else " ")

    def _tick_pill(self):
        rec = self.stream is not None
        target = self._spectrum(PILL_N_BARS) if rec else np.zeros(PILL_N_BARS)
        self.bars[:PILL_N_BARS] = np.where(target > self.bars[:PILL_N_BARS],
                                           target, self.bars[:PILL_N_BARS] * 0.7)
        if self.layered is not None:
            try:
                self._render_pill(rec)
            except Exception:
                pass
        else:
            self._tick_pill_canvas(rec)

    def _tick_pill_canvas(self, rec):
        pal = self.pal
        color = pal["live"] if rec else pal["dim"]
        yc = self._pill_yc
        for i in range(PILL_N_BARS):
            h = 2 + self.bars[i] * 22
            x = self._pill_x0 + i * self._pill_step
            self.canvas.coords(self.pill_bars[i], x, yc - h, x, yc + h)
            self.canvas.itemconfig(self.pill_bars[i], fill=color)
        m, s = divmod(self.rec_ticks // 10, 60)
        self.canvas.itemconfig(self.pill_time, text=f"{m}:{s:02d}",
                               fill=pal["rec"] if rec else pal["acc"])
        self.canvas.itemconfig(self.pill_status, text="" if rec else self._pill_status_text())

    def _pill_status_text(self):
        s = self.status
        if s == "TRANSCRIBING":
            return "transcribing…"
        if s.startswith("COPIED"):
            return "copied ✓"
        if s.startswith("NOTHING"):
            return "nothing heard"
        if s.startswith("MIC ERROR") or s.startswith("ERROR"):
            return "error"
        return ""


if __name__ == "__main__":
    root = tk.Tk()
    WinVoCode(root)
    root.mainloop()
