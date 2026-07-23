"""Find, grab, and mirror pointer devices via evdev/uinput."""

from __future__ import annotations

import logging
import os
import select
import time
from dataclasses import dataclass
from typing import Iterator

from evdev import InputDevice, InputEvent, UInput, ecodes, list_devices

log = logging.getLogger("winmiddle.devices")

MOUSE_BUTTONS = [
    ecodes.BTN_LEFT,
    ecodes.BTN_RIGHT,
    ecodes.BTN_MIDDLE,
    ecodes.BTN_SIDE,
    ecodes.BTN_EXTRA,
    ecodes.BTN_FORWARD,
    ecodes.BTN_BACK,
    ecodes.BTN_TASK,
]

REL_AXES = [
    ecodes.REL_X,
    ecodes.REL_Y,
    ecodes.REL_WHEEL,
    ecodes.REL_HWHEEL,
    ecodes.REL_WHEEL_HI_RES,
    ecodes.REL_HWHEEL_HI_RES,
    ecodes.REL_MISC,
]


@dataclass
class PointerDevice:
    path: str
    name: str
    vendor: int
    product: int
    device: InputDevice


def listPointerDevices() -> list[PointerDevice]:
    found: list[PointerDevice] = []
    for path in list_devices():
        try:
            device = InputDevice(path)
        except OSError:
            continue
        caps = device.capabilities()
        keys = caps.get(ecodes.EV_KEY, [])
        rels = caps.get(ecodes.EV_REL, [])
        if ecodes.BTN_MIDDLE not in keys:
            continue
        if ecodes.REL_X not in rels or ecodes.REL_Y not in rels:
            continue
        info = device.info
        found.append(
            PointerDevice(
                path=path,
                name=device.name,
                vendor=info.vendor,
                product=info.product,
                device=device,
            )
        )
    return found


def pickPointerDevice(
    preferredPath: str | None = None,
    vendor: int | None = None,
    product: int | None = None,
) -> PointerDevice:
    devices = listPointerDevices()
    if not devices:
        raise RuntimeError(
            "No mouse with a middle button found under /dev/input. "
            "Check permissions (loginctl seat ACL or input group)."
        )

    if preferredPath:
        for item in devices:
            if item.path == preferredPath:
                return item

    if vendor is not None and product is not None:
        for item in devices:
            if item.vendor == vendor and item.product == product:
                return item

    # Prefer devices the user can open RW (seat ACL)
    for item in devices:
        if os.access(item.path, os.R_OK | os.W_OK):
            return item

    return devices[0]


def createVirtualMouse(name: str = "winmiddle virtual mouse") -> UInput:
    capabilities = {
        ecodes.EV_KEY: MOUSE_BUTTONS,
        ecodes.EV_REL: REL_AXES,
    }
    return UInput(capabilities, name=name, bustype=ecodes.BUS_USB)


def grabDevice(device: InputDevice) -> None:
    # Retry briefly — another process may hold it during login
    lastError: Exception | None = None
    for _ in range(20):
        try:
            device.grab()
            return
        except OSError as error:
            lastError = error
            time.sleep(0.1)
    raise RuntimeError(f"Failed to grab {device.path}: {lastError}")


def iterDeviceEvents(
    device: InputDevice, timeoutSec: float = 0.01
) -> Iterator[list[InputEvent]]:
    while True:
        ready, _, _ = select.select([device.fd], [], [], timeoutSec)
        if not ready:
            yield []
            continue
        batch = list(device.read())
        yield batch


def forwardEvent(ui: UInput, event: InputEvent) -> None:
    ui.write(event.type, event.code, event.value)


def injectRelative(ui: UInput, code: int, value: int) -> None:
    if value == 0:
        return
    ui.write(ecodes.EV_REL, code, value)


def injectButton(ui: UInput, code: int, value: int) -> None:
    ui.write(ecodes.EV_KEY, code, value)


def syn(ui: UInput) -> None:
    ui.syn()
