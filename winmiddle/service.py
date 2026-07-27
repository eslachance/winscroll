"""systemd --user helpers for the winmiddle daemon."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


SERVICE_NAME = "winmiddle.service"


@dataclass
class ServiceStatus:
    active: bool
    enabled: bool
    activeState: str
    unitFileState: str
    detail: str


def _systemctl(*args: str, timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def serviceAvailable() -> bool:
    return shutil.which("systemctl") is not None


def queryServiceStatus() -> ServiceStatus:
    if not serviceAvailable():
        return ServiceStatus(
            active=False,
            enabled=False,
            activeState="unavailable",
            unitFileState="unavailable",
            detail="systemctl not found",
        )

    activeProc = _systemctl("is-active", SERVICE_NAME)
    enabledProc = _systemctl("is-enabled", SERVICE_NAME)
    showProc = _systemctl(
        "show",
        SERVICE_NAME,
        "--property=ActiveState,SubState,UnitFileState,Description",
        "--no-pager",
    )

    props: dict[str, str] = {}
    for line in (showProc.stdout or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            props[key] = value

    activeFromIs = (activeProc.stdout or "").strip()
    enabledFromIs = (enabledProc.stdout or "").strip()
    activeState = props.get("ActiveState") or activeFromIs or "unknown"
    unitFileState = props.get("UnitFileState") or enabledFromIs or "unknown"
    subState = props.get("SubState", "")
    detail = f"{activeState}/{subState}" if subState else activeState

    return ServiceStatus(
        active=activeState == "active" or activeFromIs == "active",
        enabled=unitFileState in {"enabled", "enabled-runtime", "static", "indirect"}
        or enabledFromIs in {"enabled", "enabled-runtime", "static", "indirect"},
        activeState=activeState,
        unitFileState=unitFileState,
        detail=detail,
    )


def startService() -> tuple[bool, str]:
    proc = _systemctl("start", SERVICE_NAME)
    ok = proc.returncode == 0
    return ok, _resultMessage(proc, okFallback="Daemon started", failFallback="Start failed")


def stopService() -> tuple[bool, str]:
    proc = _systemctl("stop", SERVICE_NAME)
    ok = proc.returncode == 0
    return ok, _resultMessage(proc, okFallback="Daemon stopped", failFallback="Stop failed")


def restartService() -> tuple[bool, str]:
    proc = _systemctl("restart", SERVICE_NAME)
    ok = proc.returncode == 0
    return ok, _resultMessage(proc, okFallback="Daemon restarted", failFallback="Restart failed")


def enableService(*, now: bool = True) -> tuple[bool, str]:
    args = ["enable", "--now", SERVICE_NAME] if now else ["enable", SERVICE_NAME]
    proc = _systemctl(*args)
    ok = proc.returncode == 0
    return ok, _resultMessage(proc, okFallback="Enabled at login", failFallback="Enable failed")


def disableService(*, now: bool = True) -> tuple[bool, str]:
    args = ["disable", "--now", SERVICE_NAME] if now else ["disable", SERVICE_NAME]
    proc = _systemctl(*args)
    ok = proc.returncode == 0
    return ok, _resultMessage(proc, okFallback="Disabled at login", failFallback="Disable failed")


def _resultMessage(
    proc: subprocess.CompletedProcess[str],
    *,
    okFallback: str,
    failFallback: str,
) -> str:
    raw = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode == 0:
        # systemctl often prints long "Created symlink …" noise on success.
        if not raw or "Created symlink" in raw or "Removed" in raw:
            return okFallback
        return raw.splitlines()[0]
    if raw:
        return raw.splitlines()[0]
    return failFallback
