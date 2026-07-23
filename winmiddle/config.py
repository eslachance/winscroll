"""Load TOML config with Windows-middle-click defaults."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    devicePath: str | None = None
    deviceVendor: int | None = None
    deviceProduct: int | None = None
    dragThresholdPx: float = 6.0
    deadzonePx: float = 8.0
    scrollGain: float = 0.045
    scrollExponent: float = 1.35
    maxScrollUnits: float = 28.0
    scrollHz: float = 60.0
    # Apps that implement real Windows middle-click themselves (passthrough).
    nativeMiddleApps: list[str] = field(
        default_factory=lambda: [
            "firefox",
            "firefox-bin",
            "firefox-esr",
            "google-chrome",
            "chromium",
            "brave-browser",
            "brave",
            "vivaldi",
            "msedge",
            "librewolf",
            "floorp",
            "zen",
            "navigator",  # Firefox resourceClass on some builds
        ]
    )
    # Always pass middle button through untouched (games/3D often need it raw).
    passthroughApps: list[str] = field(
        default_factory=lambda: [
            "steam_app",
            "steam_proton",
            "gamesoverlay",
            "games.exe",
            "blender",
            "unity",
            "unreal",
            "dota",
            "cs2",
            "wine",
            "lutris",
            "heroic",
            "minecraft",
            "java",  # often Minecraft launchers
        ]
    )
    showOverlay: bool = True
    grabDevice: bool = True


def configPaths() -> list[Path]:
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return [
        xdg / "winmiddle" / "config.toml",
        Path.home() / ".winmiddle.toml",
    ]


def loadConfig(path: Path | None = None) -> Config:
    cfg = Config()
    candidates = [path] if path else configPaths()
    data: dict = {}
    for candidate in candidates:
        if candidate and candidate.is_file():
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
            break

    device = data.get("device", {})
    scroll = data.get("scroll", {})
    apps = data.get("apps", {})
    ui = data.get("ui", {})

    if device.get("path"):
        cfg.devicePath = str(device["path"])
    if "vendor" in device:
        cfg.deviceVendor = int(device["vendor"], 0) if isinstance(device["vendor"], str) else int(device["vendor"])
    if "product" in device:
        cfg.deviceProduct = int(device["product"], 0) if isinstance(device["product"], str) else int(device["product"])
    if "grab" in device:
        cfg.grabDevice = bool(device["grab"])

    cfg.dragThresholdPx = float(scroll.get("drag_threshold_px", cfg.dragThresholdPx))
    cfg.deadzonePx = float(scroll.get("deadzone_px", cfg.deadzonePx))
    cfg.scrollGain = float(scroll.get("gain", cfg.scrollGain))
    cfg.scrollExponent = float(scroll.get("exponent", cfg.scrollExponent))
    cfg.maxScrollUnits = float(scroll.get("max_units", cfg.maxScrollUnits))
    cfg.scrollHz = float(scroll.get("hz", cfg.scrollHz))

    if "native_middle" in apps:
        cfg.nativeMiddleApps = [str(x) for x in apps["native_middle"]]
    if "passthrough" in apps:
        cfg.passthroughApps = [str(x) for x in apps["passthrough"]]

    cfg.showOverlay = bool(ui.get("overlay", cfg.showOverlay))
    return cfg


def defaultConfigText() -> str:
    return """# winmiddle — Windows-faithful middle-click autoscroll

[device]
# path = "/dev/input/event10"
# vendor = 0x3434
# product = 0x0b10
grab = true

[scroll]
drag_threshold_px = 6      # above this while held → middle-drag passthrough (Blender etc.)
deadzone_px = 8           # no scroll inside the origin glyph
gain = 0.045
exponent = 1.35
max_units = 28
hz = 60

[apps]
# These apps already do real Windows middle-click (links/tabs/autoscroll).
# We pass middle-click through untouched so native behavior wins.
native_middle = [
  "firefox", "google-chrome", "chromium", "brave", "vivaldi",
  "msedge", "librewolf", "floorp", "zen", "navigator",
]

# Always raw middle button (no autoscroll interception).
passthrough = [
  "steam_app", "blender", "wine", "lutris", "heroic", "minecraft",
]

[ui]
overlay = true
"""
