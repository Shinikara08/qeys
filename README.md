# Typing Overlay — a no-look typing trainer

A lightweight, always-on-top **QWERTY keyboard overlay** for Windows that mirrors
your **real typing in any app or browser tab** in real time. Press a key anywhere and
it lights up amber on the overlay, then fades out slowly — so you can train your
fingers without ever looking down at the physical keyboard.

## Why it helps

Most typing tutors force you to type *into their box*. The problem with no-look
(touch) typing is that the moment you glance down to check a key, you break the
muscle-memory loop you're trying to build.

This tool flips that:

- **You keep working in your real apps** — write an email, code, chat — and the
  overlay shows what your hands are doing on a clean on-screen keyboard.
- **Glance up, not down.** Your eyes stay at screen level, where your real work is,
  instead of dropping to the keyboard.
- **The slow fade is the feedback.** A key stays lit briefly after you release it, so
  you can see the trail of what you just pressed and catch wrong-finger habits.
- **Home-row anchors (F & J)** are marked so you can re-orient your fingers by feel.
- **The typed-text bar** lets you confirm the words came out right *without* looking
  at the source app — pure verification by feel.

It's a practice aid, not a game: low-friction, runs in the tray, and gets out of your way.

## Features

- 🌐 **Global** — captures keystrokes from any window via a system-wide hook
- 📌 **Always-on-top**, borderless, semi-transparent overlay
- 🖱️ **Drag anywhere** to move · **bottom-right grip** to resize (keyboard rescales)
- 🔆 **Instant light-up, slow fade** on release (tunable)
- 🔤 **Typed-text bar** with word breaks; **Backspace** edits, **Ctrl+A** clears
- 🪟 **System tray icon** — Show / Hide / Quit; the ✕ button minimizes to tray
- 🏠 **F/J home-row markers** for blind finger placement

## Install & run

Requires **Python 3.8+** on Windows.

```bash
pip install keyboard pystray Pillow
python typing_overlay.py
```

### One-click launch (Windows)

Double-click **`Typing Overlay.vbs`** — it starts the app silently (no console
window) and drops it into the system tray.

> ⚠️ **Note on the `.vbs` launcher:** it runs cleanly on the machine where it was
> created. If you *download* or copy it to a **different** PC, Windows may show a
> "Security Warning" / SmartScreen prompt (it flags `.vbs` files that arrive from the
> internet), and some managed machines disable Windows Script Host entirely. On a new
> machine, prefer `python typing_overlay.py`. Nothing unsigned launches 100%
> dialog-free on Windows without a code-signing certificate.

## Controls

| Action | How |
|---|---|
| Move overlay | Drag anywhere on it |
| Resize | Drag the bottom-right corner grip |
| Clear text bar | `Ctrl+A` |
| Delete last char | `Backspace` |
| Minimize to tray | Click ✕ (top-right) |
| Show / Hide / Quit | Right-click the tray icon |
| Quit | `Esc` (while overlay focused) or tray → Quit |

## Tuning

Edit the constants at the top of [`typing_overlay.py`](typing_overlay.py):

| Constant | Default | Effect |
|---|---|---|
| `FADE_SECONDS` | `0.9` | Higher = slower fade-out after release |
| `-alpha` (in `__init__`) | `0.7` | Window opacity: `1.0` solid, lower = more see-through |
| `ACTIVE_KEY` | amber | Highlight color (RGB) |
| `FPS` | `60` | Redraw rate |

## Notes & caveats

- The global hook works without admin for normal apps. To capture keys typed inside an
  app you launched **as administrator**, run this script as administrator too.
- Letter case isn't reflected in the text bar (it shows the base key name); the goal is
  finger position, not exact text capture.
- Windows-only as written (uses the `keyboard` hook + Win32 tray). The Tkinter UI is
  cross-platform, but the global hook may need root/extra permissions on macOS/Linux.

## License

MIT — see [LICENSE](LICENSE).
