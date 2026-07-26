"""System tray icon for quick access to winmiddle settings / service."""

from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from winmiddle.service import (
    disableService,
    enableService,
    queryServiceStatus,
    restartService,
)
from winmiddle.ui.icons import winmiddleIcon


class TrayController(QSystemTrayIcon):
    def __init__(self, settingsWindow: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(winmiddleIcon(), parent)
        self.settingsWindow = settingsWindow
        self.setToolTip("winmiddle")

        self.menu = QMenu()
        self.openAction = QAction("Open settings", self.menu)
        self.restartAction = QAction("Restart daemon", self.menu)
        self.enableAction = QAction("Enable at login", self.menu)
        self.quitAction = QAction("Quit", self.menu)

        self.openAction.triggered.connect(self.showSettings)
        self.restartAction.triggered.connect(self._restart)
        self.enableAction.triggered.connect(self._toggleEnabled)
        self.quitAction.triggered.connect(self._quit)

        self.menu.addAction(self.openAction)
        self.menu.addSeparator()
        self.menu.addAction(self.restartAction)
        self.menu.addAction(self.enableAction)
        self.menu.addSeparator()
        self.menu.addAction(self.quitAction)
        self.setContextMenu(self.menu)

        self.activated.connect(self._onActivated)
        self.refreshMenu()

    def showSettings(self) -> None:
        self.settingsWindow.show()
        self.settingsWindow.raise_()
        self.settingsWindow.activateWindow()

    def refreshMenu(self) -> None:
        status = queryServiceStatus()
        if status.active:
            self.setToolTip(f"winmiddle — running ({status.detail})")
        else:
            self.setToolTip(f"winmiddle — {status.detail}")
        self.enableAction.setText("Disable at login" if status.enabled else "Enable at login")

    def _onActivated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.settingsWindow.isVisible():
                self.settingsWindow.hide()
            else:
                self.showSettings()

    def _restart(self) -> None:
        restartService()
        self.refreshMenu()
        if hasattr(self.settingsWindow, "refreshServiceStatus"):
            self.settingsWindow.refreshServiceStatus()

    def _toggleEnabled(self) -> None:
        status = queryServiceStatus()
        if status.enabled:
            disableService(now=False)
        else:
            enableService(now=True)
        self.refreshMenu()
        if hasattr(self.settingsWindow, "refreshServiceStatus"):
            self.settingsWindow.refreshServiceStatus()

    def _quit(self) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.instance().quit()
