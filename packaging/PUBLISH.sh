#!/usr/bin/env bash
# Helper notes for publishing (run locally; not used by PKGBUILD).
set -euo pipefail

cat <<'EOF'
Publish checklist
=================

1. Commit packaging changes on main and push to GitHub.
2. Tag and release:
     git tag -a v0.1.0 -m "winmiddle 0.1.0"
     git push origin main --tags
     gh release create v0.1.0 --title "winmiddle 0.1.0" --notes "First public alpha for Plasma/Wayland on Arch-based distros."

3. AUR SSH (once):
     # ~/.ssh/config
     Host aur.archlinux.org
       User aur
       IdentityFile ~/.ssh/aur
       IdentitiesOnly yes

4. Publish winmiddle (versioned):
     git clone ssh://aur@aur.archlinux.org/winmiddle.git
     cp packaging/aur/winmiddle/{PKGBUILD,winmiddle.install,.SRCINFO} winmiddle/
     cd winmiddle
     # after tag exists:
     updpkgsums
     makepkg --printsrcinfo > .SRCINFO
     git add PKGBUILD winmiddle.install .SRCINFO
     git commit -m "Initial winmiddle 0.1.0"
     git push

5. Publish winmiddle-git:
     git clone ssh://aur@aur.archlinux.org/winmiddle-git.git
     cp packaging/aur/winmiddle-git/{PKGBUILD,winmiddle.install,.SRCINFO} winmiddle-git/
     cd winmiddle-git
     makepkg --printsrcinfo > .SRCINFO
     git add PKGBUILD winmiddle.install .SRCINFO
     git commit -m "Initial winmiddle-git"
     git push

6. Testers:
     paru -S winmiddle
     winmiddle --setup
EOF
