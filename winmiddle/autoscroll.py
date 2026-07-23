"""Windows-like autoscroll speed curve and state machine helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto


class Mode(Enum):
    IDLE = auto()
    PENDING_MIDDLE = auto()  # middle down; deciding click vs drag
    MIDDLE_DRAG = auto()  # passthrough middle-drag (Blender, CAD, etc.)
    AUTOSCROLL = auto()  # Windows click-to-autoscroll active


@dataclass
class ScrollSample:
    wheelY: float  # positive = scroll up (evdev REL_WHEEL)
    wheelX: float  # positive = scroll right (REL_HWHEEL)


def windowsScrollSpeed(
    dx: float,
    dy: float,
    *,
    deadzonePx: float = 8.0,
    gain: float = 0.045,
    exponent: float = 1.35,
    maxUnits: float = 28.0,
) -> ScrollSample:
    """Map cursor offset from origin → continuous wheel units (Windows-ish).

    Moving the pointer *down* from the origin scrolls *down* (negative REL_WHEEL).
    Deadzone in the center matches the classic four-way autoscroll icon.
    """
    distance = math.hypot(dx, dy)
    if distance < deadzonePx:
        return ScrollSample(0.0, 0.0)

    excess = distance - deadzonePx
    magnitude = min(maxUnits, gain * (excess**exponent))
    nx = dx / distance
    ny = dy / distance
    # Screen y grows downward; Windows scrolls down when pointer is below origin.
    return ScrollSample(wheelY=-ny * magnitude, wheelX=nx * magnitude)


def shouldStartDrag(dx: float, dy: float, dragThresholdPx: float) -> bool:
    return math.hypot(dx, dy) >= dragThresholdPx
