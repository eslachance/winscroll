"""Built-in icon for the settings app / tray (no external assets required)."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def winmiddleIcon(size: int = 128) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = size * 0.08
    outer = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)

    # Soft circular badge — reads fine on light and dark Plasma themes.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#1f6feb"))
    painter.drawEllipse(outer)

    cx = size / 2
    cy = size / 2
    arm = size * 0.28
    gap = size * 0.07
    stroke = max(2.0, size * 0.07)

    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)

    # Four-way scroll cross (matches the origin glyph idea).
    painter.drawLine(QPointF(cx, cy - gap), QPointF(cx, cy - arm))
    painter.drawLine(QPointF(cx, cy + gap), QPointF(cx, cy + arm))
    painter.drawLine(QPointF(cx - gap, cy), QPointF(cx - arm, cy))
    painter.drawLine(QPointF(cx + gap, cy), QPointF(cx + arm, cy))

    # Middle “button” dot.
    painter.setBrush(QColor("#ffffff"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPointF(cx, cy), size * 0.07, size * 0.07)

    # Tiny mouse outline hint.
    mousePath = QPainterPath()
    mouseLeft = size * 0.68
    mouseTop = size * 0.62
    mouseW = size * 0.22
    mouseH = size * 0.28
    mousePath.addRoundedRect(QRectF(mouseLeft, mouseTop, mouseW, mouseH), mouseW * 0.35, mouseW * 0.35)
    painter.setPen(QPen(QColor(255, 255, 255, 210), max(1.0, size * 0.03)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(mousePath)
    painter.drawLine(
        QPointF(mouseLeft + mouseW / 2, mouseTop + mouseH * 0.12),
        QPointF(mouseLeft + mouseW / 2, mouseTop + mouseH * 0.42),
    )

    painter.end()
    return QIcon(pixmap)
