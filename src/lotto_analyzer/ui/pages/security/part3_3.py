"""UI-Seite security: part3 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_analyzer.ui.ui_helpers import show_toast

logger = get_logger("security.part3")
import ipaddress




class Part3Mixin3:
    """Teil 3 von Part3Mixin."""

    def _on_load_more_logs(self, button: Gtk.Button) -> None:
        """Weitere Log-Einträge laden."""
        self._load_logs(clear=False)

    def _on_cleanup_logs(self, button: Gtk.Button) -> None:
        """Alte Firewall-Logs bereinigen."""
        button.set_sensitive(False)
        self._cleanup_status.set_text(_("Wird bereinigt..."))

        def worker():
            try:
                result = self.api_client.firewall_log_cleanup()
                deleted = result.get("deleted", 0)
                msg = f"{deleted} {_('Einträge gelöscht')}"
                GLib.idle_add(self._cleanup_status.set_text, msg)
                GLib.idle_add(self._load_logs, True)
            except Exception as e:
                GLib.idle_add(self._cleanup_status.set_text, f"Fehler: {e}")
            GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────
    #  Sektion 11: AI-Sicherheitsassistent
    # ──────────────────────────────────────────────────────────────────

    # ── Sektion 11: Audit-Einstellungen ──

    def _build_audit_settings_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("Audit-Einstellungen"),
            description=_("Einzelne Checks für das System-Audit an/aus schalten (persistent)"),
        )
        content.append(group)

        self._audit_toggle_ufw = Adw.SwitchRow(title=_("UFW-Prüfung"), active=True)
        self._audit_toggle_ssh = Adw.SwitchRow(title=_("SSH-Prüfung"), active=True)
        self._audit_toggle_ports = Adw.SwitchRow(title=_("Port-Prüfung"), active=True)
        self._audit_toggle_f2b = Adw.SwitchRow(title=_("Fail2ban-Prüfung"), active=True)

        self._audit_toggles_loading = True  # Verhindert Speichern beim Laden

        for sw in (self._audit_toggle_ufw, self._audit_toggle_ssh,
                   self._audit_toggle_ports, self._audit_toggle_f2b):
            sw.connect("notify::active", self._on_audit_toggle_changed)
            group.add(sw)

        # Settings vom Server laden
        self._load_audit_settings()

    def _load_audit_settings(self) -> None:
        """Audit-Toggle-Einstellungen vom Server laden."""
        if not self.api_client:
            self._audit_toggles_loading = False
            return

        # Flag MUSS vor Thread-Start gesetzt sein, damit Toggle-Signale
        # waehrend des Ladens ignoriert werden (Race-Condition vermeiden)
        self._audit_toggles_loading = True

        def worker():
            try:
                settings = self.api_client.firewall_audit_settings()
                GLib.idle_add(self._apply_audit_settings, settings)
            except Exception as e:
                logger.warning(f"Audit-Einstellungen laden fehlgeschlagen: {e}")
                GLib.idle_add(self._finish_audit_loading)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_audit_settings(self, settings: dict) -> bool:
        self._audit_toggles_loading = True
        self._audit_toggle_ufw.set_active(settings.get("ufw", True))
        self._audit_toggle_ssh.set_active(settings.get("ssh", True))
        self._audit_toggle_ports.set_active(settings.get("ports", True))
        self._audit_toggle_f2b.set_active(settings.get("fail2ban", True))
        self._audit_toggles_loading = False
        return False

    def _finish_audit_loading(self) -> bool:
        self._audit_toggles_loading = False
        return False

    def _on_audit_toggle_changed(self, switch: Adw.SwitchRow, _pspec) -> None:
        """Bei Toggle-Änderung: Settings an Server senden (debounced)."""
        if self._audit_toggles_loading:
            return
        # Debounce: vorherigen Timer abbrechen und neu starten
        if hasattr(self, "_audit_save_timer") and self._audit_save_timer:
            GLib.source_remove(self._audit_save_timer)
        self._audit_save_timer = GLib.timeout_add(self._AUDIT_DEBOUNCE_MS, self._save_audit_settings)

    def _save_audit_settings(self) -> bool:
        """Audit-Settings zum Server senden."""
        self._audit_save_timer = None
        if not self.api_client:
            return False
        settings = {
            "ufw": self._audit_toggle_ufw.get_active(),
            "ssh": self._audit_toggle_ssh.get_active(),
            "ports": self._audit_toggle_ports.get_active(),
            "fail2ban": self._audit_toggle_f2b.get_active(),
        }

        def worker():
            try:
                self.api_client.firewall_set_audit_settings(settings)
            except Exception as e:
                logger.warning(f"Audit-Einstellungen speichern fehlgeschlagen: {e}")

        threading.Thread(target=worker, daemon=True).start()
        return False

    # ── Sektion 12: AI-Sicherheitsassistent ──

    def _build_security_ai_section(self, content: Gtk.Box) -> None:
        group = Adw.PreferencesGroup(
            title=_("AI-Sicherheitsassistent"),
            description=_("System-Audit, AI-Analyse und Security-Chat"),
        )
        content.append(group)

        # ── Sicherheitsbewertung ──
        self._audit_score_row = Adw.ActionRow(
            title=_("Sicherheitsbewertung"),
            subtitle=_("Noch nicht geprüft"),
        )
        audit_btn = Gtk.Button(label=_("System prüfen"))
        audit_btn.set_tooltip_text(_("Sicherheits-Audit des gesamten Systems durchfuehren"))
        audit_btn.add_css_class("suggested-action")
        audit_btn.set_valign(Gtk.Align.CENTER)
        audit_btn.connect("clicked", self._on_run_audit)
        self._audit_score_row.add_suffix(audit_btn)
        group.add(self._audit_score_row)

        # Expander für Audit-Issues
        self._audit_issues_expander = Adw.ExpanderRow(
            title=_("Erkannte Probleme"),
            subtitle=_("Keine"),
            show_enable_switch=False,
        )
        self._audit_issue_rows: list[Adw.ActionRow] = []
        group.add(self._audit_issues_expander)

        # ── AI-Analyse starten ──
        self._ai_analyze_row = Adw.ActionRow(
            title=_("AI-Sicherheitsanalyse"),
            subtitle=_("AI analysiert den Sicherheitszustand"),
        )
        analyze_btn = Gtk.Button(label=_("Analyse starten"))
        analyze_btn.set_tooltip_text(_("AI analysiert Sicherheitslage und gibt Empfehlungen"))
        analyze_btn.set_valign(Gtk.Align.CENTER)
        analyze_btn.connect("clicked", self._on_ai_analyze)
        self._ai_analyze_row.add_suffix(analyze_btn)
        group.add(self._ai_analyze_row)

        # ── Chat-Bereich ──
        chat_frame = Gtk.Frame()
        chat_frame.set_margin_top(8)
        chat_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        chat_frame.set_child(chat_vbox)

        # Nachrichten-ScrolledWindow
        self._sec_chat_scroll = Gtk.ScrolledWindow()
        self._sec_chat_scroll.set_min_content_height(self._CHAT_MIN_HEIGHT)
        self._sec_chat_scroll.set_max_content_height(self._CHAT_MAX_HEIGHT)
        self._sec_chat_scroll.set_policy(
            Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC,
        )
        self._sec_chat_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8,
        )
        self._sec_chat_box.set_margin_top(8)
        self._sec_chat_box.set_margin_bottom(8)
        self._sec_chat_box.set_margin_start(8)
        self._sec_chat_box.set_margin_end(8)
        self._sec_chat_scroll.set_child(self._sec_chat_box)
        chat_vbox.append(self._sec_chat_scroll)

        # Eingabezeile
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        input_box.set_margin_start(8)
        input_box.set_margin_end(8)
        input_box.set_margin_bottom(8)

        self._sec_chat_entry = Gtk.Entry()
        self._sec_chat_entry.set_hexpand(True)
        self._sec_chat_entry.set_placeholder_text(_("Frage zur Server-Sicherheit..."))
        self._sec_chat_entry.connect("activate", self._on_sec_chat_send)
        input_box.append(self._sec_chat_entry)

        self._sec_chat_send_btn = Gtk.Button(icon_name="mail-send-symbolic")
        self._sec_chat_send_btn.set_tooltip_text(_("Nachricht senden"))
        self._sec_chat_send_btn.add_css_class("suggested-action")
        self._sec_chat_send_btn.connect("clicked", self._on_sec_chat_send)
        input_box.append(self._sec_chat_send_btn)

        self._sec_chat_spinner = Gtk.Spinner()
        self._sec_chat_spinner.set_visible(False)
        input_box.append(self._sec_chat_spinner)

        chat_vbox.append(input_box)
        group.add(chat_frame)

    def _add_chat_bubble(self, text: str, is_user: bool) -> None:
        """Chat-Nachricht als Blase hinzufügen."""
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bubble.set_margin_top(2)
        bubble.set_margin_bottom(2)

        label = Gtk.Label()
        label.set_text(text)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_max_width_chars(70)
        label.set_selectable(True)
        label.set_xalign(0)

        if is_user:
            bubble.set_halign(Gtk.Align.END)
            label.add_css_class("card")
            label.set_margin_start(60)
        else:
            bubble.set_halign(Gtk.Align.START)
            label.set_margin_end(60)

        label.set_margin_start(8)
        label.set_margin_end(8)
        label.set_margin_top(4)
        label.set_margin_bottom(4)
        bubble.append(label)
        self._sec_chat_box.append(bubble)

        # Ans Ende scrollen
        def scroll_down():
            adj = self._sec_chat_scroll.get_vadjustment()
            adj.set_value(adj.get_upper())
            return False
        GLib.timeout_add(self._SCROLL_DELAY_MS, scroll_down)

    def _on_run_audit(self, button: Gtk.Button) -> None:
        """System-Sicherheitsaudit durchfuehren."""
        if not self.api_client:
            return
        button.set_sensitive(False)
        self._audit_score_row.set_subtitle(_("Wird geprüft..."))

        def update_issues(issues):
            # Alte Einträge entfernen
            for old_row in self._audit_issue_rows:
                self._audit_issues_expander.remove(old_row)
            self._audit_issue_rows.clear()

            # Neue Issues einfuegen
            for issue in issues:
                row = Adw.ActionRow(title=issue)
                row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
                self._audit_issues_expander.add_row(row)
                self._audit_issue_rows.append(row)
            subtitle = f"{len(issues)} {_('Probleme')}" if issues else _("Keine Probleme")
            self._audit_issues_expander.set_subtitle(subtitle)
            return False

        def worker():
            try:
                result = self.api_client.firewall_system_audit()
                score = result.get("score", 0)
                rating = result.get("rating", "?")
                issues = result.get("issues", [])
                text = f"{score}/100 ({rating})"
                if issues:
                    text += f" — {len(issues)} {_('Probleme')}"
                GLib.idle_add(self._audit_score_row.set_subtitle, text)
                GLib.idle_add(update_issues, issues)
            except Exception as e:
                GLib.idle_add(self._audit_score_row.set_subtitle, f"Fehler: {e}")
            GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()

    def _on_ai_analyze(self, button: Gtk.Button) -> None:
        """AI-Sicherheitsanalyse starten — sendet automatische Anfrage."""
        if not self.api_client or self._sec_chat_sending:
            return
        self._sec_chat_sending = True
        button.set_sensitive(False)
        self._sec_chat_spinner.set_visible(True)
        self._sec_chat_spinner.start()

        msg = "Analysiere den aktuellen Sicherheitszustand meines Servers und gib konkrete Empfehlungen."
        GLib.idle_add(self._add_chat_bubble, msg, True)

        def worker():
            try:
                reply = self.api_client.firewall_chat(msg)
                if isinstance(reply, dict) and "error" in reply:
                    hint = reply.get("hint", "")
                    text = f"{reply['error']}. {hint}"
                    GLib.idle_add(self._add_chat_bubble, text, False)
                else:
                    GLib.idle_add(self._add_chat_bubble, reply, False)
            except Exception as e:
                GLib.idle_add(self._add_chat_bubble, f"Fehler: {e}", False)
            GLib.idle_add(self._sec_chat_done, button)

        threading.Thread(target=worker, daemon=True).start()

    def _on_sec_chat_send(self, _widget) -> None:
        """Freitext-Frage an den Security-Chat senden."""
        if not self.api_client or self._sec_chat_sending:
            return
        msg = self._sec_chat_entry.get_text().strip()
        if not msg:
            return
        self._sec_chat_sending = True
        self._sec_chat_entry.set_text("")
        self._sec_chat_send_btn.set_sensitive(False)
        self._sec_chat_spinner.set_visible(True)
        self._sec_chat_spinner.start()

        self._add_chat_bubble(msg, True)

        def worker():
            try:
                reply = self.api_client.firewall_chat(msg)
                if isinstance(reply, dict) and "error" in reply:
                    hint = reply.get("hint", "")
                    text = f"{reply['error']}. {hint}"
                    GLib.idle_add(self._add_chat_bubble, text, False)
                else:
                    GLib.idle_add(self._add_chat_bubble, reply, False)
            except Exception as e:
                GLib.idle_add(self._add_chat_bubble, f"Fehler: {e}", False)
            GLib.idle_add(self._sec_chat_done, None)

        threading.Thread(target=worker, daemon=True).start()

    def _sec_chat_done(self, button=None) -> bool:
        """Chat-Anfrage abgeschlossen — UI zurücksetzen."""
        self._sec_chat_sending = False
        self._sec_chat_spinner.stop()
        self._sec_chat_spinner.set_visible(False)
        self._sec_chat_send_btn.set_sensitive(True)
        if button:
            button.set_sensitive(True)
        return False

    # ──────────────────────────────────────────────────────────────────
    #  Hilfsmethoden
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_ip_or_cidr(value: str) -> str | None:
        """IP oder CIDR validieren. Gibt Fehlermeldung zurück oder None bei Erfolg."""
        try:
            if "/" in value:
                ipaddress.ip_network(value, strict=False)
            else:
                ipaddress.ip_address(value)
            return None
        except ValueError as e:
            return _("Ungültige IP/CIDR: {}").format(e)

    @staticmethod
    def _clear_listbox(listbox: Gtk.ListBox) -> None:
        """Alle Einträge aus einer ListBox entfernen."""
        while True:
            row = listbox.get_row_at_index(0)
            if row is None:
                break
            listbox.remove(row)

    def _show_error(self, message: str) -> bool:
        """Fehlermeldung als Toast anzeigen (falls Fenster verfügbar)."""
        show_toast(self, message)
        return False
