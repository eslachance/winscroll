#!/usr/bin/env bash
# Install winmiddle: Windows middle-click autoscroll + paste kill on Plasma/Linux.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/winmiddle"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/winmiddle"
KWIN_SCRIPT_DST="${XDG_DATA_HOME:-$HOME/.local/share}/kwin/scripts/winmiddle-focus"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

log() { printf '==> %s\n' "$*"; }
ok()  { printf 'OK  %s\n' "$*"; }
warn(){ printf '!!  %s\n' "$*" >&2; }

mkdir -p "$SITE_DIR" "$BIN_DIR" "$CONFIG_DIR" "$UNIT_DIR"

log "Installing winmiddle package → $SITE_DIR"
rm -rf "$SITE_DIR/winmiddle"
cp -a "$ROOT_DIR/winmiddle" "$SITE_DIR/winmiddle"
printf '%s\n' "$SITE_DIR" >"$SITE_DIR/ROOT"

# Launcher puts site dir on PYTHONPATH
cat >"$BIN_DIR/winmiddle" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="${SITE_DIR}\${PYTHONPATH:+:\$PYTHONPATH}"
exec /usr/bin/python3 -m winmiddle "\$@"
EOF
chmod +x "$BIN_DIR/winmiddle"
ok "Launcher $BIN_DIR/winmiddle"

# Ensure ~/.local/bin is on PATH for this shell check
if ! command -v winmiddle >/dev/null 2>&1; then
  warn "Add \$HOME/.local/bin to your PATH if winmiddle is not found"
fi

if [[ ! -f "$CONFIG_DIR/config.toml" ]]; then
  "$BIN_DIR/winmiddle" --write-config || python3 - <<PY
from pathlib import Path
import sys
sys.path.insert(0, "$SITE_DIR")
from winmiddle.config import defaultConfigText
p = Path("$CONFIG_DIR/config.toml")
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(defaultConfigText(), encoding="utf-8")
print(p)
PY
  ok "Config $CONFIG_DIR/config.toml"
fi

log "Installing KWin focus helper script"
mkdir -p "$KWIN_SCRIPT_DST/contents/code"
cp -a "$ROOT_DIR/kwin-script/winmiddle-focus/metadata.json" "$KWIN_SCRIPT_DST/"
cp -a "$ROOT_DIR/kwin-script/winmiddle-focus/contents/code/main.js" "$KWIN_SCRIPT_DST/contents/code/"
if command -v kwriteconfig6 >/dev/null; then
  kwriteconfig6 --file kwinrc --group Plugins --key winmiddle-focusEnabled true
  qdbus6 org.kde.KWin /KWin reconfigure 2>/dev/null || true
  # Also try loading via Scripting API
  qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript winmiddle-focus 2>/dev/null || true
  qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript "$KWIN_SCRIPT_DST/contents/code/main.js" winmiddle-focus 2>/dev/null || true
  qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.start 2>/dev/null || true
  ok "KWin script enabled (winmiddle-focus)"
else
  warn "kwriteconfig6 missing — enable KWin script manually later"
fi

log "Applying paste-kill + browser Windows middle-click prefs"
PYTHONPATH="$SITE_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
from winmiddle.paste import applyAllPasteAndBrowserFixes
applyAllPasteAndBrowserFixes()
PY

log "Writing udev rules for mouse + uinput (needs sudo once)"
DEVICE_LINE="$(PYTHONPATH="$SITE_DIR" python3 -m winmiddle --list-devices 2>/dev/null | head -1 || true)"
VENDOR=""; PRODUCT=""
if [[ -n "$DEVICE_LINE" ]]; then
  # path vid=XXXX pid=YYYY name
  VENDOR="$(awk '{for(i=1;i<=NF;i++) if($i ~ /^vid=/) {split($i,a,"="); print a[2]}}' <<<"$DEVICE_LINE")"
  PRODUCT="$(awk '{for(i=1;i<=NF;i++) if($i ~ /^pid=/) {split($i,a,"="); print a[2]}}' <<<"$DEVICE_LINE")"
  ok "Detected mouse vid=$VENDOR pid=$PRODUCT"
fi

UDEV_FILE="/etc/udev/rules.d/99-winmiddle.rules"
if [[ -n "$VENDOR" && -n "$PRODUCT" ]]; then
  TMP="$(mktemp)"
  cat >"$TMP" <<EOF
# winmiddle — allow seated user to grab mouse + create virtual pointer
KERNEL=="uinput", MODE="0660", TAG+="uaccess", OPTIONS+="static_node=uinput"
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{idVendor}=="$VENDOR", ATTRS{idProduct}=="$PRODUCT", MODE="0660", TAG+="uaccess"
EOF
  if sudo cp "$TMP" "$UDEV_FILE"; then
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    ok "udev rules → $UDEV_FILE"
  else
    warn "Could not install udev rules; if grab fails, add yourself to the input group"
  fi
  rm -f "$TMP"
else
  warn "No mouse detected for udev rule; skipping"
fi

log "Installing systemd --user service"
cp "$ROOT_DIR/systemd/winmiddle.service" "$UNIT_DIR/winmiddle.service"
# Point ExecStart at the launcher
sed -i "s|^ExecStart=.*|ExecStart=$BIN_DIR/winmiddle -v|" "$UNIT_DIR/winmiddle.service"
systemctl --user daemon-reload
systemctl --user enable --now winmiddle.service
ok "systemd --user winmiddle.service enabled and started"

cat <<EOF

────────────────────────────────────────────────────────────
winmiddle is installed.

What you get (Windows model):
  • Middle-CLICK (not hold) → autoscroll mode + origin glyph
  • Move away from origin → scroll speed scales with distance
  • Click any button → exit autoscroll
  • Middle-DRAG → passed through (Blender/CAD orbit)
  • Browsers → native Windows middle-click (links/tabs/autoscroll)
  • Highlight-to-middle-paste → killed (KDE/GTK/Firefox)

IMPORTANT:
  1. Log out and back in once so KWin drops primary selection.
  2. Check status:   systemctl --user status winmiddle
  3. Logs:           journalctl --user -u winmiddle -f
  4. List devices:   winmiddle --list-devices
  5. Config:         ~/.config/winmiddle/config.toml

Test in Kate/Dolphin/Okular:
  middle-click once, move mouse — should autoscroll like Windows.
Test in Firefox/Chrome:
  middle-click empty page — native autoscroll; links still open in new tabs.
────────────────────────────────────────────────────────────
EOF
