"""Best-effort AT-SPI probe: is the widget under the cursor scrollable?"""

from __future__ import annotations

import logging
import threading
from typing import Literal

log = logging.getLogger("winmiddle.scrolltarget")

ScrollVerdict = Literal["yes", "no", "unknown"]

_atspiReady = False
_atspiLock = threading.Lock()
_atspiModule = None


def _ensureAtspi():
    """Lazy-import and init AT-SPI; enable the a11y bus so Qt/GTK export trees."""
    global _atspiReady, _atspiModule
    with _atspiLock:
        if _atspiReady:
            return _atspiModule
        try:
            _enableAccessibilityBus()
            import gi

            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi

            Atspi.init()
            _atspiModule = Atspi
            _atspiReady = True
            desktop = Atspi.get_desktop(0)
            log.info(
                "AT-SPI ready (%s application nodes)",
                desktop.get_child_count() if desktop else 0,
            )
            return Atspi
        except Exception:
            log.exception("AT-SPI init failed")
            _atspiModule = None
            _atspiReady = True  # don't retry every click
            return None


def _enableAccessibilityBus() -> None:
    """Ask the session a11y bus to turn on toolkit bridges (Kate, Dolphin, …)."""
    try:
        from PyQt6.QtDBus import QDBusConnection, QDBusMessage, QDBusVariant

        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return
        msg = QDBusMessage.createMethodCall(
            "org.a11y.Bus",
            "/org/a11y/bus",
            "org.freedesktop.DBus.Properties",
            "Set",
        )
        msg.setArguments(["org.a11y.Status", "IsEnabled", QDBusVariant(True)])
        bus.call(msg)
    except Exception as exc:
        log.debug("could not enable a11y bus: %s", exc)


def _roleName(node) -> str:
    try:
        return (node.get_role_name() or "").strip().lower()
    except Exception:
        return ""


def _roles(Atspi, *names: str):
    out = set()
    for name in names:
        role = getattr(Atspi.Role, name, None)
        if role is not None:
            out.add(role)
    return out


def _isExplicitNo(node, Atspi) -> bool:
    noRoles = _roles(
        Atspi,
        "PAGE_TAB",
        "PAGE_TAB_LIST",
        "PUSH_BUTTON",
        "TOGGLE_BUTTON",
        "RADIO_BUTTON",
        "CHECK_BOX",
        "MENU",
        "MENU_ITEM",
        "MENU_BAR",
        "POPUP_MENU",
        "TOOL_BAR",
        "LINK",
        "SCROLL_BAR",
        "SLIDER",
        "SPIN_BUTTON",
        "COMBO_BOX",
    )
    role = node.get_role()
    if role in noRoles:
        return True
    name = _roleName(node)
    # Some bridges use descriptive strings not in the enum set above.
    if name in {
        "page tab",
        "page tab list",
        "push button",
        "toggle button",
        "tool bar",
        "menu bar",
        "menu item",
        "link",
        "scroll bar",
        "push button menu",
    }:
        return True
    return False


def _isExplicitYes(node, Atspi) -> bool:
    yesRoles = _roles(
        Atspi,
        "SCROLL_PANE",
        "VIEWPORT",
        "DOCUMENT_FRAME",
        "DOCUMENT_TEXT",
        "DOCUMENT_WEB",
        "DOCUMENT_EMAIL",
        "DOCUMENT_PRESENTATION",
        "DOCUMENT_SPREADSHEET",
        "HTML_CONTAINER",
        "LIST",
        "LIST_BOX",
        "TREE",
        "TREE_TABLE",
        "TABLE",
        "TERMINAL",
    )
    role = node.get_role()
    if role in yesRoles:
        return True
    name = _roleName(node)
    if name in {
        "scroll pane",
        "viewport",
        "document frame",
        "document text",
        "document web",
        "html container",
        "list",
        "list box",
        "tree",
        "tree table",
        "table",
        "terminal",
    }:
        return True
    # Multiline editable / text views (Kate editor, etc.)
    textRoles = _roles(Atspi, "TEXT", "ENTRY", "EDITBAR")
    if role in textRoles or name in {"text", "entry", "edit bar"}:
        try:
            states = node.get_state_set()
            if states.contains(Atspi.StateType.MULTI_LINE):
                return True
            # Kate sometimes omits MULTI_LINE on the text peer; treat plain
            # "text" under an editor as scrollable when not single-line.
            if not states.contains(Atspi.StateType.SINGLE_LINE):
                return True
        except Exception:
            if name == "text":
                return True
    return False


def _isGenericChrome(node) -> bool:
    return _roleName(node) in {
        "filler",
        "panel",
        "layered pane",
        "split pane",
        "section",
        "grouping",
        "",
    }


def _descendantHasYes(node, Atspi, *, budget: list[int]) -> bool:
    if node is None or budget[0] <= 0:
        return False
    budget[0] -= 1
    if _isExplicitYes(node, Atspi):
        return True
    try:
        count = node.get_child_count()
    except Exception:
        return False
    for i in range(min(count, 40)):
        try:
            child = node.get_child_at_index(i)
        except Exception:
            continue
        if child is not None and _descendantHasYes(child, Atspi, budget=budget):
            return True
    return False


def _accessibleAtScreenPoint(Atspi, x: int, y: int):
    desktop = Atspi.get_desktop(0)
    if desktop is None:
        return None
    try:
        appCount = desktop.get_child_count()
    except Exception:
        return None
    for i in range(appCount):
        try:
            app = desktop.get_child_at_index(i)
        except Exception:
            continue
        if app is None:
            continue
        try:
            winCount = app.get_child_count()
        except Exception:
            continue
        for j in range(winCount):
            try:
                window = app.get_child_at_index(j)
            except Exception:
                continue
            if window is None:
                continue
            try:
                if not window.is_component():
                    continue
                ext = window.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
                if ext.width <= 0 or ext.height <= 0:
                    continue
                if not (ext.x <= x < ext.x + ext.width and ext.y <= y < ext.y + ext.height):
                    continue
                hit = window.get_accessible_at_point(x, y, Atspi.CoordType.SCREEN)
                if hit is not None:
                    return hit
            except Exception:
                continue
    return None


def probeScrollTarget(x: int, y: int) -> ScrollVerdict:
    """Return whether screen point (x,y) looks like a scrollable target."""
    Atspi = _ensureAtspi()
    if Atspi is None:
        return "unknown"
    try:
        hit = _accessibleAtScreenPoint(Atspi, int(x), int(y))
    except Exception:
        log.debug("accessible-at-point failed", exc_info=True)
        return "unknown"
    if hit is None:
        return "unknown"

    # Pass 1: explicit non-scrollable chrome (tabs, buttons, toolbars).
    cur = hit
    for _ in range(14):
        if cur is None:
            break
        try:
            if _isExplicitNo(cur, Atspi):
                return "no"
            if cur.get_role() == Atspi.Role.APPLICATION:
                break
            cur = cur.get_parent()
        except Exception:
            break

    # Pass 2: explicit scrollable roles on the hit chain.
    cur = hit
    for _ in range(14):
        if cur is None:
            break
        try:
            if _isExplicitYes(cur, Atspi):
                return "yes"
            if cur.get_role() == Atspi.Role.APPLICATION:
                break
            cur = cur.get_parent()
        except Exception:
            break

    # Pass 3: Kate-style editors often hit-test as empty fillers; look for a
    # scrollable/text descendant under nearby ancestors (not across the whole app).
    cur = hit
    for depth in range(8):
        if cur is None:
            break
        try:
            role = cur.get_role()
            if role == Atspi.Role.APPLICATION:
                break
            if _isExplicitNo(cur, Atspi):
                return "no"
            if _isGenericChrome(cur) or depth == 0:
                if _descendantHasYes(cur, Atspi, budget=[120]):
                    return "yes"
            if role in {Atspi.Role.FRAME, Atspi.Role.WINDOW, Atspi.Role.DIALOG}:
                if _descendantHasYes(cur, Atspi, budget=[160]):
                    return "yes"
                break
            cur = cur.get_parent()
        except Exception:
            break

    return "unknown"
