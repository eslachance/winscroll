"""Device-loss, multi-pointer bank, and reconnect helpers."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from winmiddle.devices import (
    DeviceLostError,
    PointerBank,
    PointerDevice,
    PointerInfo,
    closePointerDevice,
    filterPointerInfos,
    iterDeviceEventsWithExtras,
    waitForPointerDevice,
)


def testDeviceLostErrorOnReadFailure() -> None:
    device = MagicMock()
    device.fd = 3
    device.read.side_effect = OSError(19, "No such device")

    with patch("winmiddle.devices.select.select", return_value=([3], [], [])):
        gen = iterDeviceEventsWithExtras(device, [], timeoutSec=0.01)
        raised = False
        try:
            next(gen)
        except DeviceLostError:
            raised = True
        assert raised


def testDeviceLostErrorOnSelectFailure() -> None:
    device = MagicMock()
    device.fd = 3

    with patch(
        "winmiddle.devices.select.select",
        side_effect=OSError(9, "Bad file descriptor"),
    ):
        gen = iterDeviceEventsWithExtras(device, [], timeoutSec=0.01)
        raised = False
        try:
            next(gen)
        except DeviceLostError:
            raised = True
        assert raised


def testWaitForPointerDeviceStops() -> None:
    stop = threading.Event()
    stop.set()
    assert waitForPointerDevice(stopEvent=stop, pollSec=0.01) is None


def testWaitForPointerDeviceReturnsWhenAvailable() -> None:
    stop = threading.Event()
    fake = PointerDevice(
        path="/dev/input/event99",
        name="Fake",
        vendor=0x1234,
        product=0x5678,
        device=MagicMock(),
    )
    with patch("winmiddle.devices.pickPointerDevice", return_value=fake):
        got = waitForPointerDevice(stopEvent=stop, pollSec=0.01)
    assert got is fake


def testClosePointerDeviceBestEffort() -> None:
    device = MagicMock()
    device.ungrab.side_effect = OSError("already gone")
    pointer = PointerDevice(
        path="/dev/input/event0",
        name="Gone",
        vendor=1,
        product=2,
        device=device,
    )
    closePointerDevice(pointer)
    assert pointer.device is None
    device.close.assert_called_once()


def testFilterPointerInfosKeepsAllWithoutPreference() -> None:
    infos = [
        PointerInfo("/dev/input/event1", "A", 1, 1),
        PointerInfo("/dev/input/event2", "B", 2, 2),
    ]
    assert filterPointerInfos(infos) == infos


def testFilterPointerInfosIncludesSameNameSiblings() -> None:
    infos = [
        PointerInfo("/dev/input/event10", "Keychron Mouse", 0x3434, 0x0B10),
        PointerInfo("/dev/input/event20", "Keychron Mouse", 0x3434, 0x0B11),
        PointerInfo("/dev/input/event30", "Other", 0x1111, 0x2222),
    ]
    selected = filterPointerInfos(
        infos,
        preferredPath="/dev/input/event10",
        vendor=0x3434,
        product=0x0B10,
    )
    paths = {item.path for item in selected}
    assert paths == {"/dev/input/event10", "/dev/input/event20"}


def testFilterPointerInfosUsesRememberedNames() -> None:
    infos = [
        PointerInfo("/dev/input/event20", "Keychron Mouse", 0x3434, 0x0B11),
    ]
    selected = filterPointerInfos(
        infos,
        preferredPath="/dev/input/event10",
        vendor=0x3434,
        product=0x0B10,
        preferredNames={"Keychron Mouse"},
    )
    assert [item.path for item in selected] == ["/dev/input/event20"]


def testPointerBankDropsLostAndAddsNew() -> None:
    bank = PointerBank(grab=False, rescanSec=0.01)
    first = PointerDevice(
        path="/dev/input/event1",
        name="Dongle",
        vendor=1,
        product=1,
        device=MagicMock(fd=11),
    )
    bank.byPath[first.path] = first

    probed = [
        PointerInfo("/dev/input/event1", "Dongle", 1, 1),
        PointerInfo("/dev/input/event2", "BT", 1, 2),
    ]
    opened = PointerDevice(
        path="/dev/input/event2",
        name="BT",
        vendor=1,
        product=2,
        device=MagicMock(fd=12),
    )

    with (
        patch("winmiddle.devices.probePointerInfos", return_value=probed),
        patch("winmiddle.devices.openPointerDevice", return_value=opened),
    ):
        added, removed = bank.sync()

    assert removed == []
    assert [item.path for item in added] == ["/dev/input/event2"]
    assert set(bank.byPath) == {"/dev/input/event1", "/dev/input/event2"}

    probedGone = [PointerInfo("/dev/input/event2", "BT", 1, 2)]
    with (
        patch("winmiddle.devices.probePointerInfos", return_value=probedGone),
        patch("winmiddle.devices.openPointerDevice") as openMock,
    ):
        added, removed = bank.sync()
    openMock.assert_not_called()
    assert removed == ["/dev/input/event1"]
    assert set(bank.byPath) == {"/dev/input/event2"}
