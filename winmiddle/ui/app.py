"""Entry point for the winmiddle settings UI."""

from __future__ import annotations

import argparse
import logging
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from winmiddle.ui.icons import winmiddleIcon
from winmiddle.ui.tray import TrayController
from winmiddle.ui.window import SettingsWindow


def buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="winmiddle-ui",
        description="Settings UI for winmiddle (Windows-style middle-click autoscroll)",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Do not keep a system tray icon; quit when the window closes",
    )
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

    app = QApplication(sys.argv)
    app.setApplicationName("winmiddle")
    app.setApplicationDisplayName("winmiddle")
    app.setDesktopFileName("winmiddle")
    app.setWindowIcon(winmiddleIcon())
    app.setQuitOnLastWindowClosed(False)

    useTray = (not args.no_tray) and QSystemTrayIcon.isSystemTrayAvailable()
    window = SettingsWindow(closeToTray=useTray)

    tray: TrayController | None = None
    if useTray:
        tray = TrayController(window)
        tray.show()
        window.statusChanged.connect(tray.refreshMenu)
        trayHintShown = {"done": False}

        def onClosedToTray() -> None:
            if trayHintShown["done"]:
                return
            trayHintShown["done"] = True
            tray.showMessage(
                "winmiddle",
                "Still running in the system tray. Click the icon to reopen.",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )

        window.closedToTray.connect(onClosedToTray)
    else:
        app.setQuitOnLastWindowClosed(True)
        if not args.no_tray:
            QMessageBox.information(
                window,
                "No system tray",
                "No system tray is available, so the settings window will quit on close.",
            )

    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
