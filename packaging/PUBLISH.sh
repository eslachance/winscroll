#!/usr/bin/env bash
# Print the maintainer release checklist from README.md
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
awk '
  /^## Releasing a new version$/ { show=1 }
  show && /^## License$/ { exit }
  show { print }
' "$ROOT_DIR/README.md"
