"""UI-Seite settings: part2."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("settings.part2")
from lotto_analyzer.client.api_client import APIClient
from lotto_common.models.ai_config import AIMode, ServerConfig, resolve_cli_path
import subprocess

from lotto_analyzer.ui.ui_helpers import show_error_toast


class Part2Mixin:
    """Part2 Mixin."""

    def _save_settings_to_server(self) -> None:
        """Alle Einstellungen an den Server senden (AI, Crawl, Learning, Generation)."""
        # AI
        mode = "api" if self._ai_mode.get_selected() == 0 else "cli"
        idx = self._model_combo.get_selected()
        model = self._model_values[idx] if 0 <= idx < len(self._model_values) else None
        api_key = self._api_key.get_text().strip() or None
        cli_path = self._cli_path.get_text().strip() or None

        # Crawl
        crawl_data = {
            "enabled": self._crawl_enabled.get_active(),
            "retry_interval_hours": int(self._retry_interval.get_value()),
        }

        # Learning
        learn_data = {
            "enabled": self._learn_enabled.get_active(),
            "auto_retrain_after_draw": self._auto_retrain.get_active(),
            "auto_train_on_startup": self._train_on_startup.get_active(),
            "auto_self_improve": self._self_improve.get_active(),
            "crawl_timing_learning": self._crawl_timing.get_active(),
            "strategy_weight_learning": self._strategy_weights.get_active(),
            "evaluation_window": int(self._eval_window.get_value()),
            "max_model_age_days": int(self._max_model_age.get_value()),
        }

        # Generation
        gen_data = {
            "enabled": self._autogen_enabled.get_active(),
            "generate_after_train": self._gen_after_train.get_active(),
            "auto_compare": self._auto_compare.get_active(),
            "count_per_strategy": int(self._count_per_strategy.get_value()),
            "purchase_count": int(self._purchase_count.get_value()),
        }

        def worker():
            errors = []
            try:
                self.api_client.update_ai_settings(
                    mode=mode, model=model, api_key=api_key, cli_path=cli_path,
                )
            except Exception as e:
                errors.append(f"AI: {e}")
            try:
                self.api_client.update_crawl_settings(**crawl_data)
            except Exception as e:
                errors.append(f"Crawl: {e}")
            try:
                self.api_client.update_learning_settings(**learn_data)
            except Exception as e:
                errors.append(f"Learning: {e}")
            try:
                self.api_client.update_generation_settings(**gen_data)
            except Exception as e:
                errors.append(f"Generation: {e}")
            GLib.idle_add(self._on_server_settings_saved, errors, self._save_btn)

        threading.Thread(target=worker, daemon=True).start()

    def _on_server_settings_saved(self, errors: list[str], button: Gtk.Button = None) -> bool:
        """Ergebnis des Server-Speicherns."""
        if errors:
            logger.error(f"Server-Settings teils fehlgeschlagen: {errors}")
            if button:
                button.set_label(_("Fehler beim Speichern!"))
                button.set_sensitive(True)
                button.add_css_class("error")
            # Toast mit Details
            show_error_toast(self, f"Server: {', '.join(errors)}")
        else:
            logger.info("Alle Server-Einstellungen gespeichert")
            if button:
                button.set_label(_("Gespeichert!"))
                button.set_sensitive(False)
        return False

    def _on_save(self, button: Gtk.Button) -> None:
        """Einstellungen speichern."""
        if self._is_readonly:
            return
        config = self.config_manager.config

        # Client-Modus: AI, Crawl, Learning, Generation an Server senden
        if self.app_mode == "client" and self.api_client:
            button.set_label(_("Speichere auf Server..."))
            button.set_sensitive(False)
            self._save_settings_to_server()
        else:
            # Standalone: lokal speichern
            config.ai.mode = AIMode.API if self._ai_mode.get_selected() == 0 else AIMode.CLI
            idx = self._model_combo.get_selected()
            if 0 <= idx < len(self._model_values):
                config.ai.model = self._model_values[idx]
            config.ai.api_key = self._api_key.get_text()
            config.ai.cli_path = self._cli_path.get_text()

            config.crawl_schedule.enabled = self._crawl_enabled.get_active()
            config.crawl_schedule.retry_interval_hours = int(
                self._retry_interval.get_value()
            )

            config.learning.enabled = self._learn_enabled.get_active()
            config.learning.auto_retrain_after_draw = self._auto_retrain.get_active()
            config.learning.auto_train_on_startup = self._train_on_startup.get_active()
            config.learning.auto_self_improve = self._self_improve.get_active()
            config.learning.crawl_timing_learning = self._crawl_timing.get_active()
            config.learning.strategy_weight_learning = self._strategy_weights.get_active()
            config.learning.evaluation_window = int(self._eval_window.get_value())
            config.learning.max_model_age_days = int(self._max_model_age.get_value())

            config.auto_generation.enabled = self._autogen_enabled.get_active()
            config.auto_generation.generate_after_train = self._gen_after_train.get_active()
            config.auto_generation.auto_compare = self._auto_compare.get_active()
            config.auto_generation.count_per_strategy = int(self._count_per_strategy.get_value())
            config.auto_generation.purchase_count = int(self._purchase_count.get_value())

        # Server-Verbindung (immer lokal speichern)
        config.server.host = self._server_host.get_text()
        config.server.port = int(self._server_port.get_value())
        config.server.use_https = self._server_https.get_active()

        # UI-Sprache
        ui_lang_idx = self._ui_lang_combo.get_selected()
        if 0 <= ui_lang_idx < len(self._ui_lang_codes):
            new_lang = self._ui_lang_codes[ui_lang_idx]
            old_lang = getattr(config, "ui_language", "de")
            config.ui_language = new_lang
            if new_lang != old_lang:
                from lotto_common.i18n import setup_i18n
                setup_i18n(new_lang)

        # Theme
        theme_map = {0: "system", 1: "light", 2: "dark"}
        config.theme = theme_map.get(self._theme_combo.get_selected(), "system")

        # Audio
        config.audio.tts_enabled = self._tts_enabled.get_active()
        lang_idx = self._tts_lang.get_selected()
        if 0 <= lang_idx < len(self._lang_codes):
            config.audio.tts_language = self._lang_codes[lang_idx]
        config.audio.stt_enabled = self._stt_enabled.get_active()
        config.audio.openai_api_key = self._openai_key.get_text()

        # Font
        config.font_size = int(self._font_size_spin.get_value())
        config.font_bold = self._font_bold_switch.get_active()
        config.popup_font_size = int(self._popup_font_spin.get_value())

        self.config_manager.save(config)

        # Font-CSS live anwenden
        app = self.get_root().get_application() if self.get_root() else None
        if app and hasattr(app, "apply_font_settings"):
            app.apply_font_settings()

        # Feedback
        button.set_label(_("Gespeichert!"))
        button.set_sensitive(False)

    def _on_test_connection(self, button: Gtk.Button) -> None:
        """Server-Verbindung testen."""
        self._test_btn.set_sensitive(False)
        self._test_row.set_subtitle(_("Teste Verbindung..."))

        server_config = ServerConfig(
            host=self._server_host.get_text(),
            port=int(self._server_port.get_value()),
            api_key=self.config_manager.config.server.api_key,
            use_https=self._server_https.get_active(),
        )

        def worker():
            try:
                client = APIClient(server_config)
                ok, message = client.test_connection()
                if not ok:
                    client.close()
                    client = None
            except Exception as e:
                ok, message = False, str(e)
                client = None
            GLib.idle_add(self._on_test_result, ok, message, client)

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_result(self, ok: bool, message: str, client=None) -> bool:
        self._test_btn.set_sensitive(True)
        prefix = _("OK") if ok else _("Fehler")
        self._test_row.set_subtitle(f"{prefix}: {message}")
        if ok:
            # Server-Verbindungseinstellungen bei Erfolg automatisch speichern
            config = self.config_manager.config
            config.server.host = self._server_host.get_text()
            config.server.port = int(self._server_port.get_value())
            config.server.use_https = self._server_https.get_active()
            self.config_manager.save(config)
            logger.info("Server-Verbindung gespeichert: %s:%d (HTTPS=%s)",
                        config.server.host, config.server.port, config.server.use_https)
            # API-Client an alle Seiten propagieren
            if client:
                window = self.get_root()
                if window and hasattr(window, "set_api_client"):
                    window.set_api_client(client)
        return False

    def _on_test_cli(self, button: Gtk.Button) -> None:
        """Claude CLI testen."""
        cli_path = self._cli_path.get_text().strip() or "claude"
        cli_path = resolve_cli_path(cli_path)

        def worker():
            try:
                result = subprocess.run(
                    [cli_path, "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    version = result.stdout.strip()
                    GLib.idle_add(self._cli_path.set_text, cli_path)
                    GLib.idle_add(
                        self._cli_test_row.set_subtitle,
                        f"OK: {version}",
                    )
                else:
                    GLib.idle_add(
                        self._cli_test_row.set_subtitle,
                        f"{_('Fehler')}: Exit-Code {result.returncode}",
                    )
            except FileNotFoundError:
                GLib.idle_add(
                    self._cli_test_row.set_subtitle,
                    f"{_('Nicht gefunden')}: {cli_path}",
                )
            except Exception as e:
                GLib.idle_add(self._cli_test_row.set_subtitle, str(e))

        threading.Thread(target=worker, daemon=True).start()

