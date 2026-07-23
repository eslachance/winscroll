"""Unit tests for hold/toggle/modifier activation rules."""

from __future__ import annotations

from winmiddle.activation import gestureAllowed, modifierRequiredFor
from winmiddle.config import Config, loadConfig
from winmiddle.modifiers import normalizeModifierName


def testModifierRequiredFor():
    assert modifierRequiredFor("both", "hold")
    assert modifierRequiredFor("both", "toggle")
    assert modifierRequiredFor("hold", "hold")
    assert not modifierRequiredFor("hold", "toggle")
    assert modifierRequiredFor("toggle", "toggle")
    assert not modifierRequiredFor("toggle", "hold")


def testGestureAllowedNoModifier():
    assert gestureAllowed(
        enabled=True,
        activationModifier="none",
        modifierFor="both",
        gesture="hold",
        modifierHeld=False,
    )
    assert not gestureAllowed(
        enabled=False,
        activationModifier="none",
        modifierFor="both",
        gesture="hold",
        modifierHeld=True,
    )


def testGestureAllowedCtrlBoth():
    assert gestureAllowed(
        enabled=True,
        activationModifier="ctrl",
        modifierFor="both",
        gesture="hold",
        modifierHeld=True,
    )
    assert not gestureAllowed(
        enabled=True,
        activationModifier="ctrl",
        modifierFor="both",
        gesture="hold",
        modifierHeld=False,
    )


def testGestureAllowedModifierForHoldOnly():
    # Hold needs ctrl; toggle does not.
    assert not gestureAllowed(
        enabled=True,
        activationModifier="ctrl",
        modifierFor="hold",
        gesture="hold",
        modifierHeld=False,
    )
    assert gestureAllowed(
        enabled=True,
        activationModifier="ctrl",
        modifierFor="hold",
        gesture="toggle",
        modifierHeld=False,
    )


def testNormalizeModifierAliases():
    assert normalizeModifierName("WIN") == "super"
    assert normalizeModifierName("control") == "ctrl"
    assert normalizeModifierName("none") == "none"


def testConfigDefaultsPreferHold():
    cfg = Config()
    assert cfg.holdScroll is True
    assert cfg.toggleScroll is False
    assert cfg.activationModifier == "none"
    assert cfg.modifierFor == "both"


def testLoadActivationSection(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[activation]
hold = false
toggle = true
modifier = "super"
modifier_for = "toggle"
""",
        encoding="utf-8",
    )
    cfg = loadConfig(path)
    assert cfg.holdScroll is False
    assert cfg.toggleScroll is True
    assert cfg.activationModifier == "super"
    assert cfg.modifierFor == "toggle"


if __name__ == "__main__":
    testModifierRequiredFor()
    testGestureAllowedNoModifier()
    testGestureAllowedCtrlBoth()
    testGestureAllowedModifierForHoldOnly()
    testNormalizeModifierAliases()
    testConfigDefaultsPreferHold()
    print("ok (tmp_path tests need pytest)")
