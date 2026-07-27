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

That installs both the daemon (`winmiddle`) and the settings GUI (`winmiddle-ui`, also in the app launcher as **winmiddle**).

Then finish session setup once:

```bash
winmiddle --setup
# or open the GUI and use Setup there:
winmiddle-ui
```

Log out and back in once (KWin only reapplies primary-selection on session start).

### From source

```bash
git clone https://github.com/eslachance/winscroll.git
cd winscroll
./install.sh
```

`install.sh` installs `winmiddle`, `winmiddle-ui`, the desktop entry, and the icon under `~/.local`.

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
                              └─ browsers (hold): tap = native middle; hold = scroll

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
native_middle = ["firefox", "google-chrome", ...]  # tap=native; hold=scroll
passthrough = ["steam_app", "blender", ...]        # never intercept
require_scrollable = true                          # AT-SPI gate (skipped for native_middle)
```

## Requirements

- Python 3.11+ with `python-evdev` and `python-pyqt6`
- `layer-shell-qt` (origin glyph on Wayland)
- Permission to read your mouse + `/dev/uinput` (`winmiddle --setup` installs a generic `ID_INPUT_MOUSE` + uinput `uaccess`/`seat` rule so hot-plugged mice work without re-pinning VID/PID)
- KDE Plasma recommended (ships a KWin script for focus/cursor). Other DEs: daemon still autoscrolls, but overlay placement / per-app filters degrade without a focus provider.

Optional: `python-gobject` + `at-spi2-core` for scrollable-under-cursor probing.

## Honest limits

- **True** Windows link/tab hit-testing only exists inside apps. With hold mode, browser taps synthesize a real middle-click (close tab / open link); hold+move uses winmiddle scroll (Chromium’s own Wayland autoscroll is unreliable after tab switches).
- AT-SPI “scrollable” is best-effort and is skipped for `native_middle` apps; some UI (tabs, custom widgets) may still need the hold/tap split.
- Fullscreen games should stay on the passthrough list so camera-orbit binds keep working.

## Releasing a new version

Maintainers only. Goal: ship a tagged GitHub release **and** update both AUR packages so `paru -S winmiddle` gets the daemon **and** the settings GUI.

### What must ship with the GUI

An install is incomplete unless all of these are present:

| Piece | Where |
|---|---|
| CLI entry `winmiddle-ui` | `pyproject.toml` → `[project.scripts]` (`winmiddle.ui.app:main`) |
| UI package | `winmiddle/ui/` (included by hatch `packages = ["winmiddle"]`) |
| App launcher | `share/winmiddle.desktop` (`Exec=winmiddle-ui`, `Icon=winmiddle`) |
| Icon | `share/icons/hicolor/scalable/apps/winmiddle.svg` |
| Data install | `packaging/install-data.sh` copies desktop + icon into `/usr/share/...` |
| From-source | `install.sh` writes `~/.local/bin/winmiddle-ui` + desktop/icon |

Before tagging, sanity-check locally:

```bash
# After a DESTDIR-style / AUR-like install, or from source:
command -v winmiddle-ui
winmiddle-ui --help   # or just launch it
test -f /usr/share/applications/winmiddle.desktop \
  -o -f ~/.local/share/applications/winmiddle.desktop
```

### 1. Bump version in the repo

Pick the next semver (example: `0.2.0`). Update **both**:

- `pyproject.toml` → `version = "0.2.0"`
- `winmiddle/__init__.py` → `__version__ = "0.2.0"`
- `packaging/aur/winmiddle/PKGBUILD` → `pkgver=0.2.0` (and reset `pkgrel=1`)

Commit and push to `main` on GitHub (`eslachance/winscroll`).

### 2. Tag + GitHub Release

```bash
git tag -a v0.2.0 -m "winmiddle 0.2.0"
git push origin main --tags
gh release create v0.2.0 --title "winmiddle 0.2.0" --notes-file - <<'EOF'
- …
EOF
```

Confirm the source tarball exists:

`https://github.com/eslachance/winscroll/archive/refs/tags/v0.2.0.tar.gz`

(extracts as `winscroll-0.2.0/`).

### 3. Update AUR `winmiddle` (versioned)

```bash
# once per machine
# ~/.ssh/config → Host aur.archlinux.org / User aur / IdentityFile ~/.ssh/aur

git clone ssh://aur@aur.archlinux.org/winmiddle.git
cd winmiddle
# copy from this repo (or edit in place):
#   PKGBUILD, winmiddle.install, .SRCINFO

# set pkgver to the new version, then:
updpkgsums
makepkg --printsrcinfo > .SRCINFO

# optional local build smoke-test:
# makepkg -si

git checkout -B master
git add PKGBUILD winmiddle.install .SRCINFO
git commit -m "Update to 0.2.0"
git push origin master
```

Also copy the updated `PKGBUILD` / `.SRCINFO` / `winmiddle.install` back into `packaging/aur/winmiddle/` in this repo so they stay in sync.

### 4. Update AUR `winmiddle-git` (tracks main)

Usually only needed when packaging metadata changes (depends, install script, desktop files). The `pkgver()` function picks the version from git tags automatically.

```bash
git clone ssh://aur@aur.archlinux.org/winmiddle-git.git
cd winmiddle-git
# sync PKGBUILD / winmiddle.install from packaging/aur/winmiddle-git/
makepkg --printsrcinfo > .SRCINFO
git checkout -B master
git add PKGBUILD winmiddle.install .SRCINFO
git commit -m "Update packaging"
git push origin master
```

Testers on `-git` rebuild with `paru -S winmiddle-git` (or `--rebuild`).

### 5. Verify the install includes the GUI

```bash
paru -S winmiddle          # or winmiddle-git
pacman -Ql winmiddle | grep -E 'winmiddle-ui|applications/winmiddle.desktop|icons/.*/winmiddle'
winmiddle-ui
```

Expected: `/usr/bin/winmiddle-ui`, `/usr/share/applications/winmiddle.desktop`, icon under `/usr/share/icons/...`, and the app appears in the Plasma launcher.

### One-time AUR SSH setup

```bash
ssh-keygen -t ed25519 -f ~/.ssh/aur -C "aur"
# paste ~/.ssh/aur.pub into https://aur.archlinux.org → My Account → SSH Public Key

cat >> ~/.ssh/config <<'EOF'
Host aur.archlinux.org
  User aur
  IdentityFile ~/.ssh/aur
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
ssh -T aur@aur.archlinux.org   # expect: Welcome to AUR, <user>!
```

## License

MIT
