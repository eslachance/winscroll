"""CLI entry: python -m winmiddle"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from winmiddle.config import loadConfig
from winmiddle.cursor import CursorController
from winmiddle.daemon import MiddleDaemon
from winmiddle.devices import listPointerDevices
from winmiddle.focus import FocusHub, registerFocusHub
from winmiddle.scrollprobe import ScrollProbe
from winmiddle.setuputil import ensureConfig, runSetup


def buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="winmiddle",
        description="Windows-faithful middle-click autoscroll for Linux (Wayland/X11)",
    )
    parser.add_argument("-c", "--config", type=Path, help="Config TOML path")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("--list-devices", action="store_true", help="List middle-button pointers and exit")
    parser.add_argument("--write-config", action="store_true", help="Write default config to ~/.config/winmiddle/config.toml")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="First-time setup: config, paste-kill, KWin script, mouse udev, enable user service",
    )
    parser.add_argument("--skip-udev", action="store_true", help="With --setup, skip mouse udev rule")
    parser.add_argument("--skip-service", action="store_true", help="With --setup, skip enabling the user service")
    parser.add_argument("--no-overlay", action="store_true", help="Disable the drawn autoscroll indicator")
    parser.add_argument("--no-grab", action="store_true", help="Do not exclusive-grab the physical mouse (debug)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = buildParser().parse_args(argv)
    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list_devices:
        for device in listPointerDevices():
            print(
                f"{device.path}\tvid={device.vendor:04x}\tpid={device.product:04x}\t{device.name}"
            )
        return 0

    if args.write_config:
        target = Path.home() / ".config" / "winmiddle" / "config.toml"
        if target.exists():
            print(f"Already exists: {target}", file=sys.stderr)
            return 1
        ensureConfig(target)
        print(f"Wrote {target}")
        return 0

    if args.setup:
        return runSetup(skipUdev=args.skip_udev, skipService=args.skip_service)

    config = loadConfig(args.config)
    if args.no_overlay:
        config.showOverlay = False
    if args.no_grab:
        config.grabDevice = False

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("winmiddle")
    # Matches NoDisplay desktop entry so Plasma can skip taskbar chrome.
    app.setDesktopFileName("winmiddle-overlay")

    focusHub = FocusHub()
    registerFocusHub(focusHub)

    # Keep availableGeometry fresh for panel-edge pointer clamp during autoscroll.
    workAreaTimer = QTimer()
    workAreaTimer.setInterval(200)
    workAreaTimer.timeout.connect(focusHub.refreshWorkArea)
    workAreaTimer.start()
    focusHub.refreshWorkArea()

    # Drawn LayerShell indicator (not cursor override — that steals scroll on Wayland).
    overlayController = CursorController() if config.showOverlay else None

    scrollProbe = None
    if config.requireScrollable:
        scrollProbe = ScrollProbe(timeoutSec=max(0.005, config.scrollProbeTimeoutMs / 1000.0))

    daemon = MiddleDaemon(config, focusHub, overlayController, scrollProbe=scrollProbe)
    thread = threading.Thread(target=daemon.run, name="winmiddle-input", daemon=True)
    thread.start()

    def shutdown(*_args) -> None:
        daemon.stop()
        QTimer.singleShot(200, app.quit)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    def watch() -> None:
        if not thread.is_alive():
            app.quit()

    watcher = QTimer()
    watcher.setInterval(500)
    watcher.timeout.connect(watch)
    watcher.start()

    code = app.exec()
    daemon.stop()
    thread.join(timeout=2.0)
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
