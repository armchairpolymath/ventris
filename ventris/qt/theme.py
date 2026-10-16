"""Colors for light and dark mode. Follows the operating system's setting."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

_dark: bool | None = None  # resolved by refresh()


def _portal_prefers_dark() -> bool | None:
    """Ask the freedesktop settings portal (GNOME, KDE…). None if unavailable.

    PySide6 wheels from PyPI don't read the Linux desktop's appearance setting, so
    on Linux we ask the portal ourselves. 1 = prefer dark, 2 = prefer light.
    """
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface
    except ImportError:
        return None
    iface = QDBusInterface("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                           "org.freedesktop.portal.Settings", QDBusConnection.sessionBus())
    if not iface.isValid():
        return None
    for method in ("ReadOne", "Read"):
        reply = iface.call(method, "org.freedesktop.appearance", "color-scheme")
        args = reply.arguments()
        if not args:
            continue
        value = args[0]
        while hasattr(value, "variant"):  # Read wraps the value twice
            value = value.variant()
        if isinstance(value, int):
            return value == 1
    return None


def _system_prefers_dark(app: QGuiApplication) -> bool:
    scheme = app.styleHints().colorScheme()
    if sys.platform.startswith("linux"):
        portal = _portal_prefers_dark()
        if portal is not None:
            return portal
    if scheme != Qt.ColorScheme.Unknown:
        return scheme == Qt.ColorScheme.Dark
    return app.palette().color(QPalette.ColorRole.Window).lightness() < 128


def _dark_palette() -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: "#242424", QPalette.ColorRole.WindowText: "#f6f5f4",
        QPalette.ColorRole.Base: "#1e1e1e", QPalette.ColorRole.AlternateBase: "#2a2a2a",
        QPalette.ColorRole.Text: "#f6f5f4", QPalette.ColorRole.Button: "#303030",
        QPalette.ColorRole.ButtonText: "#f6f5f4", QPalette.ColorRole.ToolTipBase: "#303030",
        QPalette.ColorRole.ToolTipText: "#f6f5f4", QPalette.ColorRole.Highlight: "#3584e4",
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.Link: "#78aeed",
        QPalette.ColorRole.PlaceholderText: "#8b8f96", QPalette.ColorRole.Mid: "#3a3a3a",
        QPalette.ColorRole.Dark: "#151515", QPalette.ColorRole.Light: "#404040",
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#77767b"))
    return p


def refresh() -> bool:
    """Re-read the system setting and update the app palette. True if it changed."""
    global _dark
    app = QGuiApplication.instance()
    if app is None:
        return False
    dark = _system_prefers_dark(app)
    if dark == _dark:
        return False
    _dark = dark
    palette_is_dark = app.palette().color(QPalette.ColorRole.Window).lightness() < 128
    if dark and not palette_is_dark:
        app.setPalette(_dark_palette())
    elif not dark and palette_is_dark:
        app.setPalette(app.style().standardPalette())
    return True


def is_dark() -> bool:
    if _dark is None:
        refresh()
    return bool(_dark)


def syntax_colors(dark: bool) -> dict[str, str]:
    if dark:
        return {"comment": "#8b8f96", "g": "#ffa348", "m": "#78aeed", "t": "#5bc8af",
                "letter": "#8ff0a4", "number": "#c0bfbc"}
    return {"comment": "#77767b", "g": "#c64600", "m": "#1c71d8", "t": "#26a269",
            "letter": "#2ec27e", "number": "#3d3846"}


def current_line_color(dark: bool) -> str:
    return "#2a2e35" if dark else "#eef3fb"


def stylesheet(dark: bool) -> str:
    """Styles for the explanation pane (object names are set in explain_view.py)."""
    c = {
        "text": "#f6f5f4" if dark else "#241f31",
        "dim": "#9a9996" if dark else "#6e6d71",
        "card": "#2b2b2f" if dark else "#f4f4f6",
        "raw": "#323238" if dark else "#ebebef",
        "changed": "rgba(53,132,228,0.35)" if dark else "rgba(53,132,228,0.18)",
        "green": "#8ff0a4" if dark else "#1b7f3b",
        "green_bg": "rgba(46,194,126,0.18)",
        "amber": "#f8e45c" if dark else "#8a5a00",
        "amber_bg": "rgba(229,165,10,0.22)",
        "red": "#ff7b63" if dark else "#c01c28",
        "red_bg": "rgba(224,27,36,0.18)",
        "grey_bg": "rgba(128,128,128,0.18)",
    }
    return f"""
    #explainPane {{ background: transparent; }}
    #lineLabel {{ color: {c['dim']}; font-size: 11px; font-weight: bold; letter-spacing: 1px; }}
    #rawLine {{ background: {c['raw']}; border-radius: 8px; padding: 8px 10px; }}
    #title {{ font-size: 20px; font-weight: bold; }}
    #sentence {{ font-size: 15px; }}
    #fileNote {{ font-style: italic; color: {c['dim']}; }}
    #sectionTitle {{ font-size: 14px; font-weight: bold; }}
    #hint {{ color: {c['dim']}; font-size: 11px; }}
    #paramRow, #stateCard {{ background: {c['card']}; border-radius: 8px; }}
    #paramMeaning {{ color: {c['dim']}; font-size: 11px; }}
    #stateHeading {{ font-weight: bold; }}
    #stateLabel {{ color: {c['dim']}; }}
    #stateRow {{ border-radius: 6px; }}
    #stateRow[changed="true"] {{ background: {c['changed']}; }}
    #stateRow[changed="true"] #stateValue {{ font-weight: bold; }}
    #badge {{ border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: bold; }}
    #badge[kind="standard"] {{ background: {c['green_bg']}; color: {c['green']}; }}
    #badge[kind="community"] {{ background: {c['amber_bg']}; color: {c['amber']}; }}
    #badge[kind="unknown"] {{ background: {c['red_bg']}; color: {c['red']}; }}
    #badge[kind="note"] {{ background: {c['grey_bg']}; }}
    #emptyTitle {{ font-size: 22px; font-weight: bold; }}
    #emptyText {{ color: {c['dim']}; }}
    """
