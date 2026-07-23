"""Load TOML config with Windows-middle-click defaults."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Speed presets in real notches/sec terms (noticeably different).
# At ~100px past the deadzone you get ref_nps; far out clamps at max_nps.
# "fast" approximates the old overly-sensitive bring-up feel.
SPEED_PRESETS: dict[str, dict[str, float]] = {
    "slow": {
        "deadzone_px": 16.0,
        "ref_distance_px": 120.0,
        "ref_nps": 3.5,
        "max_nps": 10.0,
        "power": 1.5,
    },
    "normal": {
        "deadzone_px": 12.0,
        "ref_distance_px": 100.0,
        "ref_nps": 9.0,
        "max_nps": 24.0,
        "power": 1.35,
    },
    "fast": {
        "deadzone_px": 8.0,
        "ref_distance_px": 80.0,
        "ref_nps": 22.0,
        "max_nps": 55.0,
        "power": 1.2,
    },
}


def _defaultPassthroughApps() -> list[str]:
    return [
        # Steam / Proton games (prefer steam_app over bare "steam")
        "steam_app",
        "steam_proton",
        "gameoverlay",
        "steamwebhelper",
        "games.exe",
        # Launchers / runtimes
        "lutris",
        "heroic",
        "legendary",
        "bottles",
        "proton",
        "wine",
        "gamescope",
        # Engines / hosts
        "blender",
        "unity",
        "unreal",
        "godot",
        "sdl",
        "minecraft",
        "java",
        "javaw",
        "dota",
        "cs2",
    ]


@dataclass
class Config:
    devicePath: str | None = None
    deviceVendor: int | None = None
    deviceProduct: int | None = None
    dragThresholdPx: float = 50.0
    clickMaxMs: float = 350.0
    speed: str = "normal"
    deadzonePx: float = SPEED_PRESETS["normal"]["deadzone_px"]
    refDistancePx: float = SPEED_PRESETS["normal"]["ref_distance_px"]
    refNotchesPerSec: float = SPEED_PRESETS["normal"]["ref_nps"]
    maxNotchesPerSec: float = SPEED_PRESETS["normal"]["max_nps"]
    scrollPower: float = SPEED_PRESETS["normal"]["power"]
    scrollHz: float = 60.0
    # Noisy middle-click mice (e.g. Logitech M720) emit accidental wheel ticks.
    exitOnWheel: bool = False
    wheelGraceMs: float = 450.0
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
            "navigator",
        ]
    )
    passthroughApps: list[str] = field(default_factory=_defaultPassthroughApps)
    # Only engage autoscroll when AT-SPI says the target looks scrollable.
    requireScrollable: bool = True
    scrollProbeTimeoutMs: float = 15.0
    showOverlay: bool = True
    grabDevice: bool = True

    # Back-compat aliases used by older call sites / docs
    @property
    def scrollGain(self) -> float:
        return self.refNotchesPerSec

    @property
    def scrollExponent(self) -> float:
        return self.scrollPower

    @property
    def maxScrollUnits(self) -> float:
        return self.maxNotchesPerSec


def configPaths() -> list[Path]:
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return [
        xdg / "winmiddle" / "config.toml",
        Path.home() / ".winmiddle.toml",
    ]


def applySpeedPreset(cfg: Config, speed: str) -> None:
    key = (speed or "normal").strip().lower()
    if key not in SPEED_PRESETS:
        raise ValueError(f"Unknown scroll speed {speed!r}; use slow, normal, or fast")
    preset = SPEED_PRESETS[key]
    cfg.speed = key
    cfg.deadzonePx = preset["deadzone_px"]
    cfg.refDistancePx = preset["ref_distance_px"]
    cfg.refNotchesPerSec = preset["ref_nps"]
    cfg.maxNotchesPerSec = preset["max_nps"]
    cfg.scrollPower = preset["power"]


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

    applySpeedPreset(cfg, str(scroll.get("speed", cfg.speed)))

    cfg.dragThresholdPx = float(scroll.get("drag_threshold_px", cfg.dragThresholdPx))
    cfg.clickMaxMs = float(scroll.get("click_max_ms", cfg.clickMaxMs))
    if "deadzone_px" in scroll:
        cfg.deadzonePx = float(scroll["deadzone_px"])
    if "ref_distance_px" in scroll:
        cfg.refDistancePx = float(scroll["ref_distance_px"])
    if "ref_nps" in scroll:
        cfg.refNotchesPerSec = float(scroll["ref_nps"])
    if "max_nps" in scroll:
        cfg.maxNotchesPerSec = float(scroll["max_nps"])
    if "power" in scroll:
        cfg.scrollPower = float(scroll["power"])
    # Legacy override keys from the old gain-based curve
    if "gain" in scroll and "ref_nps" not in scroll:
        cfg.refNotchesPerSec = float(scroll["gain"]) * 120.0  # rough map; prefer ref_nps
    if "exponent" in scroll and "power" not in scroll:
        cfg.scrollPower = float(scroll["exponent"])
    if "max_units" in scroll and "max_nps" not in scroll:
        cfg.maxNotchesPerSec = float(scroll["max_units"])

    cfg.scrollHz = float(scroll.get("hz", cfg.scrollHz))
    if "exit_on_wheel" in scroll:
        cfg.exitOnWheel = bool(scroll["exit_on_wheel"])
    cfg.wheelGraceMs = float(scroll.get("wheel_grace_ms", cfg.wheelGraceMs))

    if "native_middle" in apps:
        cfg.nativeMiddleApps = [str(x) for x in apps["native_middle"]]
    if "passthrough" in apps:
        cfg.passthroughApps = [str(x) for x in apps["passthrough"]]
    if "require_scrollable" in apps:
        cfg.requireScrollable = bool(apps["require_scrollable"])
    cfg.scrollProbeTimeoutMs = float(apps.get("scroll_probe_timeout_ms", cfg.scrollProbeTimeoutMs))

    cfg.showOverlay = bool(ui.get("overlay", cfg.showOverlay))
    return cfg


def defaultConfigText() -> str:
    return """# winmiddle — Windows-faithful middle-click autoscroll

[device]
# vendor = 0x046d
# product = 0x405e
grab = true

[scroll]
# Speed curve: slow | normal | fast
# Measured in wheel notches/sec — presets are deliberately far apart.
speed = "normal"
drag_threshold_px = 50
click_max_ms = 350
hz = 60
exit_on_wheel = false
wheel_grace_ms = 450
# Optional fine-tuning (overrides the preset):
# deadzone_px = 12
# ref_distance_px = 100   # distance past deadzone where you hit ref_nps
# ref_nps = 9             # notches per second at that distance
# max_nps = 24
# power = 1.35            # >1 = gradual near center, faster when far

[apps]
# Only autoscroll when AT-SPI says the click target looks scrollable.
# Unknown (games, no a11y tree, timeout) → native middle-click passthrough.
require_scrollable = true
# scroll_probe_timeout_ms = 15

native_middle = [
  "firefox", "google-chrome", "chromium", "brave", "vivaldi",
  "msedge", "librewolf", "floorp", "zen", "navigator",
]

# Always raw middle button (games / 3D / launchers).
passthrough = [
  "steam_app", "steam_proton", "gameoverlay", "steamwebhelper",
  "lutris", "heroic", "legendary", "bottles", "proton", "wine", "gamescope",
  "blender", "unity", "unreal", "godot", "sdl", "minecraft", "java", "javaw",
]

[ui]
overlay = true
"""
