"""
Qeys — a no-look typing trainer.

An always-on-top QWERTY overlay that mirrors your REAL typing from any app or tab
via a global keyboard hook. Keys light up instantly and fade out slowly so you can
train touch typing without looking down. Includes a practice mode: type the target
sentence and watch your live WPM and accuracy.

Run:
    pip install keyboard pystray Pillow
    python qeys.py

Controls:
    - Type anywhere; the overlay mirrors it and scores you against the prompt.
    - Drag the overlay to move it; drag the bottom-right grip to resize.
    - Ctrl+A     restart the current prompt
    - Backspace  delete last character
    - ▸ button   skip to a new prompt   (or tray -> New prompt)
    - ✕ button   minimize to tray       (Esc / tray -> Quit to exit)

Notes:
    - On Windows the global hook works without admin for normal apps; to capture keys
      typed inside an ELEVATED app (run-as-admin), run this script as admin too.
"""

import os
import sys
import time
import random
import threading
import webbrowser
import tkinter as tk
import tkinter.font as tkfont

try:
    import keyboard
except ImportError:
    sys.exit("Missing dependency. Install it with:  pip install keyboard")

try:
    from PIL import Image, ImageDraw, ImageTk
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False  # logo badge disabled without Pillow

try:
    import pystray
    _HAS_TRAY = _HAS_PIL  # tray icon needs Pillow too
except ImportError:
    _HAS_TRAY = False

# ---------------------------------------------------------------- tunables
FADE_SECONDS = 0.9          # how long a key takes to fade after release (raise = slower)
FPS = 60
OPACITY = 0.7               # window opacity: 1.0 solid, lower = more see-through
BG = "#0d1117"
PANEL = "#161b22"
BORDER = "#30363d"
BASE_KEY = (33, 38, 45)     # idle key fill
ACTIVE_KEY = (255, 176, 0)  # pressed key fill (amber)
TEXT_LIGHT = (201, 209, 217)
TEXT_DARK = (26, 26, 26)
HOME_MARK = "#1f6feb"
COL_OK = "#3fb950"          # correctly typed character
COL_BAD = "#f85149"         # wrong character
COL_PENDING = "#6e7681"     # not yet typed
COL_CURSOR = "#ffffff"      # character at the cursor

# "Built by Qollab" badge — clicking it opens the agency site.
LOGO_URL = "https://jeffreyquemuel.cloud/qorex"
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "qo_union_explore.png")

# Practice prompts. Mix of pangrams, home-row drills and flowing sentences.
PROMPTS = [
    "the quick brown fox jumps over the lazy dog",
    "asdf jkl asdf jkl the home row anchors your hands",
    "pack my box with five dozen liquor jugs",
    "she sells sea shells by the sea shore",
    "type without looking down at your hands",
    "a quiet mind types faster than a busy one",
    "the keys you fear are the keys you must drill",
    "we shape our tools and then our tools shape us",
    "practice inside the open flow of your real work",
    "how vexingly quick daft zebras jump",
    "the five boxing wizards jump quickly",
    "jackdaws love my big sphinx of quartz",
]

# ---------------------------------------------------------------- layout
# rows of (label, keyboard-name, width-in-units)
ROWS = [
    [("`", "`", 1), ("1", "1", 1), ("2", "2", 1), ("3", "3", 1), ("4", "4", 1),
     ("5", "5", 1), ("6", "6", 1), ("7", "7", 1), ("8", "8", 1), ("9", "9", 1),
     ("0", "0", 1), ("-", "-", 1), ("=", "=", 1), ("⌫", "backspace", 2)],
    [("Tab", "tab", 1.5), ("Q", "q", 1), ("W", "w", 1), ("E", "e", 1), ("R", "r", 1),
     ("T", "t", 1), ("Y", "y", 1), ("U", "u", 1), ("I", "i", 1), ("O", "o", 1),
     ("P", "p", 1), ("[", "[", 1), ("]", "]", 1), ("\\", "\\", 1.5)],
    [("Caps", "caps lock", 1.75), ("A", "a", 1), ("S", "s", 1), ("D", "d", 1),
     ("F", "f", 1), ("G", "g", 1), ("H", "h", 1), ("J", "j", 1), ("K", "k", 1),
     ("L", "l", 1), (";", ";", 1), ("'", "'", 1), ("Enter", "enter", 2.25)],
    [("Shift", "shift", 2.25), ("Z", "z", 1), ("X", "x", 1), ("C", "c", 1),
     ("V", "v", 1), ("B", "b", 1), ("N", "n", 1), ("M", "m", 1), (",", ",", 1),
     (".", ".", 1), ("/", "/", 1), ("Shift", "shift", 2.75)],
    [("Ctrl", "ctrl", 1.5), ("Alt", "alt", 1.5), ("Space", "space", 7),
     ("Alt", "alt", 1.5), ("Ctrl", "ctrl", 1.5)],
]
GRID_UNITS = 15  # widest row, used to size one unit


def _pick_prompt(exclude):
    choices = [p for p in PROMPTS if p != exclude] or PROMPTS
    return random.choice(choices)


# ---------------------------------------------------------------- shared state
# Single dict, guarded by _lock, so the hook thread and UI thread never reassign it.
_lock = threading.Lock()
_state = {
    "held": set(),      # keyboard names currently physically held down
    "typed": [],        # characters typed against the current prompt
    "target": "",       # the current prompt
    "total": 0,         # gross characters entered (for accuracy)
    "errors": 0,        # wrong characters entered
    "start": None,      # perf_counter at first keystroke of this prompt
}
_running = True


def _restart_current():
    """Reset progress on the current prompt (called while holding _lock)."""
    _state["typed"].clear()
    _state["total"] = 0
    _state["errors"] = 0
    _state["start"] = None


def _on_key(event):
    """Runs in the `keyboard` listener thread — touch only _state under _lock."""
    name = event.name
    if not name:
        return
    if event.event_type == "up":
        with _lock:
            _state["held"].discard(name)
        return

    # key down
    with _lock:
        held = _state["held"]
        ctrl = any(k in held for k in ("ctrl", "left ctrl", "right ctrl"))
        held.add(name)

        if ctrl:                      # treat Ctrl+<key> as a shortcut, not text
            if name == "a":           # Ctrl+A -> restart this prompt
                _restart_current()
            return
        if name == "backspace":
            if _state["typed"]:
                _state["typed"].pop()
            return
        if name == "space":
            ch = " "
        elif name == "enter":
            return                    # prompts auto-advance; ignore Enter
        elif len(name) == 1:
            ch = name
        else:
            return                    # tab / shift / etc. — highlight only

        target = _state["target"]
        i = len(_state["typed"])
        if _state["start"] is None:
            _state["start"] = time.perf_counter()
        _state["typed"].append(ch)
        _state["total"] += 1
        if i < len(target) and ch != target[i]:
            _state["errors"] += 1


# ---------------------------------------------------------------- helpers
def blend(base, target, t):
    """Linear color blend -> '#rrggbb'. t in [0,1]."""
    r = int(base[0] + (target[0] - base[0]) * t)
    g = int(base[1] + (target[1] - base[1]) * t)
    b = int(base[2] + (target[2] - base[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ---------------------------------------------------------------- app
class Overlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Qeys")
        self.root.overrideredirect(True)           # borderless
        self.root.wm_attributes("-topmost", True)  # always on top
        try:
            self.root.wm_attributes("-alpha", OPACITY)
        except tk.TclError:
            pass

        w, h = 840, 340
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh - h - 80}")

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.text_font = tkfont.Font(family="Consolas", size=18)

        # Qollab badge image (loaded once, resized copies cached by size)
        self.logo_src = None
        self._logo_cache = {}
        if _HAS_PIL:
            try:
                self.logo_src = Image.open(LOGO_PATH).convert("RGBA")
            except Exception:
                self.logo_src = None

        # per-key fade intensity, keyed by (row, col)
        self.intensity = {(ri, ci): 0.0
                          for ri, row in enumerate(ROWS)
                          for ci in range(len(row))}

        # scoring / session stats
        self.last_wpm = 0.0
        self.last_acc = 100.0
        self.best_wpm = 0.0
        self.completed = 0
        with _lock:
            _state["target"] = _pick_prompt("")

        self.icon = None
        self.close_box = self.skip_box = self.grip_box = self.logo_box = None
        self._mode = None
        self._drag = None

        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.root.bind("<Escape>", lambda e: self.quit())

        self._last = time.perf_counter()
        self.tick()

    # ---- mouse: move / resize / buttons
    def _zone(self, x, y):
        if self.close_box and _inside(x, y, self.close_box):
            return "close"
        if self.skip_box and _inside(x, y, self.skip_box):
            return "skip"
        if self.logo_box and _inside(x, y, self.logo_box):
            return "logo"
        if self.grip_box and _inside(x, y, self.grip_box):
            return "resize"
        return "drag"

    def on_press(self, e):
        self._mode = self._zone(e.x, e.y)
        self._drag = (
            self.root.winfo_pointerx(), self.root.winfo_pointery(),
            self.root.winfo_x(), self.root.winfo_y(),
            self.root.winfo_width(), self.root.winfo_height(),
        )

    def on_drag(self, e):
        if not self._drag:
            return
        px, py, wx, wy, ww, wh = self._drag
        dx = self.root.winfo_pointerx() - px
        dy = self.root.winfo_pointery() - py
        if self._mode == "resize":
            self.root.geometry(f"{max(460, ww + dx)}x{max(210, wh + dy)}")
        elif self._mode == "drag":
            self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def on_release(self, e):
        if self._mode and self._zone(e.x, e.y) == self._mode:
            if self._mode == "close":
                self.hide() if (self.icon and _HAS_TRAY) else self.quit()
            elif self._mode == "skip":
                self.advance(record=False)
            elif self._mode == "logo":
                webbrowser.open(LOGO_URL)
        self._mode = None
        self._drag = None

    def _logo_photo(self, size):
        size = max(8, (int(size) // 2) * 2)   # quantize to limit cache growth
        if size not in self._logo_cache:
            img = self.logo_src.resize((size, size), Image.LANCZOS)
            self._logo_cache[size] = ImageTk.PhotoImage(img)
        return self._logo_cache[size]

    # ---- scoring
    def advance(self, record=True):
        """Record the finished prompt (if any) and load a new one."""
        with _lock:
            target, typed = _state["target"], list(_state["typed"])
            start, total, errors = _state["start"], _state["total"], _state["errors"]
            if record and target and len(typed) >= len(target):
                elapsed = (time.perf_counter() - start) if start else 0
                correct = sum(1 for i, ch in enumerate(typed)
                              if i < len(target) and ch == target[i])
                self.last_wpm = (correct / 5) / (elapsed / 60) if elapsed > 0.3 else 0
                self.last_acc = (1 - errors / total) * 100 if total else 100
                self.best_wpm = max(self.best_wpm, self.last_wpm)
                self.completed += 1
            _state["target"] = _pick_prompt(target)
            _restart_current()

    # ---- frame
    def tick(self):
        if not _running:
            return
        now = time.perf_counter()
        dt = now - self._last
        self._last = now

        with _lock:
            held = set(_state["held"])
            typed = list(_state["typed"])
            target = _state["target"]
            total, errors, start = _state["total"], _state["errors"], _state["start"]

        if target and len(typed) >= len(target):   # prompt finished
            self.advance(record=True)
            with _lock:
                typed = list(_state["typed"])
                target = _state["target"]
                total, errors, start = _state["total"], _state["errors"], _state["start"]

        decay = dt / FADE_SECONDS if FADE_SECONDS > 0 else 1.0
        for key, val in self.intensity.items():
            name = ROWS[key[0]][key[1]][1]
            if name in held:
                self.intensity[key] = 1.0
            elif val > 0:
                self.intensity[key] = max(0.0, val - decay)

        elapsed = (now - start) if start else 0
        correct = sum(1 for i, ch in enumerate(typed)
                      if i < len(target) and ch == target[i])
        wpm = (correct / 5) / (elapsed / 60) if elapsed > 0.5 else 0
        acc = (1 - errors / total) * 100 if total else 100

        self.draw(target, typed, wpm, acc)
        self.root.after(int(1000 / FPS), self.tick)

    def draw(self, target, typed, wpm, acc):
        c = self.canvas
        c.delete("all")
        W, H = self.root.winfo_width(), self.root.winfo_height()
        M = 12
        c.create_rectangle(1, 1, W - 1, H - 1, outline=BORDER)

        # --- top panel (prompt + stats) ---
        bar_h = max(74, int(H * 0.24))
        round_rect(c, M, M, W - M, M + bar_h, 10, fill=PANEL, outline=BORDER)

        cb = 22
        cy1 = M + 8
        # close button
        self.close_box = (W - M - 8 - cb, cy1, W - M - 8, cy1 + cb)
        round_rect(c, *self.close_box, 6, fill="#30262b", outline="#5a3a44")
        c.create_text((self.close_box[0] + self.close_box[2]) / 2,
                      (self.close_box[1] + self.close_box[3]) / 2,
                      text="✕", fill="#ff9aa6", font=("Segoe UI", int(cb * 0.5), "bold"))
        # skip button
        self.skip_box = (self.close_box[0] - 10 - cb, cy1, self.close_box[0] - 10, cy1 + cb)
        round_rect(c, *self.skip_box, 6, fill="#1d2a33", outline="#2f4858")
        c.create_text((self.skip_box[0] + self.skip_box[2]) / 2,
                      (self.skip_box[1] + self.skip_box[3]) / 2,
                      text="▸", fill="#79c0ff", font=("Segoe UI", int(cb * 0.55), "bold"))

        # brand
        c.create_text(M + 16, M + 16, text="Qeys", anchor="w",
                      fill="#444c56", font=("Segoe UI", 11, "bold"))

        # prompt line, sized to fit the panel width
        pad = 18
        room = W - 2 * M - 2 * pad
        size = max(11, int(bar_h * 0.34))
        self.text_font.configure(size=size)
        cw = self.text_font.measure("m")
        if cw * max(1, len(target)) > room and len(target):
            size = max(9, int(size * room / (cw * len(target))))
            self.text_font.configure(size=size)
            cw = self.text_font.measure("m")
        total_w = cw * len(target)
        x0 = (W - total_w) / 2
        py = M + bar_h * 0.46
        for i, ch in enumerate(target):
            if i < len(typed):
                col = COL_OK if typed[i] == ch else COL_BAD
            elif i == len(typed):
                col = COL_CURSOR
            else:
                col = COL_PENDING
            cx = x0 + i * cw + cw / 2
            c.create_text(cx, py, text=ch, font=self.text_font, fill=col)
            if i == len(typed):                      # cursor underline
                c.create_line(cx - cw / 2 + 1, py + size * 0.72,
                              cx + cw / 2 - 1, py + size * 0.72,
                              fill=ACTIVE_KEY_HEX, width=2)
            elif i < len(typed) and typed[i] != ch and ch == " ":
                c.create_line(cx - cw / 2 + 1, py + size * 0.72,
                              cx + cw / 2 - 1, py + size * 0.72,
                              fill=COL_BAD, width=2)

        # stats line
        stat = (f"WPM {wpm:5.0f}     ACC {acc:4.0f}%     "
                f"last {self.last_wpm:.0f} wpm / {self.last_acc:.0f}%     "
                f"best {self.best_wpm:.0f}     done {self.completed}")
        c.create_text(M + pad, M + bar_h * 0.82, text=stat, anchor="w",
                      fill="#8b949e", font=("Consolas", max(9, int(bar_h * 0.16))))

        # --- keyboard ---
        gap = 6
        top = M + bar_h + gap
        kb_h = H - top - M
        unit = (W - 2 * M - gap * GRID_UNITS) / GRID_UNITS
        key_h = (kb_h - gap * (len(ROWS) - 1)) / len(ROWS)
        fsize = max(9, int(key_h * 0.3))

        btm_x = btm_y = None
        for ri, row in enumerate(ROWS):
            row_units = sum(wgt for _, _, wgt in row)
            row_w = row_units * unit + gap * (len(row) - 1)
            x = (W - row_w) / 2
            y = top + ri * (key_h + gap)
            if ri == len(ROWS) - 1:        # left edge of the bottom (Ctrl) row
                btm_x, btm_y = x, y
            for ci, (label, name, wgt) in enumerate(row):
                kw = wgt * unit
                t = self.intensity[(ri, ci)]
                round_rect(c, x, y, x + kw, y + key_h, 7,
                           fill=blend(BASE_KEY, ACTIVE_KEY, t),
                           outline=ACTIVE_KEY_HEX if t > 0.05 else BORDER)
                c.create_text(x + kw / 2, y + key_h / 2, text=label,
                              fill=blend(TEXT_LIGHT, TEXT_DARK, t),
                              font=("Segoe UI", fsize))
                if name in ("f", "j"):               # home-row anchors
                    mw = kw * 0.3
                    my = y + key_h - 7
                    c.create_line(x + kw / 2 - mw / 2, my, x + kw / 2 + mw / 2, my,
                                  fill=HOME_MARK, width=3)
                x += kw + gap

        # --- Qollab badge (bottom-left, beside the left Ctrl key) ---
        self.logo_box = None
        if self.logo_src is not None and btm_x is not None:
            lsize = int(min(key_h, btm_x - M - 6))
            if lsize >= 16:
                lx = btm_x - 8 - lsize
                ly = btm_y + (key_h - lsize) / 2
                c.create_image(lx, ly, image=self._logo_photo(lsize), anchor="nw")
                self.logo_box = (lx, ly, lx + lsize, ly + lsize)

        # --- resize grip ---
        g = 16
        self.grip_box = (W - g - 4, H - g - 4, W - 4, H - 4)
        for i in range(3):
            off = i * 5
            c.create_line(W - 6 - off, H - 4, W - 4, H - 6 - off, fill=BORDER, width=2)

    # ---- tray / visibility
    def hide(self):
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.wm_attributes("-topmost", True)

    def _tray_image(self):
        img = Image.new("RGBA", (64, 64), (13, 17, 23, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([4, 16, 60, 48], radius=8,
                            fill=(33, 38, 45, 255), outline=(255, 176, 0, 255), width=2)
        for ry in (24, 33):
            for rx in range(12, 53, 10):
                d.rounded_rectangle([rx, ry, rx + 6, ry + 6], radius=2, fill=(255, 176, 0, 255))
        d.rounded_rectangle([20, 40, 44, 44], radius=2, fill=(201, 209, 217, 255))
        return img

    def create_tray(self):
        if not _HAS_TRAY:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda: self.root.after(0, self.show), default=True),
            pystray.MenuItem("Hide", lambda: self.root.after(0, self.hide)),
            pystray.MenuItem("New prompt", lambda: self.root.after(0, lambda: self.advance(record=False))),
            pystray.MenuItem("Quit", lambda: self.root.after(0, self.quit)),
        )
        self.icon = pystray.Icon("qeys", self._tray_image(), "Qeys — no-look typing", menu)
        threading.Thread(target=self.icon.run, daemon=True).start()

    def quit(self):
        global _running
        _running = False
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
        self.root.destroy()


ACTIVE_KEY_HEX = f"#{ACTIVE_KEY[0]:02x}{ACTIVE_KEY[1]:02x}{ACTIVE_KEY[2]:02x}"


def _inside(x, y, box):
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def main():
    keyboard.hook(_on_key)
    app = Overlay()
    app.create_tray()
    app.root.mainloop()


if __name__ == "__main__":
    main()
