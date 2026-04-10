"""Connection error dialog with SSH/HTTPS toggle and profile selection."""

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib

from lotto_common.i18n import _
from lotto_common.models.user import ConnectionProfile
from lotto_common.utils.logging_config import get_logger

logger = get_logger("connection_dialog")


class ConnectionErrorDialog(Adw.Dialog):
    """Dialog for failed server connections.

    Shows error message, allows editing connection parameters
    (Host/Port/SSH/HTTPS), profile selection, and retry.
    """

    def __init__(self, config_manager, error_message: str, on_connected=None):
        super().__init__()
        self.set_title(_("Verbindung fehlgeschlagen"))
        self.set_content_width(480)
        self.set_content_height(580)

        self._config_manager = config_manager
        self._on_connected = on_connected
        self._profiles = config_manager.config.connection_profiles
        self._build_ui(error_message)

    def _build_ui(self, error_message: str) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)
        self.set_child(box)

        # Error banner
        self._error_label = Gtk.Label(label=error_message)
        self._error_label.add_css_class("error")
        self._error_label.set_wrap(True)
        self._error_label.set_selectable(True)
        self._error_label.set_xalign(0)
        box.append(self._error_label)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        box.append(scroll)
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroll.set_child(form)

        # Profile selector (if profiles exist)
        if self._profiles:
            profile_group = Adw.PreferencesGroup(title=_("Profil"))
            form.append(profile_group)

            profile_list = Gtk.StringList()
            profile_list.append(_("— Manuell —"))
            for p in self._profiles:
                lbl = f"{p.name} ({p.host}:{p.port})"
                if p.use_ssh:
                    lbl += " [SSH]"
                profile_list.append(lbl)

            self._profile_combo = Adw.ComboRow(title=_("Profil wählen"))
            self._profile_combo.set_model(profile_list)

            # Pre-select default profile
            default_idx = 0
            for i, p in enumerate(self._profiles):
                if p.is_default:
                    default_idx = i + 1
                    break
            self._profile_combo.set_selected(default_idx)
            self._profile_combo.connect("notify::selected", self._on_profile_changed)
            profile_group.add(self._profile_combo)
        else:
            self._profile_combo = None

        # Connection fields
        conn_group = Adw.PreferencesGroup(title=_("Verbindung"))
        form.append(conn_group)

        config = self._config_manager.config

        self._host_entry = Adw.EntryRow(title="Host")
        self._host_entry.set_text(config.server.host)
        conn_group.add(self._host_entry)

        self._port_entry = Adw.EntryRow(title="Port")
        self._port_entry.set_text(str(config.server.port))
        self._port_entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        conn_group.add(self._port_entry)

        self._https_switch = Adw.SwitchRow(
            title="HTTPS",
            subtitle=_("Verschlüsselte Verbindung"),
        )
        self._https_switch.set_active(config.server.use_https)
        conn_group.add(self._https_switch)

        # SSH-Tunnel section
        ssh_group = Adw.PreferencesGroup(title=_("SSH-Tunnel"))
        form.append(ssh_group)

        self._ssh_switch = Adw.SwitchRow(
            title=_("SSH verwenden"),
            subtitle=_("Verbindung über SSH-Tunnel aufbauen"),
        )
        ssh_user = getattr(config.server, "ssh_user", "")
        self._ssh_switch.set_active(bool(ssh_user))
        ssh_group.add(self._ssh_switch)

        # SSH detail fields
        self._ssh_details = Adw.PreferencesGroup()
        self._ssh_details.set_visible(bool(ssh_user))
        form.append(self._ssh_details)

        self._ssh_user_entry = Adw.EntryRow(title=_("SSH-Benutzer"))
        self._ssh_user_entry.set_text(ssh_user)
        self._ssh_details.add(self._ssh_user_entry)

        self._ssh_host_entry = Adw.EntryRow(title=_("SSH-Host"))
        self._ssh_host_entry.set_text(getattr(config.server, "ssh_host", ""))
        self._ssh_details.add(self._ssh_host_entry)

        self._ssh_port_entry = Adw.EntryRow(title=_("SSH-Port"))
        self._ssh_port_entry.set_text(str(getattr(config.server, "ssh_port", 22)))
        self._ssh_port_entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        self._ssh_details.add(self._ssh_port_entry)

        # SSH-Key with file chooser
        key_row = Adw.ActionRow(title=_("SSH-Key"))
        self._ssh_key_entry = Gtk.Entry(
            hexpand=True,
            text=getattr(config.server, "ssh_key_path", ""),
            placeholder_text="~/.ssh/id_ed25519",
        )
        key_row.add_suffix(self._ssh_key_entry)
        browse_btn = Gtk.Button(icon_name="document-open-symbolic")
        browse_btn.set_tooltip_text(_("SSH-Key-Datei wählen"))
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.connect("clicked", self._on_browse_ssh_key)
        key_row.add_suffix(browse_btn)
        self._ssh_details.add(key_row)

        self._ssh_switch.connect("notify::active", self._on_ssh_toggled)

        # Populate from default profile if available
        if self._profile_combo and default_idx > 0:
            self._apply_profile(self._profiles[default_idx - 1])

        # Status spinner
        self._status_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
            halign=Gtk.Align.CENTER,
        )
        self._status_box.set_visible(False)
        box.append(self._status_box)

        self._spinner = Gtk.Spinner()
        self._status_box.append(self._spinner)
        self._status_label = Gtk.Label(label=_("Verbindungstest..."))
        self._status_label.add_css_class("dim-label")
        self._status_box.append(self._status_label)

        # Buttons
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12, halign=Gtk.Align.CENTER,
        )
        box.append(btn_box)

        cancel_btn = Gtk.Button(label=_("Abbrechen"))
        cancel_btn.connect("clicked", lambda _: self.close())
        btn_box.append(cancel_btn)

        save_btn = Gtk.Button(label=_("Speichern"))
        save_btn.set_tooltip_text(_("Verbindungseinstellungen speichern"))
        save_btn.connect("clicked", self._on_save)
        btn_box.append(save_btn)

        self._retry_btn = Gtk.Button(label=_("Verbinden"))
        self._retry_btn.add_css_class("suggested-action")
        self._retry_btn.connect("clicked", self._on_retry)
        btn_box.append(self._retry_btn)

    # -- Profile handling --

    def _on_profile_changed(self, combo, _pspec) -> None:
        idx = combo.get_selected()
        if idx > 0 and (idx - 1) < len(self._profiles):
            self._apply_profile(self._profiles[idx - 1])

    def _apply_profile(self, p: ConnectionProfile) -> None:
        """Fill form fields from a connection profile."""
        self._host_entry.set_text(p.host)
        self._port_entry.set_text(str(p.port))
        self._https_switch.set_active(p.use_https)
        self._ssh_switch.set_active(p.use_ssh)
        self._ssh_user_entry.set_text(p.ssh_user)
        self._ssh_host_entry.set_text(p.ssh_host)
        self._ssh_port_entry.set_text(str(p.ssh_port))
        self._ssh_key_entry.set_text(p.ssh_key_path)

    def _on_ssh_toggled(self, switch, _pspec) -> None:
        self._ssh_details.set_visible(switch.get_active())

    def _on_browse_ssh_key(self, _btn) -> None:
        """Open file chooser for SSH key."""
        dialog = Gtk.FileDialog()
        dialog.set_title(_("SSH-Key wählen"))

        from pathlib import Path
        ssh_dir = Path.home() / ".ssh"
        if ssh_dir.exists():
            dialog.set_initial_folder(Gio.File.new_for_path(str(ssh_dir)))

        dialog.open(self.get_root(), None, self._on_key_file_chosen)

    def _on_key_file_chosen(self, dialog, result) -> None:
        try:
            f = dialog.open_finish(result)
            if f:
                self._ssh_key_entry.set_text(f.get_path())
        except GLib.Error:
            pass

    # -- Save / Retry --

    def _read_fields(self) -> dict:
        """Read all form fields into a dict."""
        host = self._host_entry.get_text().strip() or "localhost"
        try:
            port = int(self._port_entry.get_text().strip())
        except ValueError:
            port = 8049
        try:
            ssh_port = int(self._ssh_port_entry.get_text().strip())
        except ValueError:
            ssh_port = 22

        return {
            "host": host,
            "port": port,
            "use_https": self._https_switch.get_active(),
            "use_ssh": self._ssh_switch.get_active(),
            "ssh_user": self._ssh_user_entry.get_text().strip(),
            "ssh_host": self._ssh_host_entry.get_text().strip(),
            "ssh_port": ssh_port,
            "ssh_key_path": self._ssh_key_entry.get_text().strip(),
        }

    def _save_config(self, fields: dict) -> None:
        """Persist connection fields to config."""
        config = self._config_manager.config
        config.server.host = fields["host"]
        config.server.port = fields["port"]
        config.server.use_https = fields["use_https"]
        if hasattr(config.server, "ssh_user"):
            config.server.ssh_user = fields["ssh_user"]
        if hasattr(config.server, "ssh_host"):
            config.server.ssh_host = fields["ssh_host"]
        if hasattr(config.server, "ssh_port"):
            config.server.ssh_port = fields["ssh_port"]
        if hasattr(config.server, "ssh_key_path"):
            config.server.ssh_key_path = fields["ssh_key_path"]
        self._config_manager.save()
        logger.info(
            f"Connection config saved: {fields['host']}:{fields['port']} "
            f"SSH={fields['use_ssh']}"
        )

    def _on_save(self, _btn) -> None:
        self._save_config(self._read_fields())
        self.close()

    def _on_retry(self, _btn) -> None:
        """Save config + attempt connection (SSH or direct)."""
        fields = self._read_fields()
        self._save_config(fields)

        self._retry_btn.set_sensitive(False)
        self._error_label.set_visible(False)
        self._status_box.set_visible(True)
        self._spinner.start()
        self._status_label.set_label(_("Verbindungstest..."))

        def worker():
            client = None
            ok, msg = False, ""
            try:
                from lotto_analyzer.client.api_client import APIClient
                from lotto_common.models.ai_config import ServerConfig

                api_key = self._config_manager.config.server.api_key

                # SSH-Tunnel first if enabled
                if fields["use_ssh"] and fields["ssh_user"]:
                    ok, msg, client = self._try_ssh_connect(fields, api_key)

                # Direct connection (try configured protocol, fallback to other)
                if not client:
                    for try_https in [fields["use_https"], not fields["use_https"]]:
                        sc = ServerConfig(
                            host=fields["host"], port=fields["port"],
                            api_key=api_key, use_https=try_https,
                        )
                        c = APIClient(sc)
                        ok, msg = c.test_connection()
                        if ok:
                            client = c
                            break
                        c.close()
                    else:
                        c.close()

            except Exception as e:
                ok, msg = False, str(e)
            GLib.idle_add(self._on_retry_result, ok, msg, client)

        threading.Thread(target=worker, daemon=True).start()

    def _try_ssh_connect(self, fields: dict, api_key: str):
        """Attempt SSH tunnel connection. Returns (ok, msg, client)."""
        from lotto_analyzer.client.ssh_tunnel import SSHTunnel
        from lotto_analyzer.client.api_client import APIClient
        from lotto_common.models.ai_config import ServerConfig

        local_port = fields["port"] + 1000
        tunnel = SSHTunnel(
            ssh_host=fields["ssh_host"] or fields["host"],
            ssh_user=fields["ssh_user"],
            remote_port=fields["port"],
            local_port=local_port,
            ssh_port=fields["ssh_port"],
            ssh_key_path=fields["ssh_key_path"],
        )

        if not tunnel.start():
            tunnel.stop()
            return False, _("SSH-Tunnel konnte nicht gestartet werden"), None

        sc = ServerConfig(
            host="127.0.0.1", port=local_port,
            api_key=api_key, use_https=False,
        )
        c = APIClient(sc)
        ok, msg = c.test_connection()
        if ok:
            # Store tunnel reference on the app for cleanup
            logger.info(f"SSH tunnel established: localhost:{local_port}")
            return True, msg, c
        tunnel.stop()
        c.close()
        return False, msg, None

    def _on_retry_result(self, ok: bool, msg: str, client) -> bool:
        self._spinner.stop()
        self._status_box.set_visible(False)
        self._retry_btn.set_sensitive(True)

        if ok and client:
            logger.info(f"Connection established: {msg}")
            if self._on_connected:
                self._on_connected(client)
            self.close()
        else:
            self._error_label.set_text(msg)
            self._error_label.set_visible(True)
        return False
