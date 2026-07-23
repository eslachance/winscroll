"""Core input loop: hold/toggle autoscroll with optional modifier gate."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from evdev import InputEvent, ecodes

from winmiddle.activation import gestureAllowed
from winmiddle.autoscroll import Mode, shouldStartDrag, windowsScrollSpeed
from winmiddle.devices import (
    createVirtualMouse,
    forwardEvent,
    grabDevice,
    injectButton,
    injectRelative,
    iterDeviceEventsWithExtras,
    pickPointerDevice,
    syn,
)
from winmiddle.focus import FocusHub, matchesAny
from winmiddle.modifiers import ModifierTracker

if TYPE_CHECKING:
    from evdev import UInput

    from winmiddle.config import Config
    from winmiddle.cursor import CursorController
    from winmiddle.scrollprobe import ScrollProbe

log = logging.getLogger("winmiddle.daemon")


class MiddleDaemon:
    def __init__(
        self,
        config: Config,
        focusHub: FocusHub,
        overlay: CursorController | None,
        scrollProbe: ScrollProbe | None = None,
    ) -> None:
        self.config = config
        self.focusHub = focusHub
        self.overlay = overlay  # cursor controller (name kept for minimal churn)
        self.scrollProbe = scrollProbe
        self.mode = Mode.IDLE
        self._stop = threading.Event()
        self._originX = 0.0
        self._originY = 0.0
        self._cursorX = 0.0
        self._cursorY = 0.0
        self._pendingDx = 0.0
        self._pendingDy = 0.0
        self._pendingStartTs = 0.0
        self._pendingHoldOk = False
        self._pendingToggleOk = False
        self._wheelAccumY = 0.0
        self._wheelAccumX = 0.0
        self._lastScrollTs = 0.0
        self._autoscrollOriginScreen = (0, 0)
        self._autoscrollEnterTs = 0.0
        # Compositor cursor estimate during autoscroll (clamped to work area).
        self._pointerScreenX = 0.0
        self._pointerScreenY = 0.0
        self.ui: UInput | None = None
        self.pointer = None
        self.modifiers: ModifierTracker | None = None

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

    def _modifierHeld(self) -> bool:
        if self.modifiers is None:
            # No keyboard nodes readable → treat "none" as ok, others as not held.
            return (self.config.activationModifier or "none") == "none"
        return self.modifiers.isModifierHeld(self.config.activationModifier)

    def _snapshotGestureFlags(self) -> tuple[bool, bool]:
        held = self._modifierHeld()
        holdOk = gestureAllowed(
            enabled=self.config.holdScroll,
            activationModifier=self.config.activationModifier,
            modifierFor=self.config.modifierFor,
            gesture="hold",
            modifierHeld=held,
        )
        toggleOk = gestureAllowed(
            enabled=self.config.toggleScroll,
            activationModifier=self.config.activationModifier,
            modifierFor=self.config.modifierFor,
            gesture="toggle",
            modifierHeld=held,
        )
        return holdOk, toggleOk

    def _scrollTargetAllowsAutoscroll(self) -> bool:
        """True only when we should enter PENDING_MIDDLE / autoscroll."""
        if not self.config.requireScrollable:
            return True
        if self.scrollProbe is None:
            return False
        focus = self.focusHub.snapshot()
        verdict = self.scrollProbe.probe(focus.cursorX, focus.cursorY)
        log.info(
            "scroll probe at (%s,%s) focus=%s → %s",
            focus.cursorX,
            focus.cursorY,
            focus.resourceClass or "?",
            verdict,
        )
        return verdict == "yes"

    def _enterAutoscroll(self, mode: Mode) -> None:
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
        self.mode = mode
        label = "hold" if mode == Mode.HOLD_AUTOSCROLL else "toggle"
        log.info(
            "autoscroll ON (%s) at screen (%s,%s) focus=%s speed=%s",
            label,
            focus.cursorX,
            focus.cursorY,
            focus.resourceClass or "?",
            self.config.speed,
        )
        if self.overlay:
            self.overlay.requestShow(focus.cursorX, focus.cursorY)

    def _forwardAutoscrollMotion(self, ui: UInput, code: int, value: int) -> None:
        """Forward pointer motion, clamped to availableGeometry (excludes panels).

        Scroll vector is derived from this clamped on-screen position (not raw
        physical deltas), so pushing into the panel cannot accumulate drift.
        """
        focus = self.focusHub.snapshot()
        workArea = focus.workArea

        if code == ecodes.REL_X:
            newPos = self._pointerScreenX + value
            if workArea is not None:
                x0, _, width, _ = workArea
                x1 = x0 + max(1, width) - 1
                newPos = min(max(newPos, float(x0)), float(x1))
            deliver = int(round(newPos - self._pointerScreenX))
            self._pointerScreenX = newPos
        else:
            newPos = self._pointerScreenY + value
            if workArea is not None:
                _, y0, _, height = workArea
                y1 = y0 + max(1, height) - 1
                newPos = min(max(newPos, float(y0)), float(y1))
            deliver = int(round(newPos - self._pointerScreenY))
            self._pointerScreenY = newPos

        if deliver:
            injectRelative(ui, code, deliver)
            syn(ui)

    def _autoscrollVector(self) -> tuple[float, float]:
        """Cursor−origin in screen space using the clamped compositor position."""
        originX, originY = self._autoscrollOriginScreen
        return (
            self._pointerScreenX - float(originX),
            self._pointerScreenY - float(originY),
        )

    def _leaveAutoscroll(self) -> None:
        if self.mode in (Mode.AUTOSCROLL, Mode.HOLD_AUTOSCROLL):
            log.info("autoscroll OFF")
        self.mode = Mode.IDLE
        self._wheelAccumX = 0.0
        self._wheelAccumY = 0.0
        if self.overlay:
            self.overlay.requestHide()

    def _injectNativeMiddleClick(self, ui: UInput) -> None:
        injectButton(ui, ecodes.BTN_MIDDLE, 1)
        syn(ui)
        injectButton(ui, ecodes.BTN_MIDDLE, 0)
        syn(ui)

    def _beginMiddleDrag(self, ui: UInput) -> None:
        injectButton(ui, ecodes.BTN_MIDDLE, 1)
        syn(ui)
        self.mode = Mode.MIDDLE_DRAG

    def _flushScroll(self, ui: UInput) -> None:
        now = time.monotonic()
        interval = 1.0 / max(1.0, self.config.scrollHz)
        if now - self._lastScrollTs < interval:
            return
        self._lastScrollTs = now

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

    def _handleToggleAutoscrollEvent(self, ui: UInput, event: InputEvent) -> None:
        etype, code, value = event.type, event.code, event.value
        if etype == ecodes.EV_KEY and value == 1:
            # Consume the terminating click (Windows does this).
            self._leaveAutoscroll()
            return
        if etype == ecodes.EV_REL and code in (ecodes.REL_X, ecodes.REL_Y):
            self._forwardAutoscrollMotion(ui, code, value)
            return
        if self._isWheelEvent(etype, code):
            ageMs = (time.monotonic() - self._autoscrollEnterTs) * 1000.0
            if ageMs < self.config.wheelGraceMs:
                log.debug("ignoring wheel during grace (%.0fms)", ageMs)
                return
            if not self.config.exitOnWheel:
                log.debug("ignoring wheel (exit_on_wheel=false)")
                return
            self._leaveAutoscroll()
            forwardEvent(ui, event)
            syn(ui)
            return
        if etype == ecodes.EV_SYN:
            return

    def _handleHoldAutoscrollEvent(self, ui: UInput, event: InputEvent) -> None:
        etype, code, value = event.type, event.code, event.value
        if etype == ecodes.EV_KEY and code == ecodes.BTN_MIDDLE and value == 0:
            self._leaveAutoscroll()
            return
        if etype == ecodes.EV_KEY and value == 1 and code != ecodes.BTN_MIDDLE:
            # Another button while holding: end hold-scroll, then deliver the click.
            self._leaveAutoscroll()
            forwardEvent(ui, event)
            syn(ui)
            return
        if etype == ecodes.EV_REL and code in (ecodes.REL_X, ecodes.REL_Y):
            self._forwardAutoscrollMotion(ui, code, value)
            return
        if self._isWheelEvent(etype, code):
            # Physical wheel while holding: ignore (hold gesture owns scrolling).
            return
        if etype == ecodes.EV_SYN:
            return

    def _handlePendingEvent(self, ui: UInput, event: InputEvent) -> None:
        etype, code, value = event.type, event.code, event.value
        # Middle-click on cheap/noisy wheels almost always emits accidental ticks.
        if self._isWheelEvent(etype, code):
            return

        if etype == ecodes.EV_REL and code in (ecodes.REL_X, ecodes.REL_Y):
            if code == ecodes.REL_X:
                self._pendingDx += value
            else:
                self._pendingDy += value
            forwardEvent(ui, event)
            syn(ui)
            if shouldStartDrag(
                self._pendingDx, self._pendingDy, self.config.dragThresholdPx
            ):
                if self._pendingHoldOk:
                    self._enterAutoscroll(Mode.HOLD_AUTOSCROLL)
                else:
                    # Toggle-only: require a sustained hold so hand tremor on a
                    # short click still becomes Windows toggle-autoscroll.
                    heldMs = (time.monotonic() - self._pendingStartTs) * 1000.0
                    if heldMs >= self.config.clickMaxMs:
                        self._beginMiddleDrag(ui)
                        log.info(
                            "middle-drag passthrough (held=%.0fms move=%.0f)",
                            heldMs,
                            (self._pendingDx**2 + self._pendingDy**2) ** 0.5,
                        )
            return

        if etype == ecodes.EV_KEY and code == ecodes.BTN_MIDDLE and value == 0:
            if self._pendingToggleOk:
                self._enterAutoscroll(Mode.AUTOSCROLL)
            else:
                # Tap without toggle → native middle-click (close tab, paste, …).
                self._injectNativeMiddleClick(ui)
                self.mode = Mode.IDLE
                log.debug("middle tap → native click")
            return

        if etype == ecodes.EV_KEY and value != 0:
            self._beginMiddleDrag(ui)
            forwardEvent(ui, event)
            syn(ui)
            return

        if etype == ecodes.EV_SYN:
            return

        forwardEvent(ui, event)
        syn(ui)

    def _handleEvent(self, ui: UInput, event: InputEvent, passthroughMiddle: bool) -> None:
        etype, code, value = event.type, event.code, event.value

        # Track relative motion for click-vs-drag + autoscroll vector.
        if etype == ecodes.EV_REL and code == ecodes.REL_X:
            self._cursorX += value
        elif etype == ecodes.EV_REL and code == ecodes.REL_Y:
            self._cursorY += value

        if self.mode == Mode.AUTOSCROLL:
            self._handleToggleAutoscrollEvent(ui, event)
            return

        if self.mode == Mode.HOLD_AUTOSCROLL:
            self._handleHoldAutoscrollEvent(ui, event)
            return

        if self.mode == Mode.PENDING_MIDDLE:
            self._handlePendingEvent(ui, event)
            return

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

            holdOk, toggleOk = self._snapshotGestureFlags()
            if not holdOk and not toggleOk:
                # Modifier gate (or both modes off) → raw middle gesture.
                injectButton(ui, ecodes.BTN_MIDDLE, 1)
                syn(ui)
                self.mode = Mode.MIDDLE_DRAG
                return

            if not self._scrollTargetAllowsAutoscroll():
                # Not a scrollable target (tab, button, game/no-a11y, …).
                injectButton(ui, ecodes.BTN_MIDDLE, 1)
                syn(ui)
                self.mode = Mode.MIDDLE_DRAG
                return

            self.mode = Mode.PENDING_MIDDLE
            self._pendingDx = 0.0
            self._pendingDy = 0.0
            self._pendingStartTs = time.monotonic()
            self._pendingHoldOk = holdOk
            self._pendingToggleOk = toggleOk
            log.debug(
                "middle pending (hold=%s toggle=%s mod=%s)",
                holdOk,
                toggleOk,
                self.config.activationModifier,
            )
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
        log.info(
            "Using pointer %s (%s) vid=%04x pid=%04x",
            pointer.path,
            pointer.name,
            pointer.vendor,
            pointer.product,
        )
        log.info(
            "activation hold=%s toggle=%s modifier=%s modifier_for=%s",
            self.config.holdScroll,
            self.config.toggleScroll,
            self.config.activationModifier,
            self.config.modifierFor,
        )
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

        try:
            self.modifiers = ModifierTracker.open()
        except Exception as error:
            log.warning("modifier tracker unavailable: %s", error)
            self.modifiers = None

        if self.config.grabDevice:
            grabDevice(pointer.device)
            log.info("Grabbed physical device (compositor only sees winmiddle virtual mouse)")

        extraFds = self.modifiers.fds if self.modifiers else []
        try:
            for batch, readyExtras in iterDeviceEventsWithExtras(
                pointer.device,
                extraFds,
                timeoutSec=1.0 / max(1.0, self.config.scrollHz),
            ):
                if self._stop.is_set():
                    break

                if self.modifiers and readyExtras:
                    for fd in readyExtras:
                        device = self.modifiers.deviceForFd(fd)
                        if device is not None:
                            self.modifiers.drain(device)

                passthroughMiddle = self._shouldPassthroughMiddle()

                # If focus switches into a passthrough app mid-pending, flush middle-down.
                if passthroughMiddle and self.mode == Mode.PENDING_MIDDLE:
                    self._beginMiddleDrag(ui)

                if self.mode in (Mode.AUTOSCROLL, Mode.HOLD_AUTOSCROLL):
                    self._flushScroll(ui)

                for event in batch:
                    self._handleEvent(ui, event, passthroughMiddle)
        finally:
            self._leaveAutoscroll()
            if self.modifiers:
                self.modifiers.close()
                self.modifiers = None
            try:
                pointer.device.ungrab()
            except Exception:
                pass
            ui.close()
            log.info("Daemon stopped")
