"""Unit tests for the notches/sec autoscroll curve."""

from __future__ import annotations

from winmiddle.autoscroll import shouldStartDrag, windowsScrollSpeed
from winmiddle.config import Config, applySpeedPreset


def testDeadzone():
    sample = windowsScrollSpeed(0, 0)
    assert sample.notchesPerSecX == 0 and sample.notchesPerSecY == 0
    sample = windowsScrollSpeed(3, 3, deadzonePx=8)
    assert sample.notchesPerSecX == 0 and sample.notchesPerSecY == 0


def testScrollDownWhenPointerBelow():
    sample = windowsScrollSpeed(0, 40, deadzonePx=8, refDistancePx=100, refNotchesPerSec=10)
    assert sample.notchesPerSecY < 0  # pointer below origin → scroll down
    assert abs(sample.notchesPerSecX) < 1e-6


def testScrollRight():
    sample = windowsScrollSpeed(40, 0, deadzonePx=8, refDistancePx=100, refNotchesPerSec=10)
    assert sample.notchesPerSecX > 0
    assert abs(sample.notchesPerSecY) < 1e-6


def testDragThreshold():
    assert not shouldStartDrag(2, 2, 6)
    assert shouldStartDrag(10, 0, 6)


def testSpeedPresetsRank():
    speeds = {}
    for name in ("slow", "normal", "fast"):
        cfg = Config()
        applySpeedPreset(cfg, name)
        sample = windowsScrollSpeed(
            0,
            100,
            deadzonePx=cfg.deadzonePx,
            refDistancePx=cfg.refDistancePx,
            refNotchesPerSec=cfg.refNotchesPerSec,
            maxNotchesPerSec=cfg.maxNotchesPerSec,
            power=cfg.scrollPower,
        )
        speeds[name] = abs(sample.notchesPerSecY)
    assert speeds["slow"] < speeds["normal"] < speeds["fast"]


if __name__ == "__main__":
    testDeadzone()
    testScrollDownWhenPointerBelow()
    testScrollRight()
    testDragThreshold()
    testSpeedPresetsRank()
    print("ok")
