"""Track Ctrl/Alt/Shift/Super from keyboards (no exclusive grab)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from evdev import InputDevice, ecodes, list_devices

log = logging.getLogger("winmiddle.modifiers")

_MODIFIER_CODES = (
    ecodes.KEY_LEFTCTRL,
    ecodes.KEY_RIGHTCTRL,
    ecodes.KEY_LEFTALT,
    ecodes.KEY_RIGHTALT,
    ecodes.KEY_LEFTSHIFT,
    ecodes.KEY_RIGHTSHIFT,
    ecodes.KEY_LEFTMETA,
    ecodes.KEY_RIGHTMETA,
)

MODIFIER_ALIASES = {
    "none": (),
    "ctrl": (ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL),
    "control": (ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL),
    "alt": (ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT),
    "shift": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT),
    "super": (ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA),
    "meta": (ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA),
    "win": (ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA),
    "mod4": (ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA),
}


def normalizeModifierName(name: str) -> str:
    key = (name or "none").strip().lower()
    if key not in MODIFIER_ALIASES:
        raise ValueError(
            f"Unknown modifier {name!r}; use none, ctrl, alt, shift, or super"
        )
    if key == "control":
        return "ctrl"
    if key in {"meta", "win", "mod4"}:
        return "super"
    return key


@dataclass
class ModifierTracker:
    """Watch keyboard EV_KEY for modifier down/up without grabbing devices."""

    devices: list[InputDevice] = field(default_factory=list)
    _down: set[int] = field(default_factory=set)

    @classmethod
    def open(cls) -> ModifierTracker:
        tracker = cls()
        for path in list_devices():
            try:
                device = InputDevice(path)
            except OSError:
                continue
            keys = device.capabilities().get(ecodes.EV_KEY, [])
            # Keyboards have KEY_A; also accept devices that only expose modifiers.
            if ecodes.KEY_A not in keys and ecodes.KEY_LEFTCTRL not in keys:
                continue
            if not os.access(path, os.R_OK):
                continue
            try:
                for code in device.active_keys():
                    if code in _MODIFIER_CODES:
                        tracker._down.add(code)
                tracker.devices.append(device)
            except OSError:
                continue
        log.info("modifier tracker watching %d keyboard device(s)", len(tracker.devices))
        return tracker

    @property
    def fds(self) -> list[int]:
        return [device.fd for device in self.devices]

    def deviceForFd(self, fd: int) -> InputDevice | None:
        for device in self.devices:
            if device.fd == fd:
                return device
        return None

    def handleEvent(self, event) -> None:
        if event.type != ecodes.EV_KEY:
            return
        # value: 0=up 1=down 2=repeat
        if event.value == 0:
            self._down.discard(event.code)
        elif event.value == 1:
            self._down.add(event.code)

    def drain(self, device: InputDevice) -> None:
        try:
            for event in device.read():
                self.handleEvent(event)
        except BlockingIOError:
            return
        except OSError:
            return

    def isModifierHeld(self, modifierName: str) -> bool:
        name = normalizeModifierName(modifierName)
        codes = MODIFIER_ALIASES[name]
        if not codes:
            return True  # "none" → always satisfied
        return any(code in self._down for code in codes)

    def close(self) -> None:
        for device in self.devices:
            try:
                device.close()
            except Exception:
                pass
        self.devices.clear()
