"""Round-trip tests for config TOML save/load used by the settings UI."""

from __future__ import annotations

import tempfile
from pathlib import Path

from winmiddle.config import Config, applySpeedPreset, configToToml, loadConfig, saveConfig


def testConfigRoundTripPreservesActivation() -> None:
    cfg = Config()
    cfg.holdScroll = False
    cfg.toggleScroll = True
    cfg.activationModifier = "ctrl"
    cfg.modifierFor = "toggle"
    cfg.showOverlay = False
    cfg.grabDevice = False
    cfg.requireScrollable = False
    cfg.nativeMiddleApps = ["firefox", "zen"]
    cfg.passthroughApps = ["blender", "steam_app"]
    applySpeedPreset(cfg, "fast")
    cfg.dragThresholdPx = 40
    cfg.deadzonePx = 9.5

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        saveConfig(cfg, path)
        loaded = loadConfig(path)

    assert loaded.holdScroll is False
    assert loaded.toggleScroll is True
    assert loaded.activationModifier == "ctrl"
    assert loaded.modifierFor == "toggle"
    assert loaded.showOverlay is False
    assert loaded.grabDevice is False
    assert loaded.requireScrollable is False
    assert loaded.nativeMiddleApps == ["firefox", "zen"]
    assert loaded.passthroughApps == ["blender", "steam_app"]
    assert loaded.speed == "fast"
    assert loaded.dragThresholdPx == 40
    assert loaded.deadzonePx == 9.5
    assert loaded.refNotchesPerSec == 22.0


def testConfigToTomlIncludesSections() -> None:
    text = configToToml(Config())
    assert "[activation]" in text
    assert "[scroll]" in text
    assert "[apps]" in text
    assert "[ui]" in text
    assert 'speed = "normal"' in text


def testDeviceIdsSerializeAsHex() -> None:
    cfg = Config()
    cfg.deviceVendor = 0x046D
    cfg.deviceProduct = 0x405E
    cfg.devicePath = "/dev/input/event12"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        saveConfig(cfg, path)
        body = path.read_text(encoding="utf-8")
        loaded = loadConfig(path)

    assert 'path = "/dev/input/event12"' in body
    assert "vendor = 0x046d" in body
    assert "product = 0x405e" in body
    assert loaded.deviceVendor == 0x046D
    assert loaded.deviceProduct == 0x405E
    assert loaded.devicePath == "/dev/input/event12"


if __name__ == "__main__":
    testConfigRoundTripPreservesActivation()
    testConfigToTomlIncludesSections()
    testDeviceIdsSerializeAsHex()
    print("ok")
