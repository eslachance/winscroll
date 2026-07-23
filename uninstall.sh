#!/usr/bin/env bash
# Remove a from-source (user-local) install. Packaged installs: pacman -R winmiddle
set -euo pipefail

SITE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/winmiddle"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
KWIN_SCRIPT_DST="${XDG_DATA_HOME:-$HOME/.local/share}/kwin/scripts/winmiddle-focus"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

log() { printf '==> %s\n' "$*"; }

log "Stopping winmiddle"
systemctl --user disable --now winmiddle.service 2>/dev/null || true
rm -f "$UNIT_DIR/winmiddle.service"
systemctl --user daemon-reload 2>/dev/null || true

log "Removing KWin script"
if command -v kwriteconfig6 >/dev/null; then
  kwriteconfig6 --file kwinrc --group Plugins --key winmiddle-focusEnabled false
  qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript winmiddle-focus 2>/dev/null || true
  qdbus6 org.kde.KWin /KWin reconfigure 2>/dev/null || true
fi
rm -rf "$KWIN_SCRIPT_DST"

log "Removing launcher + package + desktop entry"
rm -f "$BIN_DIR/winmiddle"
rm -f "$APP_DIR/winmiddle-overlay.desktop"
rm -rf "$SITE_DIR"

log "Re-enabling KDE primary selection (middle-click paste)"
if command -v kwriteconfig6 >/dev/null; then
  kwriteconfig6 --file kwinrc --group Wayland --key EnablePrimarySelection --type bool true
fi

cat <<EOF
Uninstalled from-source winmiddle.
Config kept at ~/.config/winmiddle/ (remove manually if desired).
Optional mouse udev rule:
  sudo rm -f /etc/udev/rules.d/99-winmiddle-mouse.rules
  sudo udevadm control --reload-rules
Log out/in for KWin primary-selection change.
EOF
