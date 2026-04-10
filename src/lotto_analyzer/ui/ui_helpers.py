"""Gemeinsame UI-Hilfsfunktionen für alle Seiten."""

import logging

from gi.repository import Gtk, Adw, GLib

logger = logging.getLogger("ui_helpers")


def show_toast(widget: Gtk.Widget, message: str) -> None:
    """Toast-Nachricht anzeigen (falls Window erreichbar)."""
    try:
        window = widget.get_root()
        if window and hasattr(window, "add_toast"):
            window.add_toast(Adw.Toast(title=message))
    except Exception as e:
        logger.debug(f"Toast anzeigen fehlgeschlagen: {e}")


def show_error_toast(widget: Gtk.Widget, error: str) -> None:
    """Fehler-Toast anzeigen."""
    show_toast(widget, f"Fehler: {error}")


def format_eur(amount: float) -> str:
    """Betrag im deutschen Format: 1.234,56 EUR"""
    s = f"{amount:,.2f}"
    # US format: 1,234.56 -> German: 1.234,56
    s = s.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{s} EUR"
