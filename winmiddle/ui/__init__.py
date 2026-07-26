"""PyQt6 settings UI for winmiddle."""

from __future__ import annotations

__all__ = ["runUi"]


def runUi(argv: list[str] | None = None) -> int:
    from winmiddle.ui.app import main

    return main(argv)
