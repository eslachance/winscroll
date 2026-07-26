# winmiddle

> **AI disclaimer:** This project was fully AI-generated under the guidance of a veteran developer with 25 years of tech experience — but it *was* generated fully by AI.

**Windows-faithful middle-click autoscroll for Linux** — hold-to-scroll by default, with optional Windows click-to-toggle and modifier gates.

Primary target: **KDE Plasma (Wayland) on Arch-based distros** (Arch, CachyOS, EndeavourOS, …). The daemon can run elsewhere; overlay placement and per-app filters work best with the bundled KWin script.

## Install

### AUR (recommended)

```bash
# Release package
paru -S winmiddle
# or: yay -S winmiddle

# Tracking git main
paru -S winmiddle-git
```

Then finish session setup once:

```bash
winmiddle --setup
```

Log out and back in once (KWin only reapplies primary-selection on session start).

### From source

```bash
git clone https://github.com/eslachance/winscroll.git
cd winscroll
./install.sh
```

Uninstall from-source installs with `./uninstall.sh`. Packaged installs: `sudo pacman -R winmiddle` (or `winmiddle-git`).

## Settings UI

```bash
winmiddle-ui
# or: winmiddle --ui
```

Opens a Plasma-friendly PyQt6 app (also in the app launcher as **winmiddle**) to:

- Start / stop / restart the user daemon and enable it at login
- Configure activation, scroll speed, app lists, and mouse device
- Re-run setup steps (paste-kill, KWin script, mouse udev)

Closing the window keeps a system-tray icon; use **Quit** from the tray menu to exit the UI. The daemon keeps running as a systemd user service.

## Activation (config)

Prefer the settings UI above. The same options live in `~/.config/winmiddle/config.toml`:

```toml
[activation]
hold = true              # hold middle + move → scroll; release → stop; tap → native middle-click
toggle = false           # Windows click-to-toggle (click enter, click exit)
modifier = "none"        # none | ctrl | alt | shift | super
modifier_for = "both"    # which gestures need the modifier: toggle | hold | both
```

Examples:
- **Default (recommended):** hold only — tap closes tabs; hold+move scrolls.
- **Classic Windows:** `hold = false`, `toggle = true`
- **Ctrl+middle hold to scroll:** `hold = true`, `modifier = "ctrl"`, `modifier_for = "hold"`

## Architecture

```
Physical mouse ──grab──► winmiddled ──uinput──► virtual mouse ──► KWin/apps
                              │
                              ├─ hold+move → HOLD_AUTOSCROLL (default)
                              ├─ tap (toggle on) → AUTOSCROLL + overlay
                              ├─ drag when hold gated off → middle-drag passthrough
                              └─ focused Firefox/Chrome → full middle passthrough

KWin script ──DBus──► focus + cursor position (for overlay + app filters)
Paste-kill: KDE EnablePrimarySelection=false, GTK, Firefox prefs, Chrome flag
```

## Status / tuning

```bash
winmiddle-ui
systemctl --user status winmiddle
journalctl --user -u winmiddle -f
winmiddle --list-devices
```

Config: `~/.config/winmiddle/config.toml` (also edited by the settings UI)

```toml
[scroll]
drag_threshold_px = 50  # held move beyond this → hold-scroll (or Blender-style drag if hold off)
deadzone_px = 12

[apps]
native_middle = ["firefox", "google-chrome", ...]  # real Windows middle-click
passthrough = ["steam_app", "blender", ...]        # never intercept
require_scrollable = true                          # AT-SPI gate
```

## Requirements

- Python 3.11+ with `python-evdev` and `python-pyqt6`
- `layer-shell-qt` (origin glyph on Wayland)
- Permission to read your mouse + `/dev/uinput` (`winmiddle --setup` installs a generic `ID_INPUT_MOUSE` + uinput `uaccess`/`seat` rule so hot-plugged mice work without re-pinning VID/PID)
- KDE Plasma recommended (ships a KWin script for focus/cursor). Other DEs: daemon still autoscrolls, but overlay position / per-app filters degrade without a focus provider.

Optional: `python-gobject` + `at-spi2-core` for scrollable-under-cursor probing.

## Honest limits

- **True** Windows link/tab hit-testing only exists inside apps. Browsers are passthrough + native autoscroll so that stays correct.
- AT-SPI “scrollable” is best-effort; some UI (tabs, custom widgets) may still need the hold/tap split.
- Fullscreen games should stay on the passthrough list so camera-orbit binds keep working.

## License

MIT
