#!/usr/bin/env bash
set -euo pipefail
echo "=== winmiddle status ==="
systemctl --user is-active winmiddle.service 2>/dev/null || echo "service: inactive"
systemctl --user is-enabled winmiddle.service 2>/dev/null || true
echo
if command -v winmiddle >/dev/null; then
  winmiddle --list-devices || true
else
  echo "winmiddle launcher not on PATH"
fi
echo
echo "KDE EnablePrimarySelection=$(kreadconfig6 --file kwinrc --group Wayland --key EnablePrimarySelection 2>/dev/null || echo '?')"
echo "KWin script enabled=$(kreadconfig6 --file kwinrc --group Plugins --key winmiddle-focusEnabled 2>/dev/null || echo '?')"
echo
journalctl --user -u winmiddle -n 15 --no-pager 2>/dev/null || true
