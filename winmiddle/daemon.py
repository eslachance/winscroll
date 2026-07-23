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
    from winmiddle.cursor import CursorController

log = logging.getLogger("winmiddle.daemon")


class MiddleDaemon:
    def __init__(
        self,
        config: Config,
        focusHub: FocusHub,
        overlay: CursorController | None,
    ) -> None:
        self.config = config
        self.focusHub = focusHub
        self.overlay = overlay  # cursor controller (name kept for minimal churn)
        self.mode = Mode.IDLE
        self._stop = threading.Event()
        self._originX = 0.0
        self._originY = 0.0
        self._cursorX = 0.0
        self._cursorY = 0.0
        self._pendingDx = 0.0
        self._pendingDy = 0.0
        self._pendingStartTs = 0.0
        self._wheelAccumY = 0.0
        self._wheelAccumX = 0.0
        self._lastScrollTs = 0.0
        self._autoscrollOriginScreen = (0, 0)
        self._autoscrollEnterTs = 0.0
        # Compositor cursor estimate during autoscroll (screen space).
        self._pointerScreenX = 0.0
        self._pointerScreenY = 0.0
        # While the logical pointer is over a panel, keep the real cursor parked
        # on the autoscroll origin so wheel events still hit the client.
        self._scrollParked = False
        self.ui: UInput | None = None
        self.pointer = None

    def stop(self) -> None:
        self._stop.set()

    @staticmethod
    def _isWheelEvent(etype: int, code: int) -> bool:
        return etype == ecodes.EV_REL and code in (
            ecodes.REL_WHEEL,
            ecodes.REL_HWHEEL,
            ecodes.REL_WHEEL_HI_RES,
            ecodes.REL_HWHEEL_HI_RES,
        )

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
        self._pointerScreenX = float(focus.cursorX)
        self._pointerScreenY = float(focus.cursorY)
        # Keep tracking from current relative origin (zeros).
        self._originX = self._cursorX
        self._originY = self._cursorY
        self._wheelAccumX = 0.0
        self._wheelAccumY = 0.0
        self._lastScrollTs = time.monotonic()
        self._autoscrollEnterTs = time.monotonic()
        self._scrollParked = False
        self.mode = Mode.AUTOSCROLL
        log.info(
            "autoscroll ON at screen (%s,%s) focus=%s speed=%s",
            focus.cursorX,
            focus.cursorY,
            focus.resourceClass or "?",
            self.config.speed,
        )
        if self.overlay:
            self.overlay.requestShow(focus.cursorX, focus.cursorY)

    def _forwardAutoscrollMotion(self, ui: UInput, code: int, value: int) -> None:
        """Track logical pointer; park the real cursor on origin over panels.

        Wayland can only deliver wheel events to the surface under the cursor.
        Hop-and-return in one uinput batch gets coalesced back onto the panel,
        so while the logical position is outside the work area we keep the
        compositor cursor parked on the middle-click origin instead.
        """
        if code == ecodes.REL_X:
            self._pointerScreenX += value
        else:
            self._pointerScreenY += value

        if self._logicalPointerOutsideWorkArea():
            if not self._scrollParked:
                self._parkScrollCursor(ui)
            return

        if self._scrollParked:
            self._unparkScrollCursor(ui)
            return

        injectRelative(ui, code, value)
        syn(ui)

    def _logicalPointerOutsideWorkArea(self) -> bool:
        focus = self.focusHub.snapshot()
        if focus.underPanel:
            return True
        return not self._workAreaContains(self._pointerScreenX, self._pointerScreenY)

    def _workAreaContains(self, x: float, y: float, *, margin: int = 2) -> bool:
        focus = self.focusHub.snapshot()
        workArea = focus.workArea
        if workArea is None:
            return True
        x0, y0, width, height = workArea
        return (
            x0 + margin <= x <= x0 + width - 1 - margin
            and y0 + margin <= y <= y0 + height - 1 - margin
        )

    def _parkScrollCursor(self, ui: UInput) -> None:
        """Move compositor cursor to the autoscroll origin and keep it there."""
        focus = self.focusHub.snapshot()
        ox, oy = self._autoscrollOriginScreen
        hopX = int(round(ox - float(focus.cursorX)))
        hopY = int(round(oy - float(focus.cursorY)))
        if hopX:
            injectRelative(ui, ecodes.REL_X, hopX)
        if hopY:
            injectRelative(ui, ecodes.REL_Y, hopY)
        if hopX or hopY:
            syn(ui)
        self._scrollParked = True
        log.debug("panel scroll park at origin (%s,%s)", ox, oy)

    def _unparkScrollCursor(self, ui: UInput) -> None:
        """Restore compositor cursor to the logical (in-work-area) position."""
        focus = self.focusHub.snapshot()
        hopX = int(round(self._pointerScreenX - float(focus.cursorX)))
        hopY = int(round(self._pointerScreenY - float(focus.cursorY)))
        if hopX:
            injectRelative(ui, ecodes.REL_X, hopX)
        if hopY:
            injectRelative(ui, ecodes.REL_Y, hopY)
        if hopX or hopY:
            syn(ui)
        self._scrollParked = False
        log.debug(
            "panel scroll unpark to logical (%.0f,%.0f)",
            self._pointerScreenX,
            self._pointerScreenY,
        )

    def _autoscrollVector(self) -> tuple[float, float]:
        """Cursor−origin in screen space (logical pointer, including over panels)."""
        originX, originY = self._autoscrollOriginScreen
        return (
            self._pointerScreenX - float(originX),
            self._pointerScreenY - float(originY),
        )

    def _injectScrollSteps(self, ui: UInput, stepX: int, stepY: int) -> None:
        if stepY:
            injectRelative(ui, ecodes.REL_WHEEL_HI_RES, stepY)
            notches = int(abs(stepY) / 120)
            if notches:
                injectRelative(ui, ecodes.REL_WHEEL, notches if stepY > 0 else -notches)
        if stepX:
            injectRelative(ui, ecodes.REL_HWHEEL_HI_RES, stepX)
            notches = int(abs(stepX) / 120)
            if notches:
                injectRelative(ui, ecodes.REL_HWHEEL, notches if stepX > 0 else -notches)
        syn(ui)

    def _leaveAutoscroll(self) -> None:
        if self.mode == Mode.AUTOSCROLL:
            log.info("autoscroll OFF")
        self.mode = Mode.IDLE
        self._wheelAccumX = 0.0
        self._wheelAccumY = 0.0
        self._scrollParked = False
        if self.overlay:
            self.overlay.requestHide()

    def _flushScroll(self, ui: UInput) -> None:
        now = time.monotonic()
        interval = 1.0 / max(1.0, self.config.scrollHz)
        if now - self._lastScrollTs < interval:
            return
        self._lastScrollTs = now

        # Keep park state honest even if the pointer stopped moving.
        if self._logicalPointerOutsideWorkArea():
            if not self._scrollParked:
                self._parkScrollCursor(ui)
        elif self._scrollParked:
            self._unparkScrollCursor(ui)

        dx, dy = self._autoscrollVector()
        sample = windowsScrollSpeed(
            dx,
            dy,
            deadzonePx=self.config.deadzonePx,
            refDistancePx=self.config.refDistancePx,
            refNotchesPerSec=self.config.refNotchesPerSec,
            maxNotchesPerSec=self.config.maxNotchesPerSec,
            power=self.config.scrollPower,
        )
        # Convert notches/sec → hi-res units this frame (120 = one notch).
        # Modern libinput ignores REL_WHEEL when REL_WHEEL_HI_RES is advertised.
        frameSec = 1.0 / max(1.0, self.config.scrollHz)
        self._wheelAccumY += sample.notchesPerSecY * 120.0 * frameSec
        self._wheelAccumX += sample.notchesPerSecX * 120.0 * frameSec

        stepY = int(self._wheelAccumY)
        stepX = int(self._wheelAccumX)
        if stepY == 0 and stepX == 0:
            if self.overlay:
                self.overlay.requestDirection(dx, dy, self.config.deadzonePx)
            return
        self._wheelAccumY -= stepY
        self._wheelAccumX -= stepX

        self._injectScrollSteps(ui, stepX, stepY)
        if self.overlay:
            self.overlay.requestDirection(dx, dy, self.config.deadzonePx)

        log.debug(
            "scroll nps=(%.2f,%.2f) hi-res dy=%d dx=%d vec=(%.1f,%.1f)",
            sample.notchesPerSecY,
            sample.notchesPerSecX,
            stepY,
            stepX,
            dx,
            dy,
        )

    def _handleEvent(self, ui: UInput, event: InputEvent, passthroughMiddle: bool) -> None:
        etype, code, value = event.type, event.code, event.value

        # Track relative motion for click-vs-drag + autoscroll vector.
        if etype == ecodes.EV_REL and code == ecodes.REL_X:
            self._cursorX += value
        elif etype == ecodes.EV_REL and code == ecodes.REL_Y:
            self._cursorY += value

        # --- AUTOSCROLL: motion scrolls; button click ends it ---
        if self.mode == Mode.AUTOSCROLL:
            if etype == ecodes.EV_KEY and value == 1:
                # Consume the terminating click (Windows does this).
                self._leaveAutoscroll()
                return
            if etype == ecodes.EV_REL and code in (ecodes.REL_X, ecodes.REL_Y):
                self._forwardAutoscrollMotion(ui, code, value)
                return
            if self._isWheelEvent(etype, code):
                ageMs = (time.monotonic() - self._autoscrollEnterTs) * 1000.0
                # Swallow click-jitter from bad scroll wheels right after engage.
                if ageMs < self.config.wheelGraceMs:
                    log.debug("ignoring wheel during grace (%.0fms)", ageMs)
                    return
                if not self.config.exitOnWheel:
                    # Keep autoscroll; drop physical wheel so it doesn't fight us.
                    log.debug("ignoring wheel (exit_on_wheel=false)")
                    return
                self._leaveAutoscroll()
                forwardEvent(ui, event)
                syn(ui)
                return
            if etype == ecodes.EV_SYN:
                return
            return

        # --- PENDING_MIDDLE: deciding between Windows click-autoscroll vs drag ---
        if self.mode == Mode.PENDING_MIDDLE:
            heldMs = (time.monotonic() - self._pendingStartTs) * 1000.0
            # Middle-click on cheap/noisy wheels almost always emits accidental ticks.
            # Swallow them so Dolphin doesn't scroll-and-steal focus mid-click.
            if self._isWheelEvent(etype, code):
                return
            if etype == ecodes.EV_REL and code in (ecodes.REL_X, ecodes.REL_Y):
                if code == ecodes.REL_X:
                    self._pendingDx += value
                else:
                    self._pendingDy += value
                forwardEvent(ui, event)
                syn(ui)
                # Only promote to middle-drag if held long enough AND moved enough.
                # Short clicks with hand tremor must still become Windows autoscroll.
                if (
                    heldMs >= self.config.clickMaxMs
                    and shouldStartDrag(self._pendingDx, self._pendingDy, self.config.dragThresholdPx)
                ):
                    injectButton(ui, ecodes.BTN_MIDDLE, 1)
                    syn(ui)
                    self.mode = Mode.MIDDLE_DRAG
                    log.info(
                        "middle-drag passthrough (held=%.0fms move=%.0f)",
                        heldMs,
                        (self._pendingDx**2 + self._pendingDy**2) ** 0.5,
                    )
                return

            if etype == ecodes.EV_KEY and code == ecodes.BTN_MIDDLE and value == 0:
                # Released without becoming a drag → Windows autoscroll.
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
            self._pendingStartTs = time.monotonic()
            log.debug("middle pending")
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
        log.info(
            "scroll curve speed=%s deadzone=%.1f ref=%.0fpx@%.1fnps max=%.1fnps power=%.2f",
            self.config.speed,
            self.config.deadzonePx,
            self.config.refDistancePx,
            self.config.refNotchesPerSec,
            self.config.maxNotchesPerSec,
            self.config.scrollPower,
        )

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
