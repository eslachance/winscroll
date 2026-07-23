#!/usr/bin/env bash
# Install non-Python data files into a DESTDIR (used by PKGBUILD package()).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTDIR="${1:-${DESTDIR:-}}"
PREFIX="${PREFIX:-/usr}"

if [[ -z "$DESTDIR" ]]; then
  echo "usage: $0 DESTDIR" >&2
  exit 2
fi

install -Dm644 "$ROOT_DIR/systemd/winmiddle.service" \
  "$DESTDIR$PREFIX/lib/systemd/user/winmiddle.service"

install -Dm644 "$ROOT_DIR/packaging/udev/99-winmiddle.rules" \
  "$DESTDIR$PREFIX/lib/udev/rules.d/99-winmiddle.rules"

install -Dm644 "$ROOT_DIR/share/winmiddle-overlay.desktop" \
  "$DESTDIR$PREFIX/share/applications/winmiddle-overlay.desktop"

install -Dm644 "$ROOT_DIR/kwin-script/winmiddle-focus/metadata.json" \
  "$DESTDIR$PREFIX/share/kwin/scripts/winmiddle-focus/metadata.json"
install -Dm644 "$ROOT_DIR/kwin-script/winmiddle-focus/contents/code/main.js" \
  "$DESTDIR$PREFIX/share/kwin/scripts/winmiddle-focus/contents/code/main.js"

install -Dm644 "$ROOT_DIR/share/firefox-policies.json" \
  "$DESTDIR$PREFIX/share/winmiddle/firefox-policies.json"
install -Dm644 "$ROOT_DIR/share/udev-winmiddle.rules.example" \
  "$DESTDIR$PREFIX/share/winmiddle/udev-winmiddle.rules.example"
install -Dm644 "$ROOT_DIR/LICENSE" \
  "$DESTDIR$PREFIX/share/licenses/winmiddle/LICENSE"
