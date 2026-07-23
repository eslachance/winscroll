# winmiddle

**Windows-faithful middle-click autoscroll for Linux** — built for people who are done with highlight-paste and hold-to-scroll half-measures.

On Windows, middle-click means:

1. **Click once** → enter autoscroll (origin glyph appears)
2. **Move** away from the origin → scroll; speed scales with distance
3. **Click again** → exit
4. **Never** paste whatever you highlighted three windows ago
5. In browsers: middle-click **links/tabs** still do link/tab things (app hit-testing)

That is what this project targets on Linux (especially **KDE Plasma Wayland** / CachyOS).

## Architecture

```
Physical mouse ──grab──► winmiddled ──uinput──► virtual mouse ──► KWin/apps
                              │
                              ├─ click (no drag) → AUTOSCROLL + overlay
                              ├─ drag past threshold → middle-drag passthrough
                              └─ focused Firefox/Chrome → full middle passthrough
                                                          (native Windows behavior)

KWin script ──DBus──► focus + cursor position (for overlay + app filters)
Paste-kill: KDE EnablePrimarySelection=false, GTK, Firefox prefs, Chrome flag
```

Hold-to-scroll tools (X11 `Evdev Wheel Emulation`, KDE “press middle to scroll”, Wayland-Wheeltani) are **not** Windows. This daemon implements the **click-to-autoscroll** state machine.

## Install (CachyOS / Arch / Plasma)

```bash
./install.sh
```

Then **log out and back in** once (KWin only reapplies primary-selection on session start).

```bash
systemctl --user status winmiddle
journalctl --user -u winmiddle -f
winmiddle --list-devices
```

Config: `~/.config/winmiddle/config.toml`

Uninstall: `./uninstall.sh`

## Requirements

- Python 3.11+ with `python-evdev` and `python-pyqt6`
- Permission to read your mouse + `/dev/uinput` (install.sh writes a udev `uaccess` rule)
- KDE Plasma recommended (ships a KWin script for focus/cursor). Other DEs: daemon still autoscrolls, but overlay position / per-app filters degrade without a focus provider.

## Tuning

```toml
[scroll]
drag_threshold_px = 6   # held move beyond this → Blender-style middle-drag
deadzone_px = 8
gain = 0.045
exponent = 1.35

[apps]
native_middle = ["firefox", "google-chrome", ...]  # real Windows middle-click
passthrough = ["steam_app", "blender", ...]        # never intercept
```

## Honest limits

- **True** Windows link/tab hit-testing only exists inside apps. Browsers are passthrough + native autoscroll so that stays correct.
- Everywhere else, winmiddle provides the Windows **autoscroll gesture** globally — which is what most “make middle click like Windows” requests actually want.
- Fullscreen games should stay on the passthrough list so camera-orbit binds keep working.

## License

MIT
