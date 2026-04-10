"""Telegram-Seite: Bot-Login/Logout, QR-Code-Login, Chat-Verlauf."""

from __future__ import annotations

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Pango

from lotto_common.config import ConfigManager
from lotto_common.i18n import _
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from lotto_analyzer.ui.widgets.help_button import HelpButton
from lotto_common.utils.logging_config import get_logger

logger = get_logger("telegram_page")


# ── QR-Code Widget (Cairo-basiert, kein Pillow noetig) ──


class QRCodeWidget(Gtk.DrawingArea):
    """Rendert einen QR-Code aus einer URL mittels Cairo."""

    def __init__(self, size: int = 250):
        super().__init__()
        self._matrix = None
        self._qr_size = size
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self._draw)

    def set_url(self, url: str) -> None:
        """QR-Code aus URL generieren."""
        if not url:
            self._matrix = None
            self.queue_draw()
            return
        try:
            import qrcode
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=1, border=2,
            )
            qr.add_data(url)
            qr.make(fit=True)
            self._matrix = qr.get_matrix()
        except ImportError:
            logger.warning("qrcode nicht installiert: pip install qrcode")
            self._matrix = None
        except Exception as e:
            logger.warning(f"QR-Code Fehler: {e}")
            self._matrix = None
        self.queue_draw()

    def clear(self) -> None:
        self._matrix = None
        self.queue_draw()

    def _draw(self, area, cr, width, height) -> None:
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        if not self._matrix:
            cr.set_source_rgb(0.6, 0.6, 0.6)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(14)
            text = _("Kein QR-Code")
            extents = cr.text_extents(text)
            cr.move_to((width - extents.width) / 2, (height + extents.height) / 2)
            cr.show_text(text)
            return
        rows = len(self._matrix)
        cols = len(self._matrix[0]) if rows else 0
        if rows == 0 or cols == 0:
            return
        module_size = min(width / cols, height / rows)
        x_offset = (width - cols * module_size) / 2
        y_offset = (height - rows * module_size) / 2
        cr.set_source_rgb(0, 0, 0)
        for r, row in enumerate(self._matrix):
            for c, val in enumerate(row):
                if val:
                    cr.rectangle(
                        x_offset + c * module_size, y_offset + r * module_size,
                        module_size, module_size,
                    )
        cr.fill()

