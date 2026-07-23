from winmiddle.autoscroll import shouldStartDrag, windowsScrollSpeed


def testDeadzone():
    sample = windowsScrollSpeed(0, 0)
    assert sample.wheelX == 0 and sample.wheelY == 0
    sample = windowsScrollSpeed(3, 3, deadzonePx=8)
    assert sample.wheelX == 0 and sample.wheelY == 0


def testScrollDownWhenPointerBelow():
    sample = windowsScrollSpeed(0, 40, deadzonePx=8)
    assert sample.wheelY < 0  # pointer below origin → scroll down
    assert abs(sample.wheelX) < 1e-6


def testScrollRight():
    sample = windowsScrollSpeed(40, 0, deadzonePx=8)
    assert sample.wheelX > 0
    assert abs(sample.wheelY) < 1e-6


def testDragThreshold():
    assert not shouldStartDrag(2, 2, 6)
    assert shouldStartDrag(10, 0, 6)
