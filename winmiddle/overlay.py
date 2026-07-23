"""Windows-style four-way autoscroll origin overlay."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QWidget

log = logging.getLogger("winmiddle.overlay")


class AutoscrollOverlay(QWidget):
    """Fullscreen click-through canvas; paints the classic origin glyph."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._origin = QPoint(0, 0)
        self._active = False
        self._screenIndex = 0
        self.hide()

        # Re-assert geometry if screens change
        QGuiApplication.instance().screenAdded.connect(self._refreshGeometry)  # type: ignore[union-attr]
        QGuiApplication.instance().screenRemoved.connect(self._refreshGeometry)  # type: ignore[union-attr]

    def _refreshGeometry(self, *_args) -> None:
        if not self._active:
            return
        self._coverScreenAt(self._origin)

    def _coverScreenAt(self, globalPos: QPoint) -> None:
        screen = QGuiApplication.screenAt(globalPos)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        self.setGeometry(geo)
        self._screenIndex = QGuiApplication.screens().index(screen)

    def showAt(self, globalX: int, globalY: int) -> None:
        self._origin = QPoint(globalX, globalY)
        self._active = True
        self._coverScreenAt(self._origin)
        self.show()
        self.raise_()
        self.update()

    def hideOverlay(self) -> None:
        self._active = False
        self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._active:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        local = self._origin - self.geometry().topLeft()
        cx, cy = local.x(), local.y()
        radius = 14

        # Outer ring
        painter.setPen(QPen(QColor(40, 40, 40, 220), 2))
        painter.setBrush(QColor(250, 250, 250, 210))
        painter.drawEllipse(QPoint(cx, cy), radius, radius)

        # Crosshair arrows (N/E/S/W)
        painter.setPen(QPen(QColor(30, 30, 30, 240), 2))
        arm = 8
        # North
        painter.drawLine(cx, cy - 4, cx, cy - arm)
        painter.drawLine(cx, cy - arm, cx - 3, cy - arm + 4)
        painter.drawLine(cx, cy - arm, cx + 3, cy - arm + 4)
        # South
        painter.drawLine(cx, cy + 4, cx, cy + arm)
        painter.drawLine(cx, cy + arm, cx - 3, cy + arm - 4)
        painter.drawLine(cx, cy + arm, cx + 3, cy + arm - 4)
        # West
        painter.drawLine(cx - 4, cy, cx - arm, cy)
        painter.drawLine(cx - arm, cy, cx - arm + 4, cy - 3)
        painter.drawLine(cx - arm, cy, cx - arm + 4, cy + 3)
        # East
        painter.drawLine(cx + 4, cy, cx + arm, cy)
        painter.drawLine(cx + arm, cy, cx + arm - 4, cy - 3)
        painter.drawLine(cx + arm, cy, cx + arm - 4, cy + 3)

        # Center dot
        painter.setBrush(QColor(30, 30, 30, 240))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(cx, cy), 2, 2)
        painter.end()


class OverlayController:
    """Thread-safe bridge: daemon thread → Qt main thread."""

    def __init__(self, overlay: AutoscrollOverlay) -> None:
        self.overlay = overlay
        self._timer = QTimer()
        self._timer.setInterval(16)
        self._pendingShow: tuple[int, int] | None = None
        self._pendingHide = False
        self._timer.timeout.connect(self._pump)
        self._timer.start()

    def requestShow(self, x: int, y: int) -> None:
        self._pendingShow = (x, y)
        self._pendingHide = False

    def requestHide(self) -> None:
        self._pendingHide = True
        self._pendingShow = None

    def _pump(self) -> None:
        if self._pendingHide:
            self.overlay.hideOverlay()
            self._pendingHide = False
        if self._pendingShow is not None:
            x, y = self._pendingShow
            self._pendingShow = None
            self.overlay.showAt(x, y)
