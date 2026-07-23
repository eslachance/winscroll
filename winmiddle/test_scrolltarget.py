"""Tests for scroll-target config defaults and game passthrough patterns."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from winmiddle.config import Config, loadConfig
from winmiddle.focus import FocusState, matchesAny


class ScrollTargetConfigTests(unittest.TestCase):
    def testDefaultRequireScrollable(self) -> None:
        self.assertTrue(Config().requireScrollable)

    def testGamePassthroughPatterns(self) -> None:
        cfg = Config()
        samples = [
            FocusState(resourceClass="steam_app_570", resourceName=""),
            FocusState(resourceClass="gamescope", resourceName=""),
            FocusState(resourceClass="lutris", resourceName="gta"),
            FocusState(resourceClass="wine64-preloader", resourceName=""),
            FocusState(resourceClass="godot_editor", resourceName=""),
        ]
        for focus in samples:
            self.assertTrue(matchesAny(focus, cfg.passthroughApps), msg=str(focus))

    def testSteamAppPreferredOverBareSteam(self) -> None:
        cfg = Config()
        self.assertIn("steam_app", cfg.passthroughApps)
        steamClient = FocusState(resourceClass="steam", resourceName="steam")
        self.assertFalse(
            matchesAny(steamClient, ["steam_app", "steam_proton", "gameoverlay"])
        )

    def testRequireScrollableConfigOverride(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("[apps]\nrequire_scrollable = false\n", encoding="utf-8")
            cfg = loadConfig(path)
            self.assertFalse(cfg.requireScrollable)


if __name__ == "__main__":
    unittest.main()
