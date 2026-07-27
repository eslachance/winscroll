"""First-time session setup: config, paste-kill, KWin script, udev, service."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from winmiddle.config import defaultConfigText
from winmiddle.paste import applyAllPasteAndBrowserFixes

log = logging.getLogger("winmiddle.setup")

MOUSE_UDEV_PATH = Path("/etc/udev/rules.d/99-winmiddle.rules")
LEGACY_MOUSE_UDEV_PATH = Path("/etc/udev/rules.d/99-winmiddle-mouse.rules")


def ensureConfig(configPath: Path | None = None) -> Path:
    target = configPath or (Path.home() / ".config" / "winmiddle" / "config.toml")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        log.info("Config already exists: %s", target)
        return target
    target.write_text(defaultConfigText(), encoding="utf-8")
    log.info("Wrote config %s", target)
    return target


def kwinScriptMainJs() -> Path | None:
    """Prefer the packaged system script; fall back to a user-local copy.

    System first matters for AUR/distro installs: a stale ~/.local copy without
    KPackageStructure can shadow the fixed package and prevent Plasma 6 load.
    """
    candidates = [
        Path("/usr/share/kwin/scripts/winmiddle-focus/contents/code/main.js"),
        Path.home() / ".local/share/kwin/scripts/winmiddle-focus/contents/code/main.js",
    ]
    for mainJs in candidates:
        if mainJs.is_file():
            return mainJs
    return None


def _qdbusBin() -> str | None:
    return shutil.which("qdbus6") or shutil.which("qdbus")


def isKwinScriptLoaded() -> bool | None:
    """True/False if KWin answers; None if qdbus/KWin unavailable."""
    qdbus = _qdbusBin()
    if not qdbus:
        return None
    result = subprocess.run(
        [
            qdbus,
            "org.kde.KWin",
            "/Scripting",
            "org.kde.kwin.Scripting.isScriptLoaded",
            "winmiddle-focus",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip().lower() in {"true", "1"}


def enableKwinScript() -> bool:
    """Persist-enable + load winmiddle-focus so cursor/focus reach the daemon.

    Safe to call on every daemon start: AUR install only ships files; without
    Plugins/winmiddle-focusEnabled=true KWin never loads the script after reboot.
    """
    kwrite = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
    if not kwrite:
        log.warning("kwriteconfig6 missing — enable KWin script winmiddle-focus manually")
        return False

    if kwinScriptMainJs() is None:
        log.warning("winmiddle-focus KWin script not installed under /usr/share or ~/.local")
        return False

    subprocess.run(
        [kwrite, "--file", "kwinrc", "--group", "Plugins", "--key", "winmiddle-focusEnabled", "true"],
        check=False,
    )

    qdbus = _qdbusBin()
    if not qdbus:
        log.warning("qdbus6 missing — winmiddle-focusEnabled written; restart Plasma to load it")
        return False

    # Plugins=*Enabled + reconfigure is enough when metadata has KPackageStructure.
    subprocess.run([qdbus, "org.kde.KWin", "/KWin", "reconfigure"], check=False)

    loaded = isKwinScriptLoaded()
    if loaded:
        log.info("KWin script winmiddle-focus already loaded")
        return True

    # Explicit load helps when reconfigure races session startup.
    mainJs = kwinScriptMainJs()
    assert mainJs is not None
    subprocess.run(
        [qdbus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", "winmiddle-focus"],
        check=False,
        capture_output=True,
    )
    load = subprocess.run(
        [
            qdbus,
            "org.kde.KWin",
            "/Scripting",
            "org.kde.kwin.Scripting.loadScript",
            str(mainJs),
            "winmiddle-focus",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [qdbus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.start"],
        check=False,
        capture_output=True,
    )

    loaded = isKwinScriptLoaded()
    if loaded:
        log.info("KWin script winmiddle-focus loaded from %s", mainJs)
        return True

    log.warning(
        "KWin script winmiddle-focus not loaded (load=%s out=%s). "
        "Check metadata KPackageStructure and System Settings → KWin Scripts.",
        load.returncode,
        (load.stdout or load.stderr or "").strip() or "(empty)",
    )
    return False


def mouseUdevRuleText() -> str:
    """udev rules that work for any mouse (not a single VID/PID).

    Stock 70-uaccess.rules does not tag mice. A late TAG+=uaccess alone is also
    not enough: 71-seat.rules has already run, so we must TAG+=seat ourselves.
    Never RUN setfacl with /dev/%k — that expands to /dev/eventN (wrong path).
    """
    return (
        "# winmiddle — virtual pointer + any USB/Bluetooth mouse for the seated user\n"
        'KERNEL=="uinput", MODE="0660", TAG+="uaccess", OPTIONS+="static_node=uinput"\n'
        'SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_INPUT_MOUSE}=="1", '
        'MODE="0660", GROUP="input", TAG+="uaccess", TAG+="seat"\n'
    )


def installMouseUdevRule(*, vendor: int | None = None, product: int | None = None) -> bool:
    """Install a generic mouse+uinput uaccess rule (vendor/product kept for API compat)."""
    del vendor, product  # VID/PID pinning breaks when users swap mice
    body = mouseUdevRuleText()

    if os.geteuid() == 0:
        MOUSE_UDEV_PATH.write_text(body, encoding="utf-8")
        MOUSE_UDEV_PATH.chmod(0o644)
        LEGACY_MOUSE_UDEV_PATH.unlink(missing_ok=True)
    else:
        if not shutil.which("sudo"):
            log.warning("sudo missing; could not install %s", MOUSE_UDEV_PATH)
            return False
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
            handle.write(body)
            tmpPath = handle.name
        try:
            result = subprocess.run(["sudo", "cp", tmpPath, str(MOUSE_UDEV_PATH)], check=False)
            if result.returncode != 0:
                log.warning("Could not install mouse udev rule at %s", MOUSE_UDEV_PATH)
                return False
            subprocess.run(["sudo", "chmod", "644", str(MOUSE_UDEV_PATH)], check=False)
            subprocess.run(["sudo", "rm", "-f", str(LEGACY_MOUSE_UDEV_PATH)], check=False)
        finally:
            Path(tmpPath).unlink(missing_ok=True)

    subprocess.run(["sudo", "udevadm", "control", "--reload-rules"], check=False)
    subprocess.run(["sudo", "udevadm", "trigger"], check=False)
    log.info("Mouse udev rule → %s", MOUSE_UDEV_PATH)
    return True


def enableUserService() -> bool:
    result = subprocess.run(
        ["systemctl", "--user", "enable", "--now", "winmiddle.service"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.warning(
            "Could not enable winmiddle.service: %s",
            (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}",
        )
        return False
    log.info("systemd --user winmiddle.service enabled and started")
    return True


def runSetup(*, skipUdev: bool = False, skipService: bool = False) -> int:
    """Apply session-level setup after a package or from-source install."""
    ensureConfig()
    applyAllPasteAndBrowserFixes()
    enableKwinScript()
    if not skipUdev:
        installMouseUdevRule()
    if not skipService:
        enableUserService()

    print(
        "\n".join(
            [
                "",
                "winmiddle setup complete.",
                "  • Log out and back in once so KWin drops primary selection.",
                "  • Settings: winmiddle-ui  (or: winmiddle --ui)",
                "  • Status:   systemctl --user status winmiddle",
                "  • Logs:     journalctl --user -u winmiddle -f",
                "  • Devices:  winmiddle --list-devices",
                "  • Config:   ~/.config/winmiddle/config.toml",
                "",
            ]
        )
    )
    return 0
