"""Pure helpers for hold / toggle / modifier activation rules."""

from __future__ import annotations


def modifierRequiredFor(modifierFor: str, gesture: str) -> bool:
    """Whether `activation.modifier` must be held for this gesture."""
    applies = (modifierFor or "both").strip().lower()
    name = gesture.strip().lower()
    if applies == "both":
        return True
    return applies == name


def gestureAllowed(
    *,
    enabled: bool,
    activationModifier: str,
    modifierFor: str,
    gesture: str,
    modifierHeld: bool,
) -> bool:
    """True when this gesture may fire given config + current modifier state."""
    if not enabled:
        return False
    if (activationModifier or "none").strip().lower() in {"", "none"}:
        return True
    if not modifierRequiredFor(modifierFor, gesture):
        return True
    return bool(modifierHeld)
