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


VIRTUAL_MOUSE_NAME = "winmiddle virtual mouse"


@dataclass
class PointerDevice:
    path: str
    name: str
    vendor: int
    product: int
    device: InputDevice | None
    accessible: bool = True


def _eventNodePaths() -> list[str]:
    """All /dev/input/event* nodes, including ones we cannot open yet."""
    try:
        names = os.listdir("/dev/input")
    except OSError:
        return []
    paths = [f"/dev/input/{name}" for name in names if name.startswith("event")]
    paths.sort(key=lambda p: int(p.rsplit("event", 1)[-1]) if p.rsplit("event", 1)[-1].isdigit() else p)
    return paths


def _sysfsCapsHasBit(capsPath: str, code: int) -> bool:
    """Return True if sysfs capability bitmap file contains bit `code`."""
    try:
        text = open(capsPath, encoding="utf-8").read().strip()
    except OSError:
        return False
    if not text:
        return False
    # Sysfs prints longs little-endian word order: least-significant word last.
    words = [int(part, 16) for part in text.split()]
    words.reverse()
    bitIndex = code
    wordIndex = bitIndex // 64
    if wordIndex >= len(words):
        # Some kernels print 32-bit words
        words = [int(part, 16) for part in text.split()]
        words.reverse()
        wordIndex = bitIndex // 32
        if wordIndex >= len(words):
            return False
        return bool(words[wordIndex] & (1 << (bitIndex % 32)))
    return bool(words[wordIndex] & (1 << (bitIndex % 64)))


def _looksLikeMiddlePointerFromSysfs(eventPath: str) -> tuple[bool, str]:
    """Detect middle-button relative pointers via sysfs (no device open needed)."""
    sysName = os.path.basename(eventPath)
    base = f"/sys/class/input/{sysName}/device"
    namePath = f"{base}/name"
    try:
        name = open(namePath, encoding="utf-8").read().strip()
    except OSError:
        return False, ""
    if name == VIRTUAL_MOUSE_NAME:
        return False, name
    keyOk = _sysfsCapsHasBit(f"{base}/capabilities/key", ecodes.BTN_MIDDLE)
    relX = _sysfsCapsHasBit(f"{base}/capabilities/rel", ecodes.REL_X)
    relY = _sysfsCapsHasBit(f"{base}/capabilities/rel", ecodes.REL_Y)
    return keyOk and relX and relY, name


def _readIdFromSysfs(eventPath: str) -> tuple[int, int]:
    sysName = os.path.basename(eventPath)
    base = f"/sys/class/input/{sysName}/device/id"
    try:
        vendor = int(open(f"{base}/vendor", encoding="utf-8").read().strip(), 16)
        product = int(open(f"{base}/product", encoding="utf-8").read().strip(), 16)
    except (OSError, ValueError):
        return 0, 0
    return vendor, product


def listPointerDevices(*, requireAccess: bool = True) -> list[PointerDevice]:
    """List middle-button relative pointers.

    When requireAccess is False, also include devices visible in sysfs that the
    current user cannot open yet (missing seat ACL / input group). Those entries
    have device=None and accessible=False.
    """
    found: list[PointerDevice] = []
    seen: set[str] = set()

    for path in list_devices():
        try:
            device = InputDevice(path)
        except OSError:
            continue
        if device.name == VIRTUAL_MOUSE_NAME:
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
                accessible=True,
            )
        )
        seen.add(path)

    if not requireAccess:
        for path in _eventNodePaths():
            if path in seen:
                continue
            ok, name = _looksLikeMiddlePointerFromSysfs(path)
            if not ok:
                continue
            vendor, product = _readIdFromSysfs(path)
            found.append(
                PointerDevice(
                    path=path,
                    name=name or path,
                    vendor=vendor,
                    product=product,
                    device=None,
                    accessible=False,
                )
            )

    return found


def pickPointerDevice(
    preferredPath: str | None = None,
    vendor: int | None = None,
    product: int | None = None,
) -> PointerDevice:
    devices = [d for d in listPointerDevices(requireAccess=False) if d.accessible]
    if not devices:
        blocked = [d for d in listPointerDevices(requireAccess=False) if not d.accessible]
        if blocked:
            names = ", ".join(d.name for d in blocked)
            raise RuntimeError(
                f"Found mouse(s) but cannot open them ({names}). "
                "Run winmiddle --setup (mouse udev rule) or re-login after joining the input group."
            )
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


def iterDeviceEventsWithExtras(
    device: InputDevice,
    extraFds: list[int],
    timeoutSec: float = 0.01,
) -> Iterator[tuple[list[InputEvent], list[int]]]:
    """Yield (mouse_batch, ready_extra_fds) multiplexed with select."""
    watch = [device.fd, *extraFds]
    while True:
        ready, _, _ = select.select(watch, [], [], timeoutSec)
        if not ready:
            yield [], []
            continue
        mouseBatch: list[InputEvent] = []
        if device.fd in ready:
            mouseBatch = list(device.read())
        extras = [fd for fd in ready if fd != device.fd]
        yield mouseBatch, extras


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
