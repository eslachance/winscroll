"""Windows-style autoscroll origin marker (small LayerShell surface).

LOCKED DESIGN — see `.cursor/rules/indicator-locked.mdc`.
Do not replace this with fullscreen overlays or setOverrideCursor; those
steal wheel events or fight the compositor on Wayland.

Design notes (Wayland):
- A fullscreen overlay under the pointer steals wheel events → no scroll.
- setOverrideCursor needs pointer focus → same problem.
- Windows keeps a *small* origin glyph at the click point; the pointer leaves it
  when scrolling, so apps under the cursor still receive wheel events.
- Direction is shown by emphasizing arms on that glyph (no floating arrow, no drift).
"""

from __future__ import annotations

import ctypes
import logging
import math
from ctypes import CDLL, POINTER, Structure, c_int, c_void_p

from PyQt6 import sip
from PyQt6.QtCore import QObject, QPoint, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen, QRegion
from PyQt6.QtWidgets import QWidget

log = logging.getLogger("winmiddle.cursor")

GLYPH_SIZE = 48

_ANCHOR_TOP = 1
_ANCHOR_LEFT = 4
_LAYER_OVERLAY = 3
_KBD_NONE = 0


class _QMarginsC(Structure):
    _fields_ = [("left", c_int), ("top", c_int), ("right", c_int), ("bottom", c_int)]


class _QSizeC(Structure):
    _fields_ = [("wd", c_int), ("ht", c_int)]


def _layerShellLib() -> CDLL | None:
    try:
        return CDLL("libLayerShellQtInterface.so.6")
    except OSError:
        try:
            return CDLL("libLayerShellQtInterface.so")
        except OSError:
            return None


class _LayerShell:
    def __init__(self, windowHandle) -> None:
        self.lib = _layerShellLib()
        self.ptr: int | None = None
        self.obj: QObject | None = None
        if self.lib is None or windowHandle is None:
            return
        getter = self.lib._ZN12LayerShellQt6Window3getEP7QWindow
        getter.restype = c_void_p
        getter.argtypes = [c_void_p]
        self.ptr = getter(sip.unwrapinstance(windowHandle))
        if not self.ptr:
            return
        self.obj = sip.wrapinstance(self.ptr, QObject)

        setAnchors = self.lib._ZN12LayerShellQt6Window10setAnchorsE6QFlagsINS0_6AnchorEE
        setAnchors.argtypes = [c_void_p, c_int]
        setAnchors(self.ptr, _ANCHOR_TOP | _ANCHOR_LEFT)

        setLayer = self.lib._ZN12LayerShellQt6Window8setLayerENS0_5LayerE
        setLayer.argtypes = [c_void_p, c_int]
        setLayer(self.ptr, _LAYER_OVERLAY)

        setKbd = self.lib._ZN12LayerShellQt6Window24setKeyboardInteractivityENS0_21KeyboardInteractivityE
        setKbd.argtypes = [c_void_p, c_int]
        setKbd(self.ptr, _KBD_NONE)

        setZone = self.lib._ZN12LayerShellQt6Window16setExclusiveZoneEi
        setZone.argtypes = [c_void_p, c_int]
        setZone(self.ptr, -1)

        setDesired = self.lib._ZN12LayerShellQt6Window14setDesiredSizeERK5QSize
        setDesired.argtypes = [c_void_p, POINTER(_QSizeC)]
        setDesired(self.ptr, ctypes.byref(_QSizeC(GLYPH_SIZE, GLYPH_SIZE)))

        self.obj.setProperty("scope", "winmiddle")
        self.obj.setProperty("activateOnShow", False)

    @property
    def ok(self) -> bool:
        return self.ptr is not None

    def setMargins(self, left: int, top: int) -> None:
        if not self.ptr or self.lib is None:
            return
        setMargins = self.lib._ZN12LayerShellQt6Window10setMarginsERK8QMargins
        setMargins.argtypes = [c_void_p, POINTER(_QMarginsC)]
        setMargins(self.ptr, ctypes.byref(_QMarginsC(left, top, 0, 0)))


def _activeSector(dx: float, dy: float, deadzone: float) -> int | None:
    """Return 0..7 clock sector, or None inside deadzone. 0=E, 2=S, 4=W, 6=N."""
    if math.hypot(dx, dy) < max(1.0, deadzone):
        return None
    angle = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
    return int((angle + 22.5) // 45) % 8


def _drawOriginGlyph(painter: QPainter, cx: int, cy: int, sector: int | None) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor(40, 40, 40, 230), 2))
    painter.setBrush(QColor(250, 250, 250, 230))
    painter.drawEllipse(QPoint(cx, cy), 14, 14)

    # Arms: E, SE, S, SW, W, NW, N, NE — highlight active sector.
    arms = [
        (1, 0),
        (1, 1),
        (0, 1),
        (-1, 1),
        (-1, 0),
        (-1, -1),
        (0, -1),
        (1, -1),
    ]
    for idx, (ax, ay) in enumerate(arms):
        active = sector == idx
        painter.setPen(QPen(QColor(20, 20, 20, 250) if active else QColor(30, 30, 30, 160), 3 if active else 2))
        length = 10 if active else 8
        # Normalize diagonal length a bit
        scale = length / math.hypot(ax, ay)
        ex = cx + int(ax * scale)
        ey = cy + int(ay * scale)
        sx = cx + int(ax * 3)
        sy = cy + int(ay * 3)
        painter.drawLine(sx, sy, ex, ey)
        # arrow head
        if ax == 0:
            painter.drawLine(ex, ey, ex - 3, ey - (2 if ay > 0 else -2))
            painter.drawLine(ex, ey, ex + 3, ey - (2 if ay > 0 else -2))
        elif ay == 0:
            painter.drawLine(ex, ey, ex - (2 if ax > 0 else -2), ey - 3)
            painter.drawLine(ex, ey, ex - (2 if ax > 0 else -2), ey + 3)
        else:
            # diagonal: small V
            painter.drawLine(ex, ey, ex - ax * 3, ey)
            painter.drawLine(ex, ey, ex, ey - ay * 3)

    painter.setBrush(QColor(30, 30, 30, 240))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPoint(cx, cy), 2, 2)


class _OriginMarker(QWidget):
    """48×48 origin glyph parked at the middle-click point."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(GLYPH_SIZE, GLYPH_SIZE)
        self.setWindowTitle("")
        self._active = False
        self._paintArmed = False
        self._dx = 0.0
        self._dy = 0.0
        self._deadzone = 12.0
        self._layer: _LayerShell | None = None

    def _ensureLayer(self) -> None:
        if self._layer is not None:
            return
        if self.windowHandle() is None:
            self.winId()
        self._layer = _LayerShell(self.windowHandle())
        if self._layer.ok:
            log.info("LayerShell origin marker ready")
        else:
            log.warning("LayerShell unavailable; marker may mis-position on Wayland")

    def _place(self, globalX: int, globalY: int) -> None:
        half = GLYPH_SIZE // 2
        origin = QPoint(globalX, globalY)
        screen = QGuiApplication.screenAt(origin) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        localX = globalX - geo.x()
        localY = globalY - geo.y()
        left = max(0, min(localX - half, max(0, geo.width() - GLYPH_SIZE)))
        top = max(0, min(localY - half, max(0, geo.height() - GLYPH_SIZE)))

        handle = self.windowHandle()
        if handle is not None:
            handle.setScreen(screen)
            handle.setMask(QRegion())  # empty input region

        if self._layer and self._layer.ok:
            self._layer.setMargins(left, top)
        else:
            # X11 / fallback — Wayland ignores QWidget.move for normal surfaces.
            self.move(geo.x() + left, geo.y() + top)

        log.debug("marker place global=(%s,%s) margins=(%s,%s) screen=%s", globalX, globalY, left, top, geo)

    def showAt(self, globalX: int, globalY: int) -> None:
        # Focus-hub coords can be 0,0 if the KWin script hasn't reported yet.
        if globalX == 0 and globalY == 0:
            cursor = QCursor.pos()
            globalX, globalY = cursor.x(), cursor.y()

        self._dx = 0.0
        self._dy = 0.0
        self._active = True
        self._paintArmed = False
        self._ensureLayer()

        # Position while hidden so the first mapped frame is already correct
        # (avoids Plasma's center→target open animation on a wrong first rect).
        if self.isVisible():
            self.hide()
        self._place(globalX, globalY)
        self.show()
        self.raise_()
        self._place(globalX, globalY)
        self._paintArmed = True
        self.update()
        log.info("origin marker ON at (%s,%s)", globalX, globalY)

    def hideMarker(self) -> None:
        self._active = False
        self._paintArmed = False
        self.hide()
        log.info("origin marker OFF")

    def setDirection(self, dx: float, dy: float, deadzone: float) -> None:
        if not self._active:
            return
        self._dx = dx
        self._dy = dy
        self._deadzone = deadzone
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._active or not self._paintArmed:
            return
        painter = QPainter(self)
        sector = _activeSector(self._dx, self._dy, self._deadzone)
        _drawOriginGlyph(painter, GLYPH_SIZE // 2, GLYPH_SIZE // 2, sector)
        painter.end()


class CursorController:
    """Daemon → Qt bridge. Name kept so daemon imports stay stable."""

    def __init__(self) -> None:
        self._marker = _OriginMarker()
        self._timer = QTimer()
        self._timer.setInterval(8)
        self._queue: list[tuple] = []
        self._timer.timeout.connect(self._pump)
        self._timer.start()

    def requestShow(self, x: int = 0, y: int = 0) -> None:
        self._queue.append(("show", x, y))

    def requestHide(self) -> None:
        self._queue.append(("hide",))

    def requestDirection(self, dx: float, dy: float, deadzone: float) -> None:
        self._queue.append(("dir", dx, dy, deadzone))

    def _pump(self) -> None:
        if not self._queue:
            return
        batch = self._queue
        self._queue = []
        pendingDir = None
        for pending in batch:
            kind = pending[0]
            if kind == "show":
                _, x, y = pending
                self._marker.showAt(int(x), int(y))
                pendingDir = None
            elif kind == "hide":
                self._marker.hideMarker()
                pendingDir = None
            elif kind == "dir":
                pendingDir = pending
        if pendingDir is not None:
            _, dx, dy, deadzone = pendingDir
            self._marker.setDirection(dx, dy, deadzone)
