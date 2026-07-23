"""Receive active window + cursor position from the KWin helper script."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSlot
from PyQt6.QtDBus import QDBusConnection

log = logging.getLogger("winmiddle.focus")

SERVICE = "local.winmiddle.Focus1"
PATH = "/Focus"
INTERFACE = "local.winmiddle.Focus"


@dataclass
class FocusState:
    resourceClass: str = ""
    resourceName: str = ""
    cursorX: int = 0
    cursorY: int = 0
    # Screen availableGeometry (excludes strut panels): x, y, w, h — or None.
    workArea: tuple[int, int, int, int] | None = None
    # True when the topmost window under the cursor is a dock/panel.
    underPanel: bool = False


def _workAreaAt(cursorX: int, cursorY: int) -> tuple[int, int, int, int] | None:
    """Qt main-thread helper: usable desktop rect under the pointer."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QGuiApplication

    screen = QGuiApplication.screenAt(QPoint(cursorX, cursorY)) or QGuiApplication.primaryScreen()
    if screen is None:
        return None
    geo = screen.availableGeometry()
    return (geo.x(), geo.y(), geo.width(), geo.height())


class FocusHub(QObject):
    """DBus peer updated by the KWin script every ~50ms."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._state = FocusState()

    def snapshot(self) -> FocusState:
        with self._lock:
            return FocusState(
                resourceClass=self._state.resourceClass,
                resourceName=self._state.resourceName,
                cursorX=self._state.cursorX,
                cursorY=self._state.cursorY,
                workArea=self._state.workArea,
                underPanel=self._state.underPanel,
            )

    def refreshWorkArea(self) -> None:
        """Periodic Qt-thread refresh so panel detection works if the script lags."""
        with self._lock:
            cx, cy = self._state.cursorX, self._state.cursorY
        wa = _workAreaAt(cx, cy)
        if wa is None:
            return
        with self._lock:
            self._state.workArea = wa

    @pyqtSlot(str, str, int, int, bool)
    def Update(
        self,
        resourceClass: str,
        resourceName: str,
        cursorX: int,
        cursorY: int,
        underPanel: bool = False,
    ) -> None:
        wa = _workAreaAt(int(cursorX), int(cursorY))
        with self._lock:
            self._state = FocusState(
                resourceClass=(resourceClass or "").lower(),
                resourceName=(resourceName or "").lower(),
                cursorX=int(cursorX),
                cursorY=int(cursorY),
                workArea=wa,
                underPanel=bool(underPanel),
            )


def registerFocusHub(hub: FocusHub) -> bool:
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        log.warning("No session D-Bus; app-aware passthrough disabled")
        return False

    if not bus.registerService(SERVICE):
        log.warning("Could not claim %s (already running?)", SERVICE)
        return False

    opts = (
        QDBusConnection.RegisterOption.ExportScriptableSlots
        | QDBusConnection.RegisterOption.ExportNonScriptableSlots
        | QDBusConnection.RegisterOption.ExportScriptableInvokables
        | QDBusConnection.RegisterOption.ExportNonScriptableInvokables
    )
    if not bus.registerObject(PATH, hub, opts):
        log.warning("Could not export %s on D-Bus", PATH)
        return False

    log.info("Focus hub listening on %s", SERVICE)
    return True


def matchesAny(focus: FocusState, patterns: list[str]) -> bool:
    if not patterns:
        return False
    haystacks = (focus.resourceClass, focus.resourceName)
    for pattern in patterns:
        needle = pattern.lower().strip()
        if not needle:
            continue
        for hay in haystacks:
            if needle in hay:
                return True
    return False
