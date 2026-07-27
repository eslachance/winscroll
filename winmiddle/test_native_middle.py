"""native_middle: hold uses winmiddle; toggle-only stays passthrough."""

from __future__ import annotations

from winmiddle.daemon import shouldPassthroughMiddle, skipScrollableProbe
from winmiddle.focus import FocusState


def _chrome() -> FocusState:
    return FocusState(resourceClass="google-chrome", resourceName="Google-chrome")


def _kate() -> FocusState:
    return FocusState(resourceClass="kate", resourceName="kate")


def testNativeMiddleHoldDoesNotPassthrough():
    assert not shouldPassthroughMiddle(
        _chrome(),
        passthroughApps=["steam_app"],
        nativeMiddleApps=["google-chrome"],
        holdScroll=True,
    )


def testNativeMiddleToggleOnlyPassthrough():
    assert shouldPassthroughMiddle(
        _chrome(),
        passthroughApps=["steam_app"],
        nativeMiddleApps=["google-chrome"],
        holdScroll=False,
    )


def testPassthroughAppsStillWin():
    assert shouldPassthroughMiddle(
        FocusState(resourceClass="steam_app_123", resourceName=""),
        passthroughApps=["steam_app"],
        nativeMiddleApps=["google-chrome"],
        holdScroll=True,
    )


def testSkipProbeOnlyForNativeMiddle():
    assert skipScrollableProbe(_chrome(), ["google-chrome"])
    assert not skipScrollableProbe(_kate(), ["google-chrome"])


if __name__ == "__main__":
    testNativeMiddleHoldDoesNotPassthrough()
    testNativeMiddleToggleOnlyPassthrough()
    testPassthroughAppsStillWin()
    testSkipProbeOnlyForNativeMiddle()
    print("ok")
