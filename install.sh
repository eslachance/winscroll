#!/usr/bin/env bash
# From-source install for winmiddle (user-local). Prefer AUR packages when available.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/winmiddle"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/winmiddle"
KWIN_SCRIPT_DST="${XDG_DATA_HOME:-$HOME/.local/share}/kwin/scripts/winmiddle-focus"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

log() { printf '==> %s\n' "$*"; }
ok()  { printf 'OK  %s\n' "$*"; }
warn(){ printf '!!  %s\n' "$*" >&2; }

mkdir -p "$SITE_DIR" "$BIN_DIR" "$CONFIG_DIR" "$UNIT_DIR" "$APP_DIR"

log "Installing winmiddle package → $SITE_DIR"
rm -rf "$SITE_DIR/winmiddle"
cp -a "$ROOT_DIR/winmiddle" "$SITE_DIR/winmiddle"
# Drop bytecode / tests from the local install tree
rm -rf "$SITE_DIR/winmiddle/__pycache__"
rm -f "$SITE_DIR/winmiddle"/test_*.py
printf '%s\n' "$SITE_DIR" >"$SITE_DIR/ROOT"

cat >"$BIN_DIR/winmiddle" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="${SITE_DIR}\${PYTHONPATH:+:\$PYTHONPATH}"
exec /usr/bin/python3 -m winmiddle "\$@"
EOF
chmod +x "$BIN_DIR/winmiddle"
ok "Launcher $BIN_DIR/winmiddle"

if ! command -v winmiddle >/dev/null 2>&1; then
  warn "Add \$HOME/.local/bin to your PATH if winmiddle is not found"
fi

log "Installing KWin focus helper script"
mkdir -p "$KWIN_SCRIPT_DST/contents/code"
cp -a "$ROOT_DIR/kwin-script/winmiddle-focus/metadata.json" "$KWIN_SCRIPT_DST/"
cp -a "$ROOT_DIR/kwin-script/winmiddle-focus/contents/code/main.js" "$KWIN_SCRIPT_DST/contents/code/"
ok "KWin script → $KWIN_SCRIPT_DST"

log "Installing systemd --user unit + desktop entry"
install -Dm644 "$ROOT_DIR/systemd/winmiddle.service" "$UNIT_DIR/winmiddle.service"
sed -i "s|^ExecStart=.*|ExecStart=$BIN_DIR/winmiddle -v|" "$UNIT_DIR/winmiddle.service"
install -Dm644 "$ROOT_DIR/share/winmiddle-overlay.desktop" "$APP_DIR/winmiddle-overlay.desktop"
sed -i "s|^Exec=.*|Exec=$BIN_DIR/winmiddle|" "$APP_DIR/winmiddle-overlay.desktop"
systemctl --user daemon-reload
ok "User unit $UNIT_DIR/winmiddle.service"

log "Running winmiddle --setup (config, paste-kill, KWin, udev, enable service)"
if ! "$BIN_DIR/winmiddle" --setup; then
  warn "Setup reported errors; check output above"
fi

cat <<EOF

────────────────────────────────────────────────────────────
winmiddle is installed from source.

  Status:   systemctl --user status winmiddle
  Logs:     journalctl --user -u winmiddle -f
  Devices:  winmiddle --list-devices
  Config:   ~/.config/winmiddle/config.toml

Log out and back in once so KWin drops primary selection.
AUR users: prefer \`paru -S winmiddle\` / \`winmiddle-git\` instead.
────────────────────────────────────────────────────────────
EOF
