"""UI-Seite settings: part3."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.user import ConnectionProfile

logger = get_logger("settings.part3")
import subprocess
import os


class Part3Mixin:
    """Part3 Mixin."""

    def _on_auto_detect_cli(self, button: Gtk.Button) -> None:
        """Claude CLI automatisch finden."""
        def worker():
            home = os.path.expanduser("~")
            for path in [
                "claude",
                f"{home}/.local/bin/claude",
                "/usr/local/bin/claude",
                "/usr/bin/claude",
                f"{home}/.npm-global/bin/claude",
            ]:
                try:
                    result = subprocess.run(
                        [path, "--version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if result.returncode == 0:
                        GLib.idle_add(self._cli_path.set_text, path)
                        GLib.idle_add(
                            self._cli_test_row.set_subtitle,
                            f"{_('Gefunden')}: {path} ({result.stdout.strip()})",
                        )
                        return
                except (FileNotFoundError, subprocess.SubprocessError):
                    continue
            # which-Befehl als Fallback
            try:
                result = subprocess.run(
                    ["which", "claude"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    found = result.stdout.strip()
                    GLib.idle_add(self._cli_path.set_text, found)
                    GLib.idle_add(
                        self._cli_test_row.set_subtitle, f"{_('Gefunden')}: {found}",
                    )
                    return
            except Exception as e:
                logger.warning(f"Claude CLI Suche fehlgeschlagen: {e}")
            GLib.idle_add(
                self._cli_test_row.set_subtitle, _("Claude CLI nicht gefunden"),
            )

        threading.Thread(target=worker, daemon=True).start()

    # ── Profil-Verwaltung ──

    def _on_add_profile(self, button: Gtk.Button) -> None:
        """Neues Profil erstellen."""
        profile = ConnectionProfile(name=_("Neues Profil"), is_default=False)
        self.config_manager.config.connection_profiles.append(profile)
        self.config_manager.save()
        self._refresh_profiles()

    def _on_edit_profile(self, button: Gtk.Button) -> None:
        """Profil bearbeiten (oeffnet Editor-Dialog)."""
        idx = self._profile_combo.get_selected()
        profiles = self.config_manager.config.connection_profiles
        if 0 <= idx < len(profiles):
            self._show_profile_editor(profiles[idx], idx)

    def _on_delete_profile(self, button: Gtk.Button) -> None:
        """Profil löschen."""
        idx = self._profile_combo.get_selected()
        profiles = self.config_manager.config.connection_profiles
        if 0 <= idx < len(profiles):
            profiles.pop(idx)
            self.config_manager.save()
            self._refresh_profiles()

    def _refresh_profiles(self) -> None:
        """Profil-ComboBox aktualisieren."""
        profiles = self.config_manager.config.connection_profiles
        profile_list = Gtk.StringList()
        self._profile_names = []
        for p in profiles:
            label = f"{p.name} ({p.host}:{p.port})"
            if p.use_ssh:
                label += f" [{_('SSH')}]"
            if p.is_default:
                label += f" [{_('Standard')}]"
            profile_list.append(label)
            self._profile_names.append(p.name)
        if not profiles:
            profile_list.append(_("Kein Profil"))
        self._profile_combo.set_model(profile_list)

    def _show_profile_editor(self, profile: ConnectionProfile, idx: int) -> None:
        """Profil-Editor Dialog anzeigen."""
        dialog = Adw.Dialog()
        dialog.set_title(_("Profil bearbeiten"))
        dialog.set_content_width(500)
        dialog.set_content_height(600)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        dialog.set_child(box)

        # Scrollable content
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        box.append(scrolled)

        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scrolled.set_child(form)

        group = Adw.PreferencesGroup(title=_("Verbindung"))
        form.append(group)

        name_entry = Adw.EntryRow(title=_("Name"))
        name_entry.set_text(profile.name)
        group.add(name_entry)

        host_entry = Adw.EntryRow(title=_("Host"))
        host_entry.set_text(profile.host)
        group.add(host_entry)

        port_spin = Adw.SpinRow.new_with_range(1024, 65535, 1)
        port_spin.set_title("Port")
        port_spin.set_value(profile.port)
        group.add(port_spin)

        https_switch = Adw.SwitchRow(title=_("HTTPS"))
        https_switch.set_active(profile.use_https)
        group.add(https_switch)

        user_entry = Adw.EntryRow(title=_("Benutzername"))
        user_entry.set_text(profile.username)
        group.add(user_entry)

        default_switch = Adw.SwitchRow(title=_("Standard-Profil"))
        default_switch.set_active(profile.is_default)
        group.add(default_switch)

        # SSH-Gruppe
        ssh_group = Adw.PreferencesGroup(title=_("SSH-Tunnel"))
        form.append(ssh_group)

        ssh_switch = Adw.SwitchRow(
            title=_("SSH verwenden"),
            subtitle=_("Verbindung ueber SSH-Tunnel aufbauen"),
        )
        ssh_switch.set_active(profile.use_ssh)
        ssh_group.add(ssh_switch)

        # SSH-Detail-Felder (nur sichtbar wenn SSH aktiv)
        ssh_details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        ssh_details.set_visible(profile.use_ssh)

        ssh_detail_group = Adw.PreferencesGroup()
        ssh_details.append(ssh_detail_group)

        ssh_user = Adw.EntryRow(title=_("SSH-Benutzer"))
        ssh_user.set_text(profile.ssh_user)
        ssh_detail_group.add(ssh_user)

        ssh_host = Adw.EntryRow(title=_("SSH-Host"))
        ssh_host.set_text(profile.ssh_host)
        ssh_detail_group.add(ssh_host)

        ssh_port = Adw.SpinRow.new_with_range(1, 65535, 1)
        ssh_port.set_title(_("SSH-Port"))
        ssh_port.set_value(profile.ssh_port)
        ssh_detail_group.add(ssh_port)

        # SSH-Key with file chooser
        ssh_key_row = Adw.ActionRow(title=_("SSH-Key-Pfad"))
        ssh_key = Gtk.Entry(
            hexpand=True,
            text=profile.ssh_key_path,
            placeholder_text="~/.ssh/id_ed25519",
        )
        ssh_key_row.add_suffix(ssh_key)
        key_browse_btn = Gtk.Button(icon_name="document-open-symbolic")
        key_browse_btn.set_tooltip_text(_("SSH-Key-Datei wählen"))
        key_browse_btn.set_valign(Gtk.Align.CENTER)

        def on_browse_key(_btn):
            file_dialog = Gtk.FileDialog()
            file_dialog.set_title(_("SSH-Key wählen"))
            from pathlib import Path
            ssh_dir = Path.home() / ".ssh"
            if ssh_dir.exists():
                from gi.repository import Gio
                file_dialog.set_initial_folder(Gio.File.new_for_path(str(ssh_dir)))

            def on_chosen(d, result):
                try:
                    f = d.open_finish(result)
                    if f:
                        ssh_key.set_text(f.get_path())
                except GLib.Error:
                    pass

            file_dialog.open(dialog, None, on_chosen)

        key_browse_btn.connect("clicked", on_browse_key)
        ssh_key_row.add_suffix(key_browse_btn)
        ssh_detail_group.add(ssh_key_row)

        form.append(ssh_details)

        # SSH-Switch controls visibility
        def on_ssh_toggled(switch, _pspec):
            ssh_details.set_visible(switch.get_active())

        ssh_switch.connect("notify::active", on_ssh_toggled)

        # Test connection button
        test_group = Adw.PreferencesGroup(title=_("Verbindungstest"))
        form.append(test_group)

        self._profile_test_row = Adw.ActionRow(
            title=_("Verbindung testen"),
            subtitle=_("Prüft ob der Server über dieses Profil erreichbar ist"),
        )
        test_spinner = Gtk.Spinner()
        test_spinner.set_visible(False)
        self._profile_test_row.add_suffix(test_spinner)

        test_btn = Gtk.Button(icon_name="network-transmit-receive-symbolic")
        test_btn.set_tooltip_text(_("Testen"))
        test_btn.set_valign(Gtk.Align.CENTER)

        def on_test_profile(_btn):
            test_btn.set_sensitive(False)
            test_spinner.set_visible(True)
            test_spinner.start()
            self._profile_test_row.set_subtitle(_("Teste..."))

            def test_worker():
                try:
                    from lotto_analyzer.client.api_client import APIClient
                    from lotto_common.models.ai_config import ServerConfig

                    h = host_entry.get_text().strip() or "localhost"
                    p = int(port_spin.get_value())
                    use_s = ssh_switch.get_active()

                    if use_s and ssh_user.get_text().strip():
                        from lotto_analyzer.client.ssh_tunnel import SSHTunnel
                        local_p = p + 1000
                        tunnel = SSHTunnel(
                            ssh_host=ssh_host.get_text().strip() or h,
                            ssh_user=ssh_user.get_text().strip(),
                            remote_port=p,
                            local_port=local_p,
                            ssh_port=int(ssh_port.get_value()),
                            ssh_key_path=ssh_key.get_text().strip(),
                        )
                        if tunnel.start():
                            sc = ServerConfig(host="127.0.0.1", port=local_p, use_https=False)
                            c = APIClient(sc)
                            ok, msg = c.test_connection()
                            c.close()
                            tunnel.stop()
                        else:
                            ok, msg = False, _("SSH-Tunnel fehlgeschlagen")
                    else:
                        sc = ServerConfig(
                            host=h, port=p,
                            use_https=https_switch.get_active(),
                        )
                        c = APIClient(sc)
                        ok, msg = c.test_connection()
                        c.close()
                except Exception as e:
                    ok, msg = False, str(e)

                def done():
                    test_spinner.stop()
                    test_spinner.set_visible(False)
                    test_btn.set_sensitive(True)
                    if ok:
                        self._profile_test_row.set_subtitle(f"✓ {msg}")
                    else:
                        self._profile_test_row.set_subtitle(f"✗ {msg}")
                    return False

                GLib.idle_add(done)

            threading.Thread(target=test_worker, daemon=True).start()

        test_btn.connect("clicked", on_test_profile)
        self._profile_test_row.add_suffix(test_btn)
        test_group.add(self._profile_test_row)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                          halign=Gtk.Align.END)

        cancel_btn = Gtk.Button(label=_("Abbrechen"))
        cancel_btn.set_tooltip_text(_("Änderungen verwerfen"))
        cancel_btn.connect("clicked", lambda _btn: dialog.close())
        btn_box.append(cancel_btn)

        save_btn = Gtk.Button(label=_("Speichern"))
        save_btn.set_tooltip_text(_("Profil-Konfiguration speichern"))
        save_btn.add_css_class("suggested-action")

        def on_save(_btn):
            profile.name = name_entry.get_text()
            profile.host = host_entry.get_text()
            profile.port = int(port_spin.get_value())
            profile.use_https = https_switch.get_active()
            profile.username = user_entry.get_text()
            profile.use_ssh = ssh_switch.get_active()
            if ssh_switch.get_active():
                profile.ssh_user = ssh_user.get_text()
                profile.ssh_host = ssh_host.get_text()
                profile.ssh_port = int(ssh_port.get_value())
                # ssh_key is a Gtk.Entry (inside ActionRow), not Adw.EntryRow
                profile.ssh_key_path = ssh_key.get_text()
            else:
                profile.ssh_user = ""
                profile.ssh_host = ""
                profile.ssh_key_path = ""
            if default_switch.get_active():
                for p in self.config_manager.config.connection_profiles:
                    p.is_default = False
            profile.is_default = default_switch.get_active()
            self.config_manager.save()
            self._refresh_profiles()
            dialog.close()

        save_btn.connect("clicked", on_save)
        btn_box.append(save_btn)
        box.append(btn_box)

        # Dialog zeigen
        window = self.get_root()
        if window:
            dialog.present(window)
