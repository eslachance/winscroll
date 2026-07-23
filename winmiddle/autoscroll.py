"""Windows-like autoscroll speed curve and state machine helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto


class Mode(Enum):
    IDLE = auto()
    PENDING_MIDDLE = auto()  # middle down; deciding tap vs hold-scroll vs toggle vs drag
    MIDDLE_DRAG = auto()  # passthrough middle-drag (Blender, CAD, etc.)
    AUTOSCROLL = auto()  # toggle mode: click to enter, click to exit
    HOLD_AUTOSCROLL = auto()  # hold mode: scroll while middle is held


@dataclass
class ScrollSample:
    """Wheel motion in notches per second (1.0 = one classic detent / sec)."""

    notchesPerSecY: float  # positive = scroll up (evdev REL_WHEEL positive)
    notchesPerSecX: float  # positive = scroll right


def windowsScrollSpeed(
    dx: float,
    dy: float,
    *,
    deadzonePx: float = 12.0,
    refDistancePx: float = 100.0,
    refNotchesPerSec: float = 10.0,
    maxNotchesPerSec: float = 28.0,
    power: float = 1.35,
) -> ScrollSample:
    """Map cursor offset from origin → notches/sec (Windows-ish).

    Moving the pointer *down* from the origin scrolls *down* (negative Y notches).
    Speed at `refDistancePx` past the deadzone equals `refNotchesPerSec`, then
    curves with `power` and clamps at `maxNotchesPerSec`.
    """
    distance = math.hypot(dx, dy)
    if distance < deadzonePx:
        return ScrollSample(0.0, 0.0)

    excess = distance - deadzonePx
    scale = max(1e-6, refDistancePx)
    notchesPerSec = refNotchesPerSec * ((excess / scale) ** power)
    notchesPerSec = min(maxNotchesPerSec, notchesPerSec)

    nx = dx / distance
    ny = dy / distance
    # Screen y grows downward; Windows scrolls down when pointer is below origin.
    return ScrollSample(
        notchesPerSecY=-ny * notchesPerSec,
        notchesPerSecX=nx * notchesPerSec,
    )


def shouldStartDrag(dx: float, dy: float, dragThresholdPx: float) -> bool:
    return math.hypot(dx, dy) >= dragThresholdPx
