"""Core input loop: Windows click-to-autoscroll + middle-drag passthrough."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from evdev import InputEvent, ecodes

from winmiddle.autoscroll import Mode, shouldStartDrag, windowsScrollSpeed
from winmiddle.devices import (
    createVirtualMouse,
    forwardEvent,
    grabDevice,
    injectButton,
    injectRelative,
    iterDeviceEvents,
    pickPointerDevice,
    syn,
)
from winmiddle.focus import FocusHub, matchesAny

if TYPE_CHECKING:
    from evdev import UInput

    from winmiddle.config import Config
    from winmiddle.overlay import OverlayController

log = logging.getLogger("winmiddle.daemon")


class MiddleDaemon:
    def __init__(
        self,
        config: Config,
        focusHub: FocusHub,
        overlay: OverlayController | None,
    ) -> None:
        self.config = config
        self.focusHub = focusHub
        self.overlay = overlay
        self.mode = Mode.IDLE
        self._stop = threading.Event()
        self._originX = 0.0
        self._originY = 0.0
        self._cursorX = 0.0
        self._cursorY = 0.0
        self._pendingDx = 0.0
        self._pendingDy = 0.0
        self._wheelAccumY = 0.0
        self._wheelAccumX = 0.0
        self._lastScrollTs = 0.0
        self._autoscrollOriginScreen = (0, 0)
        self.ui: UInput | None = None
        self.pointer = None

    def stop(self) -> None:
        self._stop.set()

    def _shouldPassthroughMiddle(self) -> bool:
        focus = self.focusHub.snapshot()
        if matchesAny(focus, self.config.passthroughApps):
            return True
        if matchesAny(focus, self.config.nativeMiddleApps):
            return True
        return False

    def _enterAutoscroll(self) -> None:
        focus = self.focusHub.snapshot()
        self._autoscrollOriginScreen = (focus.cursorX, focus.cursorY)
        # Keep tracking from current relative origin (zeros).
        self._originX = self._cursorX
        self._originY = self._cursorY
        self._wheelAccumX = 0.0
        self._wheelAccumY = 0.0
        self._lastScrollTs = time.monotonic()
        self.mode = Mode.AUTOSCROLL
        log.info(
            "autoscroll ON at screen (%s,%s) focus=%s",
            focus.cursorX,
            focus.cursorY,
            focus.resourceClass or "?",
        )
        if self.overlay and self.config.showOverlay:
            self.overlay.requestShow(focus.cursorX, focus.cursorY)

    def _leaveAutoscroll(self) -> None:
        if self.mode == Mode.AUTOSCROLL:
            log.info("autoscroll OFF")
        self.mode = Mode.IDLE
        self._wheelAccumX = 0.0
        self._wheelAccumY = 0.0
        if self.overlay:
            self.overlay.requestHide()

    def _flushScroll(self, ui: UInput) -> None:
        now = time.monotonic()
        interval = 1.0 / max(1.0, self.config.scrollHz)
        if now - self._lastScrollTs < interval:
            return
        self._lastScrollTs = now

        dx = self._cursorX - self._originX
        dy = self._cursorY - self._originY
        sample = windowsScrollSpeed(
            dx,
            dy,
            deadzonePx=self.config.deadzonePx,
            gain=self.config.scrollGain,
            exponent=self.config.scrollExponent,
            maxUnits=self.config.maxScrollUnits,
        )
        self._wheelAccumY += sample.wheelY
        self._wheelAccumX += sample.wheelX

        stepY = int(self._wheelAccumY)
        stepX = int(self._wheelAccumX)
        if stepY == 0 and stepX == 0:
            return
        self._wheelAccumY -= stepY
        self._wheelAccumX -= stepX

        # Only classic wheel axes — sending hi-res alongside doubles scroll on many stacks.
        if stepY:
            injectRelative(ui, ecodes.REL_WHEEL, stepY)
        if stepX:
            injectRelative(ui, ecodes.REL_HWHEEL, stepX)
        syn(ui)

    def _handleEvent(self, ui: UInput, event: InputEvent, passthroughMiddle: bool) -> None:
        etype, code, value = event.type, event.code, event.value

        # Track relative motion for click-vs-drag + autoscroll vector.
        if etype == ecodes.EV_REL and code == ecodes.REL_X:
            self._cursorX += value
        elif etype == ecodes.EV_REL and code == ecodes.REL_Y:
            self._cursorY += value

        # --- AUTOSCROLL: motion scrolls; any button click ends it ---
        if self.mode == Mode.AUTOSCROLL:
            if etype == ecodes.EV_KEY and value == 1:
                # Consume the terminating click (Windows does this).
                self._leaveAutoscroll()
                return
            if etype == ecodes.EV_REL and code in (ecodes.REL_X, ecodes.REL_Y):
                forwardEvent(ui, event)
                syn(ui)
                return
            if etype == ecodes.EV_REL and code in (
                ecodes.REL_WHEEL,
                ecodes.REL_HWHEEL,
                ecodes.REL_WHEEL_HI_RES,
                ecodes.REL_HWHEEL_HI_RES,
            ):
                # Physical wheel while autoscrolling: end mode, pass wheel through.
                self._leaveAutoscroll()
                forwardEvent(ui, event)
                syn(ui)
                return
            if etype == ecodes.EV_SYN:
                return
            return

        # --- PENDING_MIDDLE: deciding between Windows click-autoscroll vs drag ---
        if self.mode == Mode.PENDING_MIDDLE:
            if etype == ecodes.EV_REL and code in (ecodes.REL_X, ecodes.REL_Y):
                if code == ecodes.REL_X:
                    self._pendingDx += value
                else:
                    self._pendingDy += value
                forwardEvent(ui, event)
                syn(ui)
                if shouldStartDrag(self._pendingDx, self._pendingDy, self.config.dragThresholdPx):
                    injectButton(ui, ecodes.BTN_MIDDLE, 1)
                    syn(ui)
                    self.mode = Mode.MIDDLE_DRAG
                    log.debug("middle-drag passthrough")
                return

            if etype == ecodes.EV_KEY and code == ecodes.BTN_MIDDLE and value == 0:
                # Released without dragging → Windows autoscroll (no middle click delivered).
                self._enterAutoscroll()
                return

            if etype == ecodes.EV_KEY and value != 0:
                injectButton(ui, ecodes.BTN_MIDDLE, 1)
                syn(ui)
                self.mode = Mode.MIDDLE_DRAG
                forwardEvent(ui, event)
                syn(ui)
                return

            if etype == ecodes.EV_SYN:
                return

            forwardEvent(ui, event)
            syn(ui)
            return

        # --- MIDDLE_DRAG: full passthrough until middle release ---
        if self.mode == Mode.MIDDLE_DRAG:
            if etype != ecodes.EV_SYN:
                forwardEvent(ui, event)
                syn(ui)
            if etype == ecodes.EV_KEY and code == ecodes.BTN_MIDDLE and value == 0:
                self.mode = Mode.IDLE
            return

        # --- IDLE ---
        if etype == ecodes.EV_KEY and code == ecodes.BTN_MIDDLE and value == 1:
            if passthroughMiddle:
                forwardEvent(ui, event)
                syn(ui)
                return
            self.mode = Mode.PENDING_MIDDLE
            self._pendingDx = 0.0
            self._pendingDy = 0.0
            return

        if etype != ecodes.EV_SYN:
            forwardEvent(ui, event)
            syn(ui)

    def run(self) -> None:
        pointer = pickPointerDevice(
            preferredPath=self.config.devicePath,
            vendor=self.config.deviceVendor,
            product=self.config.deviceProduct,
        )
        self.pointer = pointer
        log.info("Using pointer %s (%s) vid=%04x pid=%04x", pointer.path, pointer.name, pointer.vendor, pointer.product)

        ui = createVirtualMouse()
        self.ui = ui
        log.info("Virtual mouse ready")

        if self.config.grabDevice:
            grabDevice(pointer.device)
            log.info("Grabbed physical device (compositor only sees winmiddle virtual mouse)")

        try:
            for batch in iterDeviceEvents(pointer.device, timeoutSec=1.0 / max(1.0, self.config.scrollHz)):
                if self._stop.is_set():
                    break

                passthroughMiddle = self._shouldPassthroughMiddle()

                # If focus switches into a passthrough app mid-pending, flush middle-down.
                if passthroughMiddle and self.mode == Mode.PENDING_MIDDLE:
                    injectButton(ui, ecodes.BTN_MIDDLE, 1)
                    syn(ui)
                    self.mode = Mode.MIDDLE_DRAG

                if self.mode == Mode.AUTOSCROLL:
                    self._flushScroll(ui)

                for event in batch:
                    self._handleEvent(ui, event, passthroughMiddle)
        finally:
            self._leaveAutoscroll()
            try:
                pointer.device.ungrab()
            except Exception:
                pass
            ui.close()
            log.info("Daemon stopped")
