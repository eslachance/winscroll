"""Qt-main-thread bridge for AT-SPI scroll-target probes (safe + timed)."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QTimer, pyqtSlot

from winmiddle.scrolltarget import ScrollVerdict, probeScrollTarget

if TYPE_CHECKING:
    pass

log = logging.getLogger("winmiddle.scrollprobe")

DEFAULT_TIMEOUT_SEC = 0.015


class ScrollProbe(QObject):
    """Daemon thread asks; Qt thread runs AT-SPI; result via Event."""

    def __init__(self, timeoutSec: float = DEFAULT_TIMEOUT_SEC) -> None:
        super().__init__()
        self._timeoutSec = timeoutSec
        self._lock = threading.Lock()
        self._request: tuple[int, int, int] | None = None
        self._result: ScrollVerdict = "unknown"
        self._resultGen = 0
        self._generation = 0
        self._done = threading.Event()
        self._timer = QTimer(self)
        self._timer.setInterval(5)
        self._timer.timeout.connect(self._pump)
        self._timer.start()
        # Warm AT-SPI on the GUI thread shortly after startup.
        QTimer.singleShot(0, self._warm)

    @pyqtSlot()
    def _warm(self) -> None:
        try:
            from winmiddle.scrolltarget import _ensureAtspi

            _ensureAtspi()
        except Exception:
            log.debug("AT-SPI warm failed", exc_info=True)

    def probe(self, x: int, y: int) -> ScrollVerdict:
        """Block the caller (input thread) until Qt finishes or timeout."""
        self._done.clear()
        with self._lock:
            self._generation += 1
            gen = self._generation
            self._request = (int(x), int(y), gen)
            self._result = "unknown"
        if not self._done.wait(timeout=self._timeoutSec):
            log.debug("scroll probe timeout at (%s,%s)", x, y)
            with self._lock:
                if self._request is not None and self._request[2] == gen:
                    self._request = None
            return "unknown"
        with self._lock:
            if self._resultGen != gen:
                return "unknown"
            return self._result

    @pyqtSlot()
    def _pump(self) -> None:
        with self._lock:
            req = self._request
            if req is None:
                return
            self._request = None
            x, y, gen = req
        try:
            verdict = probeScrollTarget(x, y)
        except Exception:
            log.debug("scroll probe error", exc_info=True)
            verdict = "unknown"
        with self._lock:
            self._result = verdict
            self._resultGen = gen
        self._done.set()
        log.debug("scroll probe (%s,%s) → %s", x, y, verdict)
