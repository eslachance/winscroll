"""Apply paste-kill + browser native Windows middle-click prefs."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("winmiddle.paste")

FIREFOX_POLICY = {
    "policies": {
        "Preferences": {
            "middlemouse.paste": {"Value": False, "Status": "user"},
            "general.autoScroll": {"Value": True, "Status": "user"},
            "clipboard.autocopy": {"Value": False, "Status": "user"},
        }
    }
}


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=False)


def ensureIniKey(path: Path, section: str, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f"[{section}]\n{key}={value}\n", encoding="utf-8")
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    inSection = False
    sectionFound = False
    keyWritten = False
    header = f"[{section}]"
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if inSection and not keyWritten:
                out.append(f"{key}={value}")
                keyWritten = True
            inSection = stripped == header
            if inSection:
                sectionFound = True
            out.append(line)
            continue
        if inSection and (stripped.startswith(f"{key}=") or stripped.startswith(f"{key} =")):
            out.append(f"{key}={value}")
            keyWritten = True
            continue
        out.append(line)
    if inSection and not keyWritten:
        out.append(f"{key}={value}")
        keyWritten = True
    if not sectionFound:
        if out and out[-1] != "":
            out.append("")
        out.append(header)
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def applyKdePasteKill() -> None:
    kwrite = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
    kwinrc = Path.home() / ".config" / "kwinrc"
    if kwrite:
        _run([kwrite, "--file", "kwinrc", "--group", "Wayland", "--key", "EnablePrimarySelection", "--type", "bool", "false"])
    else:
        ensureIniKey(kwinrc, "Wayland", "EnablePrimarySelection", "false")
    ensureIniKey(Path.home() / ".config" / "klipperrc", "General", "NoEmptyClipboard", "false")
    log.info("KDE primary selection disabled")


def applyGtkPasteKill() -> None:
    ensureIniKey(Path.home() / ".config" / "gtk-3.0" / "settings.ini", "Settings", "gtk-enable-primary-paste", "false")
    ensureIniKey(Path.home() / ".config" / "gtk-4.0" / "settings.ini", "Settings", "gtk-enable-primary-paste", "false")
    if shutil.which("gsettings"):
        _run(["gsettings", "set", "org.gnome.desktop.interface", "gtk-enable-primary-paste", "false"])
    log.info("GTK primary paste disabled")


def applyFirefoxWindowsMiddle() -> None:
    staged = Path.home() / ".config" / "winmiddle" / "firefox-policies.json"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(json.dumps(FIREFOX_POLICY, indent=2) + "\n", encoding="utf-8")

    profilesIni = Path.home() / ".mozilla" / "firefox" / "profiles.ini"
    if profilesIni.exists():
        import configparser

        parser = configparser.ConfigParser()
        parser.read(profilesIni)
        for section in parser.sections():
            if not parser.has_option(section, "Path"):
                continue
            profile = profilesIni.parent / parser.get(section, "Path")
            if not profile.is_dir():
                continue
            userJs = profile / "user.js"
            userJs.write_text(
                "\n".join(
                    [
                        "// Managed by winmiddle",
                        'user_pref("middlemouse.paste", false);',
                        'user_pref("general.autoScroll", true);',
                        'user_pref("clipboard.autocopy", false);',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            log.info("Firefox user.js → %s", profile)

    # System policies if we can
    if shutil.which("sudo"):
        policyDir = Path("/etc/firefox/policies")
        try:
            _run(["sudo", "mkdir", "-p", str(policyDir)])
            _run(["sudo", "cp", str(staged), str(policyDir / "policies.json")])
            log.info("Firefox system policies installed")
        except Exception as error:
            log.warning("Could not install system Firefox policies: %s", error)


def applyChromeAutoscroll() -> None:
    homes = [
        Path.home() / ".config" / "google-chrome",
        Path.home() / ".config" / "chromium",
        Path.home() / ".config" / "BraveSoftware" / "Brave-Browser",
        Path.home() / ".config" / "vivaldi",
    ]
    for home in homes:
        statePath = home / "Local State"
        if not statePath.exists():
            continue
        try:
            data = json.loads(statePath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        browser = data.setdefault("browser", {})
        flags = [f for f in (browser.get("enabled_labs_experiments") or []) if not str(f).startswith("enable-middle-click-autoscroll")]
        flags.append("enable-middle-click-autoscroll@1")
        browser["enabled_labs_experiments"] = flags
        statePath.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        log.info("Chrome middle-click autoscroll flag → %s", home)


def applyAllPasteAndBrowserFixes() -> None:
    applyKdePasteKill()
    applyGtkPasteKill()
    applyFirefoxWindowsMiddle()
    applyChromeAutoscroll()
