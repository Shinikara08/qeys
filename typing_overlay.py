"""
No-Look Typing Practice — global keyboard overlay.

Mirrors your REAL typing from any app/tab via a global keyboard hook,
draws an always-on-top QWERTY overlay that is drag-able and resizable,
highlights pressed keys instantly and fades them out slowly on release,
and shows a bar of what you've typed.

Run:
    pip install keyboard
    python typing_overlay.py

Controls:
    - Drag anywhere on the overlay to move it.
    - Drag the bottom-right corner grip to resize.
    - Click the ✕ (top-right) or press Esc (while overlay focused) to quit.

Notes:
    - On Windows the global hook works without admin for normal apps; to
      capture keys typed inside an ELEVATED app (run-as-admin), run this
      script as admin too.
"""

import sys
import time
import threading
import tkinter as tk

try:
    import keyboard
except ImportError:
    sys.exit("Missing dependency. Install it with:  pip install keyboard")

try:
    import pystray
    from PIL import Image, ImageDraw
    _HAS_TRAY = True
except ImportError:
    _HAS_TRAY = False  # app still runs, just without a tray icon

# ---------------------------------------------------------------- tunables
FADE_SECONDS = 0.9          # how long a key takes to fade after release (raise = slower)
FPS = 60
BG = "#0d1117"
PANEL = "#161b22"
BORDER = "#30363d"
BASE_KEY = (33, 38, 45)     # idle key fill
ACTIVE_KEY = (255, 176, 0)  # pressed key fill (amber)
TEXT_LIGHT = (201, 209, 217)
TEXT_DARK = (26, 26, 26)
HOME_MARK = "#1f6feb"

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

# ---------------------------------------------------------------- shared state (touched by hook thread)
_lock = threading.Lock()
_held = set()        # keyboard names currently physically held down
_buf = []            # typed characters
_running = True


def _on_key(event):
    """Runs in the `keyboard` listener thread — touch only plain data + lock."""
    name = event.name
    if not name:
        return
    if event.event_type == "down":
        with _lock:
            ctrl = "ctrl" in _held or "left ctrl" in _held or "right ctrl" in _held
            _held.add(name)
            if name == "a" and ctrl:        # Ctrl+A -> clear the whole bar
                _buf.clear()
            elif name == "space":
                _buf.append(" ")
            elif name == "backspace":
                if _buf:
                    _buf.pop()
            elif name == "enter":
                _buf.append(" ")
            elif len(name) == 1:
                _buf.append(name)
    elif event.event_type == "up":
        with _lock:
            _held.discard(name)


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
        self.root.overrideredirect(True)          # borderless
        self.root.wm_attributes("-topmost", True)  # always on top
        try:
            self.root.wm_attributes("-alpha", 0.7)
        except tk.TclError:
            pass

        w, h = 820, 320
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = sh - h - 80
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # per-key fade intensity, keyed by (row, col)
        self.intensity = {}
        # name -> list of key ids, to light all matching keys (e.g. both Shifts)
        self.name_to_ids = {}
        for ri, row in enumerate(ROWS):
            for ci, (_, name, _) in enumerate(row):
                self.intensity[(ri, ci)] = 0.0
                self.name_to_ids.setdefault(name, []).append((ri, ci))

        self.icon = None        # system tray icon

        # interaction zones (filled during draw)
        self.close_box = None   # (x1,y1,x2,y2)
        self.grip_box = None
        self._mode = None
        self._start = None

        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.root.bind("<Escape>", lambda e: self.quit())

        self._last = time.perf_counter()
        self.tick()

    # ---- mouse: move / resize / close
    def _zone(self, x, y):
        if self.close_box and _inside(x, y, self.close_box):
            return "close"
        if self.grip_box and _inside(x, y, self.grip_box):
            return "resize"
        return "drag"

    def on_press(self, e):
        self._mode = self._zone(e.x, e.y)
        self._start = (
            self.root.winfo_pointerx(), self.root.winfo_pointery(),
            self.root.winfo_x(), self.root.winfo_y(),
            self.root.winfo_width(), self.root.winfo_height(),
        )

    def on_drag(self, e):
        if not self._start:
            return
        px, py, wx, wy, ww, wh = self._start
        dx = self.root.winfo_pointerx() - px
        dy = self.root.winfo_pointery() - py
        if self._mode == "resize":
            self.root.geometry(f"{max(420, ww + dx)}x{max(190, wh + dy)}")
        elif self._mode == "drag":
            self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def on_release(self, e):
        if self._mode == "close" and self._zone(e.x, e.y) == "close":
            # minimize to tray if available, otherwise quit
            self.hide() if (self.icon and _HAS_TRAY) else self.quit()
        self._mode = None
        self._start = None

    # ---- frame
    def tick(self):
        if not _running:
            return
        now = time.perf_counter()
        dt = now - self._last
        self._last = now

        with _lock:
            held = set(_held)
            text = "".join(_buf)[-120:]

        decay = dt / FADE_SECONDS if FADE_SECONDS > 0 else 1.0
        for key, val in self.intensity.items():
            ri, ci = key
            name = ROWS[ri][ci][1]
            if name in held:
                self.intensity[key] = 1.0
            elif val > 0:
                self.intensity[key] = max(0.0, val - decay)

        self.draw(text)
        self.root.after(int(1000 / FPS), self.tick)

    def draw(self, text):
        c = self.canvas
        c.delete("all")
        W = self.root.winfo_width()
        H = self.root.winfo_height()
        M = 12
        c.create_rectangle(1, 1, W - 1, H - 1, outline=BORDER)

        # --- typed text bar ---
        bar_h = max(48, int(H * 0.17))
        round_rect(c, M, M, W - M, M + bar_h, 10, fill=PANEL, outline=BORDER)
        # close button
        cb = 22
        cx2, cy1 = W - M - 8, M + 8
        self.close_box = (cx2 - cb, cy1, cx2, cy1 + cb)
        round_rect(c, *self.close_box, 6, fill="#30262b", outline="#5a3a44")
        c.create_text((self.close_box[0] + self.close_box[2]) / 2,
                      (self.close_box[1] + self.close_box[3]) / 2,
                      text="✕", fill="#ff9aa6",
                      font=("Segoe UI", int(cb * 0.5), "bold"))
        # text (right-anchored so the newest is always visible)
        c.create_text(self.close_box[0] - 14, M + bar_h / 2,
                      text=text + "│", anchor="e", fill="#e6edf3",
                      font=("Consolas", int(bar_h * 0.42)))

        # --- keyboard ---
        gap = 6
        top = M + bar_h + gap
        kb_h = H - top - M
        unit = (W - 2 * M - gap * (GRID_UNITS)) / GRID_UNITS
        key_h = (kb_h - gap * (len(ROWS) - 1)) / len(ROWS)
        fsize = max(9, int(key_h * 0.3))

        for ri, row in enumerate(ROWS):
            row_units = sum(wgt for _, _, wgt in row)
            row_w = row_units * unit + gap * (len(row) - 1)
            x = (W - row_w) / 2
            y = top + ri * (key_h + gap)
            for ci, (label, name, wgt) in enumerate(row):
                kw = wgt * unit
                t = self.intensity[(ri, ci)]
                fill = blend(BASE_KEY, ACTIVE_KEY, t)
                outline = ACTIVE_KEY_HEX if t > 0.05 else BORDER
                round_rect(c, x, y, x + kw, y + key_h, 7, fill=fill, outline=outline)
                tcolor = blend(TEXT_LIGHT, TEXT_DARK, t)
                c.create_text(x + kw / 2, y + key_h / 2, text=label,
                              fill=tcolor, font=("Segoe UI", fsize))
                if name in ("f", "j"):  # home-row anchors
                    mw = kw * 0.3
                    my = y + key_h - 7
                    c.create_line(x + kw / 2 - mw / 2, my,
                                  x + kw / 2 + mw / 2, my,
                                  fill=HOME_MARK, width=3)
                x += kw + gap

        # --- resize grip (bottom-right) ---
        g = 16
        self.grip_box = (W - g - 4, H - g - 4, W - 4, H - 4)
        for i in range(3):
            off = i * 5
            c.create_line(W - 6 - off, H - 4, W - 4, H - 6 - off,
                          fill=BORDER, width=2)

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
                d.rounded_rectangle([rx, ry, rx + 6, ry + 6], radius=2,
                                    fill=(255, 176, 0, 255))
        d.rounded_rectangle([20, 40, 44, 44], radius=2, fill=(201, 209, 217, 255))
        return img

    def create_tray(self):
        if not _HAS_TRAY:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda: self.root.after(0, self.show), default=True),
            pystray.MenuItem("Hide", lambda: self.root.after(0, self.hide)),
            pystray.MenuItem("Quit", lambda: self.root.after(0, self.quit)),
        )
        self.icon = pystray.Icon("typing_overlay", self._tray_image(),
                                 "Typing Overlay", menu)
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
