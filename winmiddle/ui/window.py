"""Main settings window for winmiddle."""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
    QInputDialog,
    QSizePolicy,
)

from winmiddle.config import (
    SPEED_PRESETS,
    Config,
    applySpeedPreset,
    loadConfig,
    primaryConfigPath,
    saveConfig,
)
from winmiddle.devices import listPointerDevices
from winmiddle.service import (
    disableService,
    enableService,
    queryServiceStatus,
    restartService,
    startService,
    stopService,
)
from winmiddle.setuputil import (
    enableKwinScript,
    ensureConfig,
    installMouseUdevRule,
)
from winmiddle.paste import applyAllPasteAndBrowserFixes
from winmiddle.ui.icons import winmiddleIcon

log = logging.getLogger("winmiddle.ui")


class AppListEditor(QWidget):
    """Editable list of app class/name substrings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.listWidget = QListWidget()
        self.listWidget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listWidget.setMinimumHeight(120)
        layout.addWidget(self.listWidget)

        row = QHBoxLayout()
        addBtn = QPushButton("Add…")
        removeBtn = QPushButton("Remove")
        addBtn.clicked.connect(self._addItem)
        removeBtn.clicked.connect(self._removeSelected)
        row.addWidget(addBtn)
        row.addWidget(removeBtn)
        row.addStretch(1)
        layout.addLayout(row)

    def setValues(self, values: list[str]) -> None:
        self.listWidget.clear()
        for value in values:
            self.listWidget.addItem(QListWidgetItem(value))

    def values(self) -> list[str]:
        out: list[str] = []
        for index in range(self.listWidget.count()):
            text = self.listWidget.item(index).text().strip()
            if text:
                out.append(text)
        return out

    def _addItem(self) -> None:
        text, ok = QInputDialog.getText(self, "Add app match", "Window class / name substring:")
        if ok and text.strip():
            self.listWidget.addItem(QListWidgetItem(text.strip()))

    def _removeSelected(self) -> None:
        for item in self.listWidget.selectedItems():
            row = self.listWidget.row(item)
            self.listWidget.takeItem(row)


class SettingsWindow(QMainWindow):
    """Configure winmiddle and control the user systemd service."""

    closedToTray = pyqtSignal()
    statusChanged = pyqtSignal()

    def __init__(self, *, closeToTray: bool = True) -> None:
        super().__init__()
        self.closeToTray = closeToTray
        self.configPath = primaryConfigPath()
        self.setWindowTitle("winmiddle")
        self.setWindowIcon(winmiddleIcon())
        self.resize(560, 640)
        self.setMinimumSize(480, 520)

        root = QWidget()
        self.setCentralWidget(root)
        rootLayout = QVBoxLayout(root)
        rootLayout.setSpacing(12)

        rootLayout.addWidget(self._buildHeader())
        rootLayout.addWidget(self._buildTabs(), stretch=1)
        rootLayout.addWidget(self._buildFooter())

        self.statusTimer = QTimer(self)
        self.statusTimer.setInterval(2000)
        self.statusTimer.timeout.connect(self.refreshServiceStatus)
        self.statusTimer.start()

        self.reloadFromDisk()
        self.refreshServiceStatus()
        self._syncModifierEnabled()

    # ── UI builders ──────────────────────────────────────────────────

    def _buildHeader(self) -> QWidget:
        box = QGroupBox("Daemon")
        layout = QHBoxLayout(box)

        self.statusDot = QLabel("●")
        self.statusDot.setFixedWidth(18)
        font = QFont(self.statusDot.font())
        font.setPointSize(font.pointSize() + 4)
        self.statusDot.setFont(font)

        self.statusLabel = QLabel("Checking…")
        self.statusLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.startStopBtn = QPushButton("Start")
        self.restartBtn = QPushButton("Restart")
        self.enableBtn = QPushButton("Enable at login")

        self.startStopBtn.clicked.connect(self._toggleRunning)
        self.restartBtn.clicked.connect(self._restartDaemon)
        self.enableBtn.clicked.connect(self._toggleEnabled)

        layout.addWidget(self.statusDot)
        layout.addWidget(self.statusLabel, stretch=1)
        layout.addWidget(self.startStopBtn)
        layout.addWidget(self.restartBtn)
        layout.addWidget(self.enableBtn)
        return box

    def _buildTabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.addTab(self._buildActivationTab(), "Activation")
        tabs.addTab(self._buildScrollTab(), "Scroll")
        tabs.addTab(self._buildAppsTab(), "Apps")
        tabs.addTab(self._buildDeviceTab(), "Device")
        tabs.addTab(self._buildSetupTab(), "Setup")
        return tabs

    def _buildActivationTab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        intro = QLabel(
            "Choose how middle-click starts autoscroll. Hold is the recommended default "
            "(tap still acts as a normal middle-click)."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.holdCheck = QCheckBox("Hold middle + move to scroll")
        self.toggleCheck = QCheckBox("Click to toggle (Windows-style)")
        self.modifierGateCheck = QCheckBox("Require modifier key")
        self.overlayCheck = QCheckBox("Show origin indicator while scrolling")

        self.modifierCombo = QComboBox()
        self.modifierCombo.addItems(["ctrl", "alt", "shift", "super"])
        self.modifierForCombo = QComboBox()
        self.modifierForCombo.addItems(["both", "hold", "toggle"])

        self.modifierGateCheck.toggled.connect(self._syncModifierEnabled)

        layout.addWidget(self.holdCheck)
        layout.addWidget(self.toggleCheck)
        layout.addWidget(self.modifierGateCheck)

        self.modifierDetails = QWidget()
        modifierForm = QFormLayout(self.modifierDetails)
        modifierForm.setContentsMargins(28, 0, 0, 0)
        modifierForm.addRow("modifier key:", self.modifierCombo)
        modifierForm.addRow("applies to:", self.modifierForCombo)
        layout.addWidget(self.modifierDetails)

        layout.addWidget(self.overlayCheck)

        tip = QLabel(
            "Tip: Classic Windows = toggle only. Ctrl+middle hold = hold + Require modifier + ctrl + applies to hold."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: palette(mid);")
        layout.addWidget(tip)
        layout.addStretch(1)
        self._syncModifierEnabled()
        return page

    def _buildScrollTab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        form = QFormLayout()
        self.speedCombo = QComboBox()
        self.speedCombo.addItems(list(SPEED_PRESETS.keys()))
        self.speedCombo.currentTextChanged.connect(self._onSpeedPresetChanged)

        self.dragThresholdSpin = QSpinBox()
        self.dragThresholdSpin.setRange(1, 500)
        self.dragThresholdSpin.setSuffix(" px")

        self.clickMaxSpin = QSpinBox()
        self.clickMaxSpin.setRange(50, 2000)
        self.clickMaxSpin.setSuffix(" ms")

        self.hzSpin = QSpinBox()
        self.hzSpin.setRange(15, 240)
        self.hzSpin.setSuffix(" Hz")

        self.exitOnWheelCheck = QCheckBox("Exit toggle-autoscroll on physical wheel tick")
        self.wheelGraceSpin = QSpinBox()
        self.wheelGraceSpin.setRange(0, 2000)
        self.wheelGraceSpin.setSuffix(" ms")

        self.deadzoneSpin = QDoubleSpinBox()
        self.deadzoneSpin.setRange(0, 200)
        self.deadzoneSpin.setDecimals(1)
        self.deadzoneSpin.setSuffix(" px")

        self.refDistanceSpin = QDoubleSpinBox()
        self.refDistanceSpin.setRange(10, 500)
        self.refDistanceSpin.setDecimals(1)
        self.refDistanceSpin.setSuffix(" px")

        self.refNpsSpin = QDoubleSpinBox()
        self.refNpsSpin.setRange(0.5, 100)
        self.refNpsSpin.setDecimals(1)
        self.refNpsSpin.setSuffix(" n/s")

        self.maxNpsSpin = QDoubleSpinBox()
        self.maxNpsSpin.setRange(1, 200)
        self.maxNpsSpin.setDecimals(1)
        self.maxNpsSpin.setSuffix(" n/s")

        self.powerSpin = QDoubleSpinBox()
        self.powerSpin.setRange(0.5, 3.0)
        self.powerSpin.setSingleStep(0.05)
        self.powerSpin.setDecimals(2)

        form.addRow("Speed preset:", self.speedCombo)
        form.addRow("Hold drag threshold:", self.dragThresholdSpin)
        form.addRow("Toggle click max time:", self.clickMaxSpin)
        form.addRow("Injection rate:", self.hzSpin)
        form.addRow(self.exitOnWheelCheck)
        form.addRow("Wheel grace after enter:", self.wheelGraceSpin)
        form.addRow("Dead zone:", self.deadzoneSpin)
        form.addRow("Reference distance:", self.refDistanceSpin)
        form.addRow("Speed at reference:", self.refNpsSpin)
        form.addRow("Max speed:", self.maxNpsSpin)
        form.addRow("Curve power:", self.powerSpin)
        layout.addLayout(form)

        hint = QLabel(
            "Changing the speed preset resets the curve fields below it. "
            "Fine-tune those if you want something between slow / normal / fast."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _buildAppsTab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.requireScrollableCheck = QCheckBox(
            "Only start autoscroll when the widget under the cursor looks scrollable (AT-SPI)"
        )
        layout.addWidget(self.requireScrollableCheck)

        layout.addWidget(QLabel("Native middle-click apps (full passthrough — browsers, etc.)"))
        self.nativeList = AppListEditor()
        layout.addWidget(self.nativeList)

        layout.addWidget(QLabel("Passthrough apps (never intercept — games, Blender, …)"))
        self.passthroughList = AppListEditor()
        layout.addWidget(self.passthroughList)
        return page

    def _buildDeviceTab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        form = QFormLayout()
        self.deviceCombo = QComboBox()
        self.deviceCombo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.deviceCombo.setMinimumContentsLength(28)
        refreshBtn = QPushButton("Refresh")
        refreshBtn.clicked.connect(self.refreshDevices)

        deviceRow = QHBoxLayout()
        deviceRow.addWidget(self.deviceCombo, stretch=1)
        deviceRow.addWidget(refreshBtn)

        self.grabCheck = QCheckBox("Exclusive-grab physical mouse (recommended)")
        form.addRow("Mouse:", deviceRow)
        form.addRow(self.grabCheck)
        layout.addLayout(form)

        note = QLabel(
            "Auto picks the first accessible middle-button pointer. Devices marked "
            "no access need the mouse udev rule (Setup tab) or an input-group re-login. "
            "Pin a device if you have more than one mouse."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        layout.addWidget(note)
        layout.addStretch(1)

        self.refreshDevices()
        return page

    def _buildSetupTab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        intro = QLabel(
            "These one-time fixes used to live only in `winmiddle --setup`. "
            "Run them again after a Plasma upgrade or if paste/browser behavior drifts."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.configPathLabel = QLabel()
        self.configPathLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.configPathLabel)

        buttons = [
            ("Apply paste-kill + browser fixes", self._runPasteFixes),
            ("Enable KWin focus script", self._runEnableKwin),
            ("Install mouse udev rule (sudo)", self._runInstallUdev),
            ("Enable & start user service", self._runEnableService),
            ("Run full setup", self._runFullSetup),
        ]
        for label, handler in buttons:
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            layout.addWidget(btn)

        layout.addStretch(1)
        return page

    def _buildFooter(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        self.messageLabel = QLabel("")
        self.messageLabel.setStyleSheet("color: palette(mid);")
        self.messageLabel.setWordWrap(True)

        defaultsBtn = QPushButton("Defaults")
        reloadBtn = QPushButton("Reload")
        applyBtn = QPushButton("Apply")
        applyRestartBtn = QPushButton("Apply & Restart")
        applyRestartBtn.setDefault(True)

        defaultsBtn.clicked.connect(self.resetToDefaults)
        reloadBtn.clicked.connect(self.reloadFromDisk)
        applyBtn.clicked.connect(lambda: self.applyConfig(restart=False))
        applyRestartBtn.clicked.connect(lambda: self.applyConfig(restart=True))

        layout.addWidget(self.messageLabel, stretch=1)
        layout.addWidget(defaultsBtn)
        layout.addWidget(reloadBtn)
        layout.addWidget(applyBtn)
        layout.addWidget(applyRestartBtn)
        return row

    # ── Data ─────────────────────────────────────────────────────────

    def reloadFromDisk(self) -> None:
        ensureConfig(self.configPath)
        cfg = loadConfig(self.configPath)
        self._applyConfigToForm(cfg)
        self.configPathLabel.setText(f"Config file: {self.configPath}")
        self._setMessage(f"Loaded {self.configPath}")

    def resetToDefaults(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reset to defaults?",
            "Replace the form with built-in defaults? (Not written until you Apply.)",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._applyConfigToForm(Config())
        self._setMessage("Form reset to defaults — click Apply to save")

    def _applyConfigToForm(self, cfg: Config) -> None:
        self.holdCheck.setChecked(cfg.holdScroll)
        self.toggleCheck.setChecked(cfg.toggleScroll)
        gateOn = cfg.activationModifier != "none"
        self.modifierGateCheck.setChecked(gateOn)
        if gateOn:
            self.modifierCombo.setCurrentText(cfg.activationModifier)
        self.modifierForCombo.setCurrentText(cfg.modifierFor)
        self.overlayCheck.setChecked(cfg.showOverlay)

        self.speedCombo.blockSignals(True)
        self.speedCombo.setCurrentText(cfg.speed if cfg.speed in SPEED_PRESETS else "normal")
        self.speedCombo.blockSignals(False)

        self.dragThresholdSpin.setValue(int(cfg.dragThresholdPx))
        self.clickMaxSpin.setValue(int(cfg.clickMaxMs))
        self.hzSpin.setValue(int(cfg.scrollHz))
        self.exitOnWheelCheck.setChecked(cfg.exitOnWheel)
        self.wheelGraceSpin.setValue(int(cfg.wheelGraceMs))
        self.deadzoneSpin.setValue(cfg.deadzonePx)
        self.refDistanceSpin.setValue(cfg.refDistancePx)
        self.refNpsSpin.setValue(cfg.refNotchesPerSec)
        self.maxNpsSpin.setValue(cfg.maxNotchesPerSec)
        self.powerSpin.setValue(cfg.scrollPower)

        self.requireScrollableCheck.setChecked(cfg.requireScrollable)
        self.nativeList.setValues(cfg.nativeMiddleApps)
        self.passthroughList.setValues(cfg.passthroughApps)

        self.grabCheck.setChecked(cfg.grabDevice)
        self._selectDeviceInCombo(cfg)
        self._syncModifierEnabled()

    def collectConfig(self) -> Config:
        if not self.holdCheck.isChecked() and not self.toggleCheck.isChecked():
            raise ValueError("Enable at least one of hold or toggle activation")

        cfg = Config()
        cfg.holdScroll = self.holdCheck.isChecked()
        cfg.toggleScroll = self.toggleCheck.isChecked()
        if self.modifierGateCheck.isChecked():
            cfg.activationModifier = self.modifierCombo.currentText()
        else:
            cfg.activationModifier = "none"
        cfg.modifierFor = self.modifierForCombo.currentText()
        cfg.showOverlay = self.overlayCheck.isChecked()

        applySpeedPreset(cfg, self.speedCombo.currentText())
        # Keep any manual curve overrides from the form.
        cfg.dragThresholdPx = float(self.dragThresholdSpin.value())
        cfg.clickMaxMs = float(self.clickMaxSpin.value())
        cfg.scrollHz = float(self.hzSpin.value())
        cfg.exitOnWheel = self.exitOnWheelCheck.isChecked()
        cfg.wheelGraceMs = float(self.wheelGraceSpin.value())
        cfg.deadzonePx = float(self.deadzoneSpin.value())
        cfg.refDistancePx = float(self.refDistanceSpin.value())
        cfg.refNotchesPerSec = float(self.refNpsSpin.value())
        cfg.maxNotchesPerSec = float(self.maxNpsSpin.value())
        cfg.scrollPower = float(self.powerSpin.value())

        cfg.requireScrollable = self.requireScrollableCheck.isChecked()
        cfg.nativeMiddleApps = self.nativeList.values()
        cfg.passthroughApps = self.passthroughList.values()

        cfg.grabDevice = self.grabCheck.isChecked()
        data = self.deviceCombo.currentData()
        if data is None:
            cfg.devicePath = None
            cfg.deviceVendor = None
            cfg.deviceProduct = None
        else:
            path, vendor, product = data
            cfg.devicePath = path
            cfg.deviceVendor = int(vendor)
            cfg.deviceProduct = int(product)
        return cfg

    def applyConfig(self, *, restart: bool) -> bool:
        try:
            cfg = self.collectConfig()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))
            return False

        path = saveConfig(cfg, self.configPath)
        self._setMessage(f"Saved {path}")

        if restart:
            ok, detail = restartService()
            if ok:
                self._setMessage(f"Saved and restarted daemon")
            else:
                # Service may not be installed yet — still a successful save.
                self._setMessage(f"Saved {path} (restart: {detail or 'failed'})")
            self.refreshServiceStatus()
        self.statusChanged.emit()
        return True

    # ── Service / setup actions ──────────────────────────────────────

    def refreshServiceStatus(self) -> None:
        status = queryServiceStatus()
        if status.active:
            self.statusDot.setStyleSheet("color: #3bb273;")
            self.statusLabel.setText(f"Running ({status.detail})")
            self.startStopBtn.setText("Stop")
        elif status.activeState == "unavailable":
            self.statusDot.setStyleSheet("color: #888;")
            self.statusLabel.setText("systemd unavailable")
            self.startStopBtn.setText("Start")
        else:
            self.statusDot.setStyleSheet("color: #d9534f;")
            self.statusLabel.setText(f"Stopped ({status.detail})")
            self.startStopBtn.setText("Start")

        if status.enabled:
            self.enableBtn.setText("Disable at login")
        else:
            self.enableBtn.setText("Enable at login")
        self.statusChanged.emit()

    def _toggleRunning(self) -> None:
        status = queryServiceStatus()
        if status.active:
            ok, detail = stopService()
        else:
            ok, detail = startService()
        self._setMessage(detail or ("ok" if ok else "failed"))
        self.refreshServiceStatus()

    def _restartDaemon(self) -> None:
        ok, detail = restartService()
        self._setMessage(detail or ("restarted" if ok else "restart failed"))
        self.refreshServiceStatus()

    def _toggleEnabled(self) -> None:
        status = queryServiceStatus()
        if status.enabled:
            ok, detail = disableService(now=False)
        else:
            ok, detail = enableService(now=True)
        self._setMessage(detail or ("ok" if ok else "failed"))
        self.refreshServiceStatus()

    def _runPasteFixes(self) -> None:
        try:
            applyAllPasteAndBrowserFixes()
            self._setMessage("Paste-kill + browser fixes applied (log out once for KWin)")
            QMessageBox.information(
                self,
                "Paste-kill applied",
                "Primary-selection / browser middle-click fixes applied.\n"
                "Log out and back in once so KWin drops primary selection.",
            )
        except Exception as exc:  # noqa: BLE001 — surface to user
            QMessageBox.warning(self, "Paste-kill failed", str(exc))

    def _runEnableKwin(self) -> None:
        ok = enableKwinScript()
        self._setMessage("KWin script enabled" if ok else "Could not enable KWin script")
        if not ok:
            QMessageBox.warning(
                self,
                "KWin script",
                "Could not enable winmiddle-focus (is kwriteconfig6 / qdbus6 installed?).",
            )

    def _runInstallUdev(self) -> None:
        data = self.deviceCombo.currentData()
        vendor = product = None
        if data is not None:
            _path, vendor, product = data
        ok = installMouseUdevRule(vendor=vendor, product=product)
        self._setMessage("Mouse udev rule installed" if ok else "udev install failed / cancelled")
        if not ok:
            QMessageBox.warning(
                self,
                "udev rule",
                "Could not install the mouse uaccess rule. You may need to approve sudo.",
            )

    def _runEnableService(self) -> None:
        ok, detail = enableService(now=True)
        self._setMessage(detail or ("enabled" if ok else "enable failed"))
        self.refreshServiceStatus()

    def _runFullSetup(self) -> None:
        from winmiddle.setuputil import runSetup

        code = runSetup()
        self.reloadFromDisk()
        self.refreshServiceStatus()
        if code == 0:
            QMessageBox.information(
                self,
                "Setup complete",
                "winmiddle setup finished.\nLog out and back in once so KWin drops primary selection.",
            )
        else:
            QMessageBox.warning(self, "Setup", f"Setup exited with code {code}")

    def refreshDevices(self) -> None:
        current = self.deviceCombo.currentData()
        self.deviceCombo.blockSignals(True)
        self.deviceCombo.clear()
        self.deviceCombo.addItem("Auto (first middle-button pointer)", None)
        try:
            devices = listPointerDevices(requireAccess=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("listPointerDevices failed: %s", exc)
            devices = []
        for device in devices:
            access = "" if device.accessible else " [no access — run Setup udev]"
            label = (
                f"{device.name}  ({device.path}, {device.vendor:04x}:{device.product:04x})"
                f"{access}"
            )
            self.deviceCombo.addItem(label, (device.path, device.vendor, device.product))
        # Restore previous selection if possible.
        if current is not None:
            for index in range(self.deviceCombo.count()):
                if self.deviceCombo.itemData(index) == current:
                    self.deviceCombo.setCurrentIndex(index)
                    break
        self.deviceCombo.blockSignals(False)

    def _selectDeviceInCombo(self, cfg: Config) -> None:
        if not cfg.devicePath and cfg.deviceVendor is None and cfg.deviceProduct is None:
            self.deviceCombo.setCurrentIndex(0)
            return
        for index in range(self.deviceCombo.count()):
            data = self.deviceCombo.itemData(index)
            if data is None:
                continue
            path, vendor, product = data
            if cfg.devicePath and path == cfg.devicePath:
                self.deviceCombo.setCurrentIndex(index)
                return
            if (
                cfg.deviceVendor is not None
                and cfg.deviceProduct is not None
                and vendor == cfg.deviceVendor
                and product == cfg.deviceProduct
            ):
                self.deviceCombo.setCurrentIndex(index)
                return
        # Config points at a device that isn't plugged in — keep Auto selected
        # but leave a note; path will be cleared on next save unless user picks one.
        self.deviceCombo.setCurrentIndex(0)

    def _onSpeedPresetChanged(self, speed: str) -> None:
        preset = SPEED_PRESETS.get(speed)
        if not preset:
            return
        self.deadzoneSpin.setValue(preset["deadzone_px"])
        self.refDistanceSpin.setValue(preset["ref_distance_px"])
        self.refNpsSpin.setValue(preset["ref_nps"])
        self.maxNpsSpin.setValue(preset["max_nps"])
        self.powerSpin.setValue(preset["power"])

    def _syncModifierEnabled(self) -> None:
        enabled = self.modifierGateCheck.isChecked()
        self.modifierDetails.setVisible(enabled)
        self.modifierCombo.setEnabled(enabled)
        self.modifierForCombo.setEnabled(enabled)

    def _setMessage(self, text: str) -> None:
        self.messageLabel.setText(text)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.closeToTray:
            event.ignore()
            self.hide()
            self.closedToTray.emit()
            return
        super().closeEvent(event)
