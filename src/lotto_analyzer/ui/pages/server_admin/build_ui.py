"""Server-Admin page: UI construction mixin."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from lotto_common.i18n import _
from lotto_analyzer.ui.widgets.help_button import HelpButton


class BuildUIMixin:
    """Builds the Server-Admin page UI (split from page.py for size)."""

    def _build_ui(self) -> None:
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        self.append(scrolled)

        clamp = Adw.Clamp(maximum_size=900)
        scrolled.set_child(clamp)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        clamp.set_child(content)

        title = Gtk.Label(label=_("Server-Verwaltung"))
        title.add_css_class("title-1")
        content.append(title)

        self._build_tls_section(content)
        self._build_le_section(content)
        self._build_user_section(content)
        self._build_apikey_section(content)
        self._build_ssh_section(content)
        self._build_cert_section(content)
        self._build_audit_section(content)
        self._build_service_section(content)
        self._build_scheduler_section(content)
        self._build_ml_section(content)
        self._build_db_section(content)
        self._build_telegram_bot_section(content)
        self._build_refresh_button(content)

        if self.app_mode == "client":
            self._disable_local_controls()

    def _build_tls_section(self, content):
        tls_group = Adw.PreferencesGroup(
            title=_("TLS/Sicherheit"),
            description=_("HTTPS-Verschluesselung"),
        )
        tls_group.set_header_suffix(
            HelpButton(_("HTTPS-Verschluesselung fuer die Verbindung zwischen GUI und Server."))
        )
        content.append(tls_group)

        self._tls_status = Adw.ActionRow(
            title=_("TLS-Status"), subtitle=_("Wird geprueft..."),
        )
        tls_group.add(self._tls_status)

        gen_cert_btn = Gtk.Button(label=_("Zertifikat generieren"))
        gen_cert_btn.set_valign(Gtk.Align.CENTER)
        gen_cert_btn.set_tooltip_text(_("Self-Signed TLS-Zertifikat generieren"))
        gen_cert_btn.connect("clicked", self._on_generate_cert)
        self._gen_cert_btn = gen_cert_btn
        self._cert_row = Adw.ActionRow(
            title=_("Self-Signed Zertifikat"),
            subtitle=_("Neues TLS-Zertifikat erstellen"),
        )
        self._cert_row.add_suffix(gen_cert_btn)
        tls_group.add(self._cert_row)

    def _build_le_section(self, content):
        le_group = Adw.PreferencesGroup(
            title=_("Let's Encrypt"),
            description=_("Vertrauenswuerdiges TLS-Zertifikat (ACME)"),
        )
        le_group.set_header_suffix(
            HelpButton(_("Let's Encrypt stellt kostenlose TLS-Zertifikate aus. "
                         "Webroot-Methode nutzt den bestehenden Webserver."))
        )
        content.append(le_group)

        self._le_status = Adw.ActionRow(title=_("Zertifikat-Status"), subtitle=_("Nicht konfiguriert"))
        le_group.add(self._le_status)

        self._le_domain = Adw.EntryRow(title=_("Domain"))
        le_group.add(self._le_domain)
        self._le_email = Adw.EntryRow(title=_("E-Mail"))
        le_group.add(self._le_email)
        self._le_webroot = Adw.EntryRow(title=_("Webroot-Pfad"))
        le_group.add(self._le_webroot)

        self._le_method = Adw.ComboRow(title=_("Methode"))
        method_model = Gtk.StringList.new([_("Webroot (certbot)"), _("Vorhandenes Zertifikat")])
        self._le_method.set_model(method_model)
        le_group.add(self._le_method)

        self._le_auto_renew = Adw.SwitchRow(
            title=_("Automatische Erneuerung"),
            subtitle=_("30 Tage vor Ablauf automatisch erneuern"),
        )
        self._le_auto_renew.set_active(True)
        le_group.add(self._le_auto_renew)

        le_action_row = Adw.ActionRow(title=_("Aktionen"))
        for label, handler, css, attr, tooltip in [
            (_("Zertifikat anfordern"), self._on_le_request, "suggested-action", "_le_request_btn",
             _("Let's Encrypt Zertifikat anfordern")),
            (_("Jetzt erneuern"), self._on_le_renew, "", "_le_renew_btn",
             _("Let's Encrypt Zertifikat sofort erneuern")),
            (_("Erkennen"), self._on_le_detect, "", "_le_detect_btn",
             _("Vorhandenes Zertifikat automatisch erkennen")),
        ]:
            btn = Gtk.Button(label=label)
            if css:
                btn.add_css_class(css)
            btn.set_valign(Gtk.Align.CENTER)
            btn.set_tooltip_text(tooltip)
            btn.connect("clicked", handler)
            le_action_row.add_suffix(btn)
            setattr(self, attr, btn)
        le_group.add(le_action_row)

        le_save_row = Adw.ActionRow(title=_("Konfiguration"))
        self._le_save_btn = Gtk.Button(label=_("Speichern"))
        self._le_save_btn.set_valign(Gtk.Align.CENTER)
        self._le_save_btn.set_tooltip_text(_("Let's Encrypt Konfiguration speichern"))
        self._le_save_btn.connect("clicked", self._on_le_save_config)
        le_save_row.add_suffix(self._le_save_btn)
        le_group.add(le_save_row)

    def _build_user_section(self, content):
        user_group = Adw.PreferencesGroup(
            title=_("Benutzerverwaltung"), description=_("Server-Benutzerkonten"),
        )
        user_group.set_header_suffix(
            HelpButton(_("Server-Konten erstellen/loeschen. Admin = voller Zugriff, User = Lesen + Generieren."))
        )
        content.append(user_group)

        self._user_list_box = Gtk.ListBox()
        self._user_list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._user_list_box.add_css_class("boxed-list")
        user_group.add(self._user_list_box)

        user_btn_row = Adw.ActionRow(title=_("Aktionen"))
        create_btn = Gtk.Button(label=_("Neuer Benutzer"))
        create_btn.add_css_class("suggested-action")
        create_btn.set_valign(Gtk.Align.CENTER)
        create_btn.set_tooltip_text(_("Neuen Benutzer erstellen"))
        create_btn.connect("clicked", self._on_create_user)
        user_btn_row.add_suffix(create_btn)
        user_group.add(user_btn_row)

    def _build_apikey_section(self, content):
        api_group = Adw.PreferencesGroup(title=_("API-Key"))
        api_group.set_header_suffix(
            HelpButton(_("Authentifizierungsschluessel fuer die Server-Verbindung."))
        )
        content.append(api_group)

        self._api_key_display = Adw.ActionRow(title=_("Aktueller Key"), subtitle="****...****")
        self._api_key_display.add_prefix(Gtk.Image.new_from_icon_name("dialog-password-symbolic"))
        rotate_btn = Gtk.Button(label=_("Rotieren"))
        rotate_btn.set_valign(Gtk.Align.CENTER)
        rotate_btn.set_tooltip_text(_("API-Key fuer den angemeldeten Benutzer neu generieren"))
        rotate_btn.connect("clicked", self._on_rotate_api_key)
        self._api_key_display.add_suffix(rotate_btn)
        api_group.add(self._api_key_display)

    def _build_ssh_section(self, content):
        ssh_group = Adw.PreferencesGroup(
            title=_("SSH-Schluessel"),
            description=_("Registrierte SSH Public Keys"),
        )
        ssh_group.set_header_suffix(
            HelpButton(_("SSH-Schluessel erlauben Login per Challenge-Response (RSA/Ed25519)."))
        )
        content.append(ssh_group)

        self._ssh_key_list = Gtk.ListBox()
        self._ssh_key_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._ssh_key_list.add_css_class("boxed-list")
        ssh_group.add(self._ssh_key_list)

        ssh_btn_row = Adw.ActionRow(title=_("Aktionen"))
        add_key_btn = Gtk.Button(label=_("Key hinzufuegen"))
        add_key_btn.add_css_class("suggested-action")
        add_key_btn.set_valign(Gtk.Align.CENTER)
        add_key_btn.set_tooltip_text(_("SSH Public Key registrieren"))
        add_key_btn.connect("clicked", self._on_add_ssh_key)
        ssh_btn_row.add_suffix(add_key_btn)
        ssh_group.add(ssh_btn_row)

    def _build_cert_section(self, content):
        cert_group = Adw.PreferencesGroup(
            title=_("Client-Zertifikate"),
            description=_("Zertifikate fuer zertifikatsbasierte Anmeldung"),
        )
        cert_group.set_header_suffix(
            HelpButton(_("Client-Zertifikate werden von der Server-CA ausgestellt."))
        )
        content.append(cert_group)

        self._cert_list = Gtk.ListBox()
        self._cert_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._cert_list.add_css_class("boxed-list")
        cert_group.add(self._cert_list)

        cert_btn_row = Adw.ActionRow(title=_("Aktionen"))
        issue_btn = Gtk.Button(label=_("Zertifikat ausstellen"))
        issue_btn.add_css_class("suggested-action")
        issue_btn.set_valign(Gtk.Align.CENTER)
        issue_btn.set_tooltip_text(_("Client-Zertifikat ausstellen"))
        issue_btn.connect("clicked", self._on_issue_cert)
        cert_btn_row.add_suffix(issue_btn)
        cert_group.add(cert_btn_row)

    def _build_audit_section(self, content):
        audit_group = Adw.PreferencesGroup(
            title=_("Audit-Log"), description=_("Letzte API-Zugriffe"),
        )
        audit_group.set_header_suffix(
            HelpButton(_("Protokoll aller API-Zugriffe: wer hat wann was gemacht."))
        )
        content.append(audit_group)

        self._audit_limit = 10
        audit_ctrl = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        audit_ctrl.set_margin_bottom(4)
        audit_ctrl.append(Gtk.Label(label=_("Zeilen:")))

        self._audit_limit_combo = Gtk.ComboBoxText()
        for n in ["10", "20", "30"]:
            self._audit_limit_combo.append_text(n)
        self._audit_limit_combo.set_active(0)
        self._audit_limit_combo.connect("changed", self._on_audit_limit_changed)
        audit_ctrl.append(self._audit_limit_combo)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        audit_ctrl.append(spacer)

        self._audit_select_all = Gtk.CheckButton(label=_("Alle"))
        self._audit_select_all.set_tooltip_text(_("Alle Eintraege aus-/abwaehlen"))
        self._audit_select_all.connect("toggled", self._on_audit_select_all)
        audit_ctrl.append(self._audit_select_all)

        self._audit_delete_btn = Gtk.Button(label=_("Markierte loeschen"))
        self._audit_delete_btn.set_icon_name("user-trash-symbolic")
        self._audit_delete_btn.add_css_class("destructive-action")
        self._audit_delete_btn.set_sensitive(False)
        self._audit_delete_btn.connect("clicked", self._on_audit_delete)
        audit_ctrl.append(self._audit_delete_btn)
        audit_group.add(audit_ctrl)

        self._audit_list = Gtk.ListBox()
        self._audit_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._audit_list.add_css_class("boxed-list")
        self._audit_checks: list[tuple[Gtk.CheckButton, dict]] = []

        audit_scroll = Gtk.ScrolledWindow()
        audit_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        audit_scroll.set_min_content_height(200)
        audit_scroll.set_max_content_height(500)
        audit_scroll.set_child(self._audit_list)
        audit_scroll.set_margin_start(16)
        audit_scroll.set_margin_end(16)
        self._audit_scroll = audit_scroll
        content.append(audit_scroll)

    def _build_service_section(self, content):
        service_group = Adw.PreferencesGroup(
            title=_("systemd Service"), description="lotto-analyzer-server.service",
        )
        service_group.set_header_suffix(
            HelpButton(_("LottoAnalyzer-Server als Systemdienst. Autostart = startet beim Booten."))
        )
        content.append(service_group)

        self._service_status = Adw.ActionRow(title=_("Status"), subtitle=_("Wird geladen..."))
        self._service_status.add_prefix(Gtk.Image.new_from_icon_name("system-run-symbolic"))
        service_group.add(self._service_status)

        self._autostart = Adw.SwitchRow(
            title=_("Autostart"), subtitle=_("Service beim Booten starten"),
        )
        self._autostart.connect("notify::active", self._on_autostart_toggled)
        service_group.add(self._autostart)

        btn_row = Adw.ActionRow(title=_("Service-Steuerung"))
        self._service_buttons: dict[str, Gtk.Button] = {}
        for label, action, css in [
            ("Start", "start", "suggested-action"),
            ("Stop", "stop", "destructive-action"),
            ("Restart", "restart", ""),
        ]:
            btn = Gtk.Button(label=label)
            if css:
                btn.add_css_class(css)
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect("clicked", self._on_service_action, action)
            btn_row.add_suffix(btn)
            self._service_buttons[action] = btn
        service_group.add(btn_row)

    def _build_scheduler_section(self, content):
        sched_group = Adw.PreferencesGroup(title=_("Auto-Crawl Scheduler"))
        sched_group.set_header_suffix(
            HelpButton(_("Automatischer Crawl-Zeitplan: prueft nach jeder Ziehung auf neue Daten."))
        )
        content.append(sched_group)

        self._sched_status = Adw.ActionRow(
            title=_("Scheduler"), subtitle=_("Aktiv – Naechster Crawl: —"),
        )
        sched_group.add(self._sched_status)

        self._retry_info = Adw.ActionRow(title=_("Retry-Status"), subtitle=_("Kein Retry aktiv"))
        sched_group.add(self._retry_info)

    def _build_ml_section(self, content):
        ml_group = Adw.PreferencesGroup(title=_("ML-Engine"))
        content.append(ml_group)

        self._ml_status = Adw.ActionRow(title=_("Letztes Training"), subtitle="—")
        ml_group.add(self._ml_status)
        self._ml_accuracy = Adw.ActionRow(title=_("Genauigkeit"), subtitle="—")
        ml_group.add(self._ml_accuracy)

    def _build_db_section(self, content):
        db_group = Adw.PreferencesGroup(title=_("Datenbank"))
        content.append(db_group)

        self._db_size = Adw.ActionRow(title=_("Groesse"), subtitle="—")
        db_group.add(self._db_size)
        self._db_draws = Adw.ActionRow(title=_("Ziehungen"), subtitle="—")
        db_group.add(self._db_draws)

        self._backup_btn = Gtk.Button(label=_("Backup erstellen"))
        self._backup_btn.set_valign(Gtk.Align.CENTER)
        self._backup_btn.set_tooltip_text(_("Datenbank-Backup erstellen"))
        self._backup_btn.connect("clicked", self._on_backup)
        backup_row = Adw.ActionRow(title=_("Backup"), subtitle=_("SQLite-Datenbank sichern"))
        backup_row.add_suffix(self._backup_btn)
        db_group.add(backup_row)

    def _build_telegram_bot_section(self, content):
        tg_bot_group = Adw.PreferencesGroup(
            title=_("Telegram-Bots pro Benutzer"),
            description=_("Jedem User kann ein eigener Telegram-Bot zugewiesen werden"),
        )
        content.append(tg_bot_group)

        self._tg_bot_list = Gtk.ListBox()
        self._tg_bot_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._tg_bot_list.add_css_class("boxed-list")
        tg_bot_group.add(self._tg_bot_list)

        tg_add_row = Adw.ActionRow(title="")
        tg_add_btn = Gtk.Button(label=_("Bot zuweisen"))
        tg_add_btn.add_css_class("suggested-action")
        tg_add_btn.set_valign(Gtk.Align.CENTER)
        tg_add_btn.set_tooltip_text(_("Telegram-Bot diesem Benutzer zuweisen"))
        tg_add_btn.connect("clicked", self._on_add_telegram_bot)
        tg_add_row.add_suffix(tg_add_btn)
        tg_bot_group.add(tg_add_row)

    def _build_refresh_button(self, content):
        refresh_box = Gtk.Box(halign=Gtk.Align.CENTER)
        refresh_box.set_margin_top(12)
        refresh_btn = Gtk.Button(label=_("Status aktualisieren"))
        refresh_btn.add_css_class("pill")
        refresh_btn.set_tooltip_text(_("Server-Status und Benutzer neu laden"))
        refresh_btn.connect("clicked", lambda _: self._load_status())
        refresh_box.append(refresh_btn)
        content.append(refresh_box)

    def _disable_local_controls(self):
        """Disable local-only controls in client mode."""
        if hasattr(self, "_gen_cert_btn"):
            self._gen_cert_btn.set_sensitive(False)
        self._cert_row.set_subtitle(_("TLS wird auf dem Server verwaltet"))
        for btn in self._service_buttons.values():
            btn.set_sensitive(False)
        self._autostart.set_sensitive(False)
        self._service_status.set_subtitle(_("Wird via API abgefragt"))
        self._backup_btn.set_sensitive(False)
