"""Find, grab, and mirror pointer devices via evdev/uinput."""

from __future__ import annotations

import logging
import os
import select
import threading
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


class DeviceLostError(OSError):
    """Physical pointer disappeared (sleep, power-off, unplug, BT drop)."""


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


def waitForPointerDevice(
    preferredPath: str | None = None,
    vendor: int | None = None,
    product: int | None = None,
    *,
    stopEvent: threading.Event | None = None,
    pollSec: float = 1.0,
) -> PointerDevice | None:
    """Block until a matching pointer is available, or stopEvent is set.

    Returns None if stopped while waiting. Used at startup (mouse not ready yet)
    and after sleep / power-cycle when the event node disappears.
    """
    attempt = 0
    while stopEvent is None or not stopEvent.is_set():
        try:
            return pickPointerDevice(preferredPath, vendor, product)
        except RuntimeError as error:
            attempt += 1
            if attempt == 1 or attempt % 10 == 0:
                log.warning("waiting for pointer device: %s", error)
            if stopEvent is not None:
                if stopEvent.wait(pollSec):
                    return None
            else:
                time.sleep(pollSec)
    return None


def closePointerDevice(pointer: PointerDevice | None) -> None:
    """Best-effort ungrab + close after disconnect or before rebind."""
    if pointer is None or pointer.device is None:
        return
    try:
        pointer.device.ungrab()
    except Exception:
        pass
    try:
        pointer.device.close()
    except Exception:
        pass
    pointer.device = None


@dataclass(frozen=True)
class PointerInfo:
    """Probe-only pointer identity (no open fd)."""

    path: str
    name: str
    vendor: int
    product: int


def probePointerInfos() -> list[PointerInfo]:
    """List middle-button pointers without retaining open fds."""
    found: list[PointerInfo] = []
    for path in list_devices():
        try:
            device = InputDevice(path)
        except OSError:
            continue
        try:
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
                PointerInfo(
                    path=path,
                    name=device.name,
                    vendor=info.vendor,
                    product=info.product,
                )
            )
        finally:
            try:
                device.close()
            except Exception:
                pass
    return found


def _preferenceActive(
    preferredPath: str | None,
    vendor: int | None,
    product: int | None,
) -> bool:
    return bool(preferredPath) or (vendor is not None and product is not None)


def filterPointerInfos(
    infos: list[PointerInfo],
    *,
    preferredPath: str | None = None,
    vendor: int | None = None,
    product: int | None = None,
    preferredNames: set[str] | None = None,
) -> list[PointerInfo]:
    """Keep all pointers, or those matching path / vid:pid / remembered name.

    Multi-mode mice (2.4G / USB / BT) often keep the same name while changing
    path and product id. Remembered names keep those siblings in the bank.
    """
    if not _preferenceActive(preferredPath, vendor, product) and not preferredNames:
        return list(infos)

    names = set(preferredNames or ())
    for info in infos:
        if preferredPath and info.path == preferredPath:
            names.add(info.name)
        if (
            vendor is not None
            and product is not None
            and info.vendor == vendor
            and info.product == product
        ):
            names.add(info.name)

    selected: list[PointerInfo] = []
    for info in infos:
        if preferredPath and info.path == preferredPath:
            selected.append(info)
            continue
        if (
            vendor is not None
            and product is not None
            and info.vendor == vendor
            and info.product == product
        ):
            selected.append(info)
            continue
        if info.name in names:
            selected.append(info)
    return selected


def openPointerDevice(path: str) -> PointerDevice:
    device = InputDevice(path)
    info = device.info
    return PointerDevice(
        path=path,
        name=device.name,
        vendor=info.vendor,
        product=info.product,
        device=device,
        accessible=True,
    )


class PointerBank:
    """Open/grab every matching mouse and hotplug-rescan for mode switches.

    Wireless multi-mode mice often leave the old event node alive-but-silent
    when switching 2.4G ↔ BT ↔ USB. Watching only one fd never sees the new
    transport; this bank multiplexes all matching nodes and picks up new ones.
    """

    def __init__(
        self,
        *,
        preferredPath: str | None = None,
        vendor: int | None = None,
        product: int | None = None,
        grab: bool = True,
        rescanSec: float = 1.0,
    ) -> None:
        self.preferredPath = preferredPath
        self.vendor = vendor
        self.product = product
        self.grab = grab
        self.rescanSec = max(0.2, rescanSec)
        self.byPath: dict[str, PointerDevice] = {}
        self.preferredNames: set[str] = set()
        self._nextRescan = 0.0

    def __len__(self) -> int:
        return len(self.byPath)

    def closeAll(self) -> None:
        for pointer in list(self.byPath.values()):
            closePointerDevice(pointer)
        self.byPath.clear()

    def _rememberNames(self, infos: list[PointerInfo]) -> None:
        for info in infos:
            if self.preferredPath and info.path == self.preferredPath:
                self.preferredNames.add(info.name)
            if (
                self.vendor is not None
                and self.product is not None
                and info.vendor == self.vendor
                and info.product == self.product
            ):
                self.preferredNames.add(info.name)

    def sync(self) -> tuple[list[PointerDevice], list[str]]:
        """Open new matching pointers, drop removed ones. Returns (added, removedPaths)."""
        probed = probePointerInfos()
        self._rememberNames(probed)
        wanted = filterPointerInfos(
            probed,
            preferredPath=self.preferredPath,
            vendor=self.vendor,
            product=self.product,
            preferredNames=self.preferredNames,
        )
        wantedPaths = {info.path for info in wanted}

        removedPaths: list[str] = []
        for path in list(self.byPath):
            if path not in wantedPaths:
                closePointerDevice(self.byPath.pop(path))
                removedPaths.append(path)
                log.info("pointer removed %s", path)

        added: list[PointerDevice] = []
        for info in wanted:
            if info.path in self.byPath:
                continue
            try:
                pointer = openPointerDevice(info.path)
            except OSError as error:
                log.warning("could not open %s: %s", info.path, error)
                continue
            if self.grab:
                try:
                    grabDevice(pointer.device)
                except RuntimeError as error:
                    log.warning("could not grab %s: %s", info.path, error)
                    closePointerDevice(pointer)
                    continue
            self.byPath[info.path] = pointer
            added.append(pointer)
            log.info(
                "pointer added %s (%s) vid=%04x pid=%04x%s",
                pointer.path,
                pointer.name,
                pointer.vendor,
                pointer.product,
                " [grabbed]" if self.grab else "",
            )
        return added, removedPaths

    def dropPath(self, path: str) -> None:
        pointer = self.byPath.pop(path, None)
        if pointer is not None:
            closePointerDevice(pointer)
            log.info("pointer dropped %s", path)

    def waitUntilReady(
        self,
        stopEvent: threading.Event | None = None,
        pollSec: float = 1.0,
    ) -> bool:
        """Sync until at least one pointer is open, or stopEvent is set."""
        attempt = 0
        while stopEvent is None or not stopEvent.is_set():
            self.sync()
            if self.byPath:
                return True
            attempt += 1
            if attempt == 1 or attempt % 10 == 0:
                log.warning("waiting for pointer device(s)")
            if stopEvent is not None:
                if stopEvent.wait(pollSec):
                    return False
            else:
                time.sleep(pollSec)
        return False

    def maybeRescan(self, now: float | None = None) -> tuple[list[PointerDevice], list[str]]:
        ts = time.monotonic() if now is None else now
        if ts < self._nextRescan:
            return [], []
        self._nextRescan = ts + self.rescanSec
        return self.sync()


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
        try:
            ready, _, _ = select.select([device.fd], [], [], timeoutSec)
        except (OSError, ValueError) as error:
            raise DeviceLostError(str(error)) from error
        if not ready:
            yield []
            continue
        try:
            batch = list(device.read())
        except OSError as error:
            raise DeviceLostError(str(error)) from error
        yield batch


def iterDeviceEventsWithExtras(
    device: InputDevice,
    extraFds: list[int],
    timeoutSec: float = 0.01,
) -> Iterator[tuple[list[InputEvent], list[int]]]:
    """Yield (mouse_batch, ready_extra_fds) multiplexed with select.

    Raises DeviceLostError when the physical mouse fd dies (ENODEV, etc.).
    """
    watch = [device.fd, *extraFds]
    while True:
        try:
            ready, _, _ = select.select(watch, [], [], timeoutSec)
        except (OSError, ValueError) as error:
            raise DeviceLostError(str(error)) from error
        if not ready:
            yield [], []
            continue
        mouseBatch: list[InputEvent] = []
        if device.fd in ready:
            try:
                mouseBatch = list(device.read())
            except OSError as error:
                raise DeviceLostError(str(error)) from error
        extras = [fd for fd in ready if fd != device.fd]
        yield mouseBatch, extras


def iterPointerBankEvents(
    bank: PointerBank,
    extraFds: list[int],
    timeoutSec: float = 0.01,
) -> Iterator[tuple[list[InputEvent], list[int]]]:
    """Yield (mouse_batch, ready_extra_fds) from every open pointer in the bank.

    Hotplug-rescans periodically. Individual dead nodes are dropped; raises
    DeviceLostError only when the bank becomes empty.
    """
    while True:
        bank.maybeRescan()
        if not bank.byPath:
            raise DeviceLostError("no pointer devices available")

        fdToPath = {
            pointer.device.fd: path
            for path, pointer in bank.byPath.items()
            if pointer.device is not None
        }
        watch = list(fdToPath.keys()) + list(extraFds)
        try:
            ready, _, _ = select.select(watch, [], [], timeoutSec)
        except (OSError, ValueError) as error:
            log.warning("select failed (%s) — rescanning pointers", error)
            bank.closeAll()
            bank.sync()
            if not bank.byPath:
                raise DeviceLostError(str(error)) from error
            continue

        if not ready:
            yield [], []
            continue

        mouseBatch: list[InputEvent] = []
        lost: list[str] = []
        for fd in ready:
            path = fdToPath.get(fd)
            if path is None:
                continue
            pointer = bank.byPath.get(path)
            if pointer is None or pointer.device is None:
                continue
            try:
                mouseBatch.extend(pointer.device.read())
            except OSError:
                lost.append(path)

        for path in lost:
            bank.dropPath(path)
        if not bank.byPath and not mouseBatch:
            raise DeviceLostError("all pointer devices disappeared")

        extras = [fd for fd in ready if fd not in fdToPath]
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
