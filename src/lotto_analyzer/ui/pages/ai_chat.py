"""AI-Chat-Seite: Vollständiger Chat mit Claude.

Nutzt AIPanel Widget — kein duplizierter Chat-Code.
"""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from lotto_common.config import ConfigManager
from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("ai_chat_page")
from lotto_analyzer.ui.pages.base_page import BasePage
from lotto_analyzer.ui.widgets.ai_panel import AIPanel
from lotto_analyzer.ui.widgets.help_button import HelpButton


class AIChatPage(BasePage):
    """Chat-Fenster für Lotto-Fragen an Claude — nutzt AIPanel Widget."""

    def __init__(self, config_manager: ConfigManager, db: Database | None, app_mode: str, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(config_manager=config_manager, db=db, app_mode=app_mode, api_client=api_client,
                         app_db=app_db, backtest_db=backtest_db)
        self._ai = None

        self._init_ai()
        self._build_ui()

    def _init_ai(self) -> None:
        """AI-Analyst initialisieren — im Client-Modus via Server."""
        # Standalone-AI entfernt: AI läuft immer auf dem Server
        pass

    def _build_ui(self) -> None:
        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_box.set_margin_top(12)
        header_box.set_margin_start(24)
        header_box.set_margin_end(24)

        title = Gtk.Label(label=_("AI-Chat"))
        title.add_css_class("title-1")
        header_box.append(title)

        header_box.append(
            HelpButton(_("Stelle Fragen zu Lotto-Statistiken, Trends, Strategien "
                         "oder lass dir Zahlen erklaeren. Die AI kennt alle Daten "
                         "aus deiner Datenbank."))
        )

        # Modell-Info
        config = self.config_manager.config
        parts = config.ai.model.split("-")
        model_name = parts[1].title() if len(parts) > 1 else "Claude"
        self._model_label = Gtk.Label(label=f"Claude ({model_name})")
        self._model_label.add_css_class("dim-label")
        self._model_label.set_hexpand(True)
        self._model_label.set_halign(Gtk.Align.END)
        header_box.append(self._model_label)

        self.append(header_box)

        # AIPanel — hat alles: Chat, Mic, Speaker, History, Neuer Chat, Delete
        self._ai_panel = AIPanel(
            ai_analyst=self._ai,
            api_client=self.api_client,
            title=_("Lotto AI-Chat"),
            config_manager=self.config_manager,
            db=self.db,
            page="ai_chat",
            app_db=self.app_db,
        )
        self._ai_panel.set_vexpand(True)
        self.append(self._ai_panel)

        # API-Key Warnung wenn noetig
        if not self._ai and self.app_mode != "client" and not self.api_client:
            self._ai_panel.add_message(
                _("Kein API-Schlüssel konfiguriert. "
                  "Bitte unter Einstellungen → AI-Konfiguration "
                  "deinen Anthropic API-Key eintragen."),
                is_user=False,
            )

    def cleanup(self) -> None:
        """Laufende AI-Anfragen abbrechen."""
        super().cleanup()
        if hasattr(self._ai_panel, 'cleanup'):
            self._ai_panel.cleanup()

    def set_api_client(self, client: "APIClient | None") -> None:
        """API-Client setzen und an AIPanel weitergeben."""
        super().set_api_client(client)
        self._ai_panel.api_client = client
