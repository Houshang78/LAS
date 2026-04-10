"""Settings: User management section (Admin/Owner only)."""

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("settings.part4")

# Field permission rules per the user management table
FIELD_RULES = {
    "system_id":    {"editable_by": [],               "approval": None,    "label": _("System-ID"), "immutable": True},
    "username":     {"editable_by": [],               "approval": None,    "label": "Username"},
    "email":        {"editable_by": ["user"],          "approval": "admin", "label": "Email"},
    "telefon":      {"editable_by": ["user"],          "approval": "admin", "label": _("Telefon")},
    "vorname":      {"editable_by": ["user"],          "approval": "admin", "label": _("Vorname")},
    "mittelname":   {"editable_by": ["user"],          "approval": "admin", "label": _("Mittelname")},
    "nachname":     {"editable_by": ["user"],          "approval": "admin", "label": _("Nachname")},
    "adresse":      {"editable_by": ["user"],          "approval": "admin", "label": _("Adresse")},
    "foto_path":    {"editable_by": ["user"],          "approval": "admin", "label": _("Foto")},
    "telegram_id":  {"editable_by": ["admin", "owner"], "approval": None,  "label": "Telegram-ID"},
    "ausweis_id":   {"editable_by": ["owner"],         "approval": None,   "label": _("Ausweis-ID (amtlich)")},
    "ausweis_path": {"editable_by": [],               "approval": "owner", "label": _("Ausweis-Abbild"), "one_time": True},
    "role":         {"editable_by": ["owner"],         "approval": None,    "label": _("Rolle")},
}


class Part4Mixin:
    """User management for Admin/Owner in Settings."""

    def _build_user_management_section(self, content: Gtk.Box) -> None:
        """Build user management section (only visible for admin/owner)."""
        self._user_mgmt_group = Adw.PreferencesGroup(
            title=_("Benutzerverwaltung"),
            description=_("Profile anzeigen und bearbeiten (Admin/Owner)"),
        )
        self._user_mgmt_group.set_visible(False)
        content.append(self._user_mgmt_group)

        # Refresh button
        refresh_row = Adw.ActionRow(title=_("Benutzer laden"))
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_valign(Gtk.Align.CENTER)
        refresh_btn.connect("clicked", self._on_load_users)
        refresh_row.add_suffix(refresh_btn)
        self._user_mgmt_group.add(refresh_row)

        # User buttons container
        self._user_buttons_box = Gtk.FlowBox()
        self._user_buttons_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._user_buttons_box.set_homogeneous(True)
        self._user_buttons_box.set_max_children_per_line(4)
        self._user_buttons_box.set_min_children_per_line(2)
        self._user_buttons_box.set_row_spacing(8)
        self._user_buttons_box.set_column_spacing(8)
        self._user_buttons_box.set_margin_top(8)
        self._user_mgmt_group.add(self._user_buttons_box)

        # Change requests section
        self._changes_group = Adw.PreferencesGroup(
            title=_("Änderungsanfragen"),
            description=_("Ausstehende Profil-Änderungen von Benutzern"),
        )
        self._changes_group.set_visible(False)
        content.append(self._changes_group)
        self._change_rows: list = []

        # Telegram notification permissions section
        self._tg_perms_group = Adw.PreferencesGroup(
            title=_("Telegram-Benachrichtigungen"),
            description=_("Pro Benutzer festlegen wer welche Nachrichten erhält. Owner bekommt immer alles."),
        )
        self._tg_perms_group.set_visible(False)
        content.append(self._tg_perms_group)
        self._tg_perms_rows: list = []

    def _show_user_management(self, role: str) -> None:
        """Show/hide user management based on role."""
        is_admin = role in ("admin", "owner")
        self._user_mgmt_group.set_visible(is_admin)
        self._changes_group.set_visible(is_admin)
        self._tg_perms_group.set_visible(is_admin)
        if is_admin:
            self._on_load_users(None)

    def _on_load_users(self, _btn) -> None:
        """Load all users + changes + telegram permissions from server."""
        if not self.api_client:
            return

        def worker():
            try:
                users = self.api_client.list_users()
                changes = self.api_client.get_change_requests(status="pending")
            except Exception as e:
                logger.warning(f"Users/changes load failed: {e}")
                users, changes = [], []
            try:
                tg_data = self.api_client.get_telegram_permissions()
            except Exception as e:
                logger.warning(f"Telegram permissions load failed: {e}")
                tg_data = {}
            GLib.idle_add(self._on_users_loaded, users, changes)
            GLib.idle_add(self._on_tg_perms_loaded, tg_data)

        threading.Thread(target=worker, daemon=True).start()

    def _on_users_loaded(self, users: list, changes: list) -> bool:
        # Clear old buttons
        child = self._user_buttons_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._user_buttons_box.remove(child)
            child = next_child

        # Create user buttons
        for user in users:
            username = user.get("username", "?")
            role = user.get("role", "user")
            is_active = user.get("is_active", True)

            btn = Gtk.Button()
            btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            btn_box.set_margin_top(8)
            btn_box.set_margin_bottom(8)

            avatar = Adw.Avatar(size=32, text=username, show_initials=True)
            btn_box.append(avatar)

            name_lbl = Gtk.Label(label=username)
            name_lbl.add_css_class("heading")
            btn_box.append(name_lbl)

            role_lbl = Gtk.Label(label=role.capitalize())
            role_lbl.add_css_class("dim-label")
            role_lbl.add_css_class("caption")
            btn_box.append(role_lbl)

            btn.set_child(btn_box)
            if not is_active:
                btn.add_css_class("dim-label")
            btn.connect("clicked", self._on_user_clicked, user)
            self._user_buttons_box.append(btn)

        # Change requests
        while self._change_rows:
            self._changes_group.remove(self._change_rows.pop())

        for change in changes:
            uid = change.get("user_id", "?")
            field = change.get("field_name", "?")
            old_val = change.get("old_value", "")
            new_val = change.get("new_value", "")
            created = str(change.get("created_at", ""))[:16]
            change_id = change.get("id")

            row = Adw.ActionRow(
                title=f"User #{uid}: {field}",
                subtitle=f"{old_val} → {new_val} ({created})",
            )

            approve_btn = Gtk.Button(icon_name="emblem-ok-symbolic")
            approve_btn.add_css_class("success")
            approve_btn.set_valign(Gtk.Align.CENTER)
            approve_btn.set_tooltip_text(_("Genehmigen"))
            approve_btn.connect("clicked", self._on_review_change, change_id, True)
            row.add_suffix(approve_btn)

            reject_btn = Gtk.Button(icon_name="window-close-symbolic")
            reject_btn.add_css_class("error")
            reject_btn.set_valign(Gtk.Align.CENTER)
            reject_btn.set_tooltip_text(_("Ablehnen"))
            reject_btn.connect("clicked", self._on_review_change, change_id, False)
            row.add_suffix(reject_btn)

            self._changes_group.add(row)
            self._change_rows.append(row)

        if not changes:
            row = Adw.ActionRow(title=_("Keine ausstehenden Änderungen"))
            self._changes_group.add(row)
            self._change_rows.append(row)

        return False

    def _on_review_change(self, _btn, change_id: int, approved: bool) -> None:
        """Approve or reject a change request."""
        _btn.set_sensitive(False)

        def worker():
            try:
                self.api_client.review_change_request(change_id, approved)
            except Exception as e:
                logger.warning(f"Change review failed: {e}")
            GLib.idle_add(self._on_load_users, None)

        threading.Thread(target=worker, daemon=True).start()

    def _on_tg_perms_loaded(self, tg_data: dict) -> bool:
        """Build telegram notification permission checkboxes per user."""
        while self._tg_perms_rows:
            self._tg_perms_group.remove(self._tg_perms_rows.pop())

        tg_users = tg_data.get("users", [])
        ntypes = tg_data.get("notification_types", [])

        # Notification type labels
        type_labels = {
            "crawl_result": _("Neue Ziehung"),
            "kaufempfehlung": _("Kaufempfehlung"),
            "vergleich": _("Vergleichsbericht"),
            "zyklus_bericht": _("Zyklus-Bericht"),
            "ml_training": _("ML-Training"),
            "system_status": _("System-Status"),
            "self_improvement": _("Self-Improvement"),
        }

        if not tg_users:
            row = Adw.ActionRow(title=_("Keine Benutzer mit Telegram-ID"))
            self._tg_perms_group.add(row)
            self._tg_perms_rows.append(row)
            return False

        for tu in tg_users:
            uid = tu["id"]
            username = tu.get("username", "?")
            is_owner = tu.get("is_owner", False)
            perms = tu.get("permissions", {})

            # Expander per user
            expander = Adw.ExpanderRow(
                title=f"{'👑 ' if is_owner else ''}{username}",
                subtitle=f"Telegram: {tu.get('telegram_id', '?')}"
                + (" — " + _("Alle Nachrichten (Owner)") if is_owner else ""),
            )
            self._tg_perms_group.add(expander)
            self._tg_perms_rows.append(expander)

            for nt in ntypes:
                label = type_labels.get(nt, nt)
                sw = Adw.SwitchRow(title=label)
                if is_owner:
                    # Owner always on, not changeable
                    sw.set_active(True)
                    sw.set_sensitive(False)
                else:
                    sw.set_active(perms.get(nt, False))

                    def on_toggled(switch, _pspec, _uid=uid, _nt=nt):
                        enabled = switch.get_active()
                        def save():
                            try:
                                self.api_client.set_user_telegram_permissions(
                                    _uid, {_nt: enabled},
                                )
                            except Exception as e:
                                logger.warning(f"Telegram perm save failed: {e}")
                        threading.Thread(target=save, daemon=True).start()

                    sw.connect("notify::active", on_toggled)
                expander.add_row(sw)

        return False

    def _on_user_clicked(self, _btn, user: dict) -> None:
        """Open profile editor dialog for a user."""
        self._show_user_profile_dialog(user)

    def _show_user_profile_dialog(self, user: dict) -> None:
        """Show profile editor dialog with field-level permissions."""
        user_id = user.get("id", 0)
        username = user.get("username", "?")
        target_role = user.get("role", "user")

        # Determine viewer's privilege level
        viewer_role = "user"
        if hasattr(self, "_user_role") and self._user_role:
            viewer_role = self._user_role
        is_owner = viewer_role == "owner"
        # Admin+ = admin with trusted_admin_id set by owner (privileged admin)
        is_admin_plus = (
            viewer_role == "admin"
            and hasattr(self, "_viewer_user_id")
            and self._viewer_user_id
            and user.get("trusted_admin_id") == self._viewer_user_id
        )
        is_privileged = is_owner or is_admin_plus

        dialog = Adw.Dialog()
        dialog.set_title(f"{_('Profil')}: {username}")
        dialog.set_content_width(520)
        dialog.set_content_height(700)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        dialog.set_child(box)

        # Header with avatar
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.set_halign(Gtk.Align.CENTER)
        avatar = Adw.Avatar(size=64, text=username, show_initials=True)
        header.append(avatar)
        header_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header_info.set_valign(Gtk.Align.CENTER)
        name_lbl = Gtk.Label(label=username)
        name_lbl.add_css_class("title-2")
        header_info.append(name_lbl)
        role_lbl = Gtk.Label(label=f"{target_role.capitalize()} (ID: {user_id})")
        role_lbl.add_css_class("dim-label")
        header_info.append(role_lbl)
        header.append(header_info)
        box.append(header)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        box.append(scroll)
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroll.set_child(form)

        # Build fields based on permission rules
        group = Adw.PreferencesGroup(title=_("Profil-Daten"))
        form.append(group)

        field_entries = {}
        for field_name, rules in FIELD_RULES.items():
            current_value = str(user.get(field_name, "") or "")
            label = rules["label"]
            one_time = rules.get("one_time", False)

            # Determine if this field is editable by the viewer
            immutable = rules.get("immutable", False)
            can_edit = False

            if immutable:
                can_edit = False  # Never editable (system_id)
            elif is_owner:
                # Owner can edit everything except immutable
                can_edit = True
            elif is_privileged:
                # Admin+ can edit: username, telegram_id, role, + normal admin fields
                can_edit = field_name in (
                    "username", "telegram_id", "role",
                    "email", "telefon", "vorname", "mittelname", "nachname",
                    "adresse", "foto_path",
                )
                if one_time and current_value:
                    can_edit = field_name not in ("ausweis_path",)
            elif viewer_role == "admin":
                can_edit = field_name in (
                    "email", "telefon", "vorname", "mittelname", "nachname",
                    "adresse", "foto_path", "telegram_id",
                )
                if one_time and current_value:
                    can_edit = False
            if one_time and current_value and not is_privileged and not is_owner:
                can_edit = False

            row = Adw.EntryRow(title=label)
            row.set_text(current_value)
            row.set_editable(can_edit)
            if not can_edit:
                row.add_css_class("dim-label")
            group.add(row)
            field_entries[field_name] = row

        # Permissions: editable for owner/admin+, read-only otherwise
        perms = user.get("permissions", [])
        if isinstance(perms, str):
            import json
            try:
                perms = json.loads(perms)
            except Exception:
                perms = []

        perm_group = Adw.PreferencesGroup(title=_("Berechtigungen"))
        form.append(perm_group)
        perm_switches = {}

        if is_privileged:
            # Editable permission checkboxes
            from lotto_common.models.user import ALL_PERMISSIONS
            for perm in ALL_PERMISSIONS:
                sw = Adw.SwitchRow(title=perm)
                sw.set_active(perm in perms)
                perm_group.add(sw)
                perm_switches[perm] = sw
        elif perms:
            perm_row = Adw.ActionRow(
                title=", ".join(perms[:10]),
                subtitle=f"{len(perms)} {_('Berechtigungen')}",
            )
            perm_group.add(perm_row)

        # Status info
        info_group = Adw.PreferencesGroup(title=_("Status"))
        form.append(info_group)

        active_row = Adw.ActionRow(
            title=_("Aktiv"),
            subtitle="✓" if user.get("is_active") else "✗",
        )
        info_group.add(active_row)

        last_login = user.get("last_login", "")
        if last_login:
            login_row = Adw.ActionRow(
                title=_("Letzter Login"),
                subtitle=str(last_login)[:16],
            )
            info_group.add(login_row)

        created = user.get("created_at", "")
        if created:
            created_row = Adw.ActionRow(
                title=_("Erstellt"),
                subtitle=str(created)[:16],
            )
            info_group.add(created_row)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                          halign=Gtk.Align.END)
        box.append(btn_box)

        cancel_btn = Gtk.Button(label=_("Schließen"))
        cancel_btn.connect("clicked", lambda _: dialog.close())
        btn_box.append(cancel_btn)

        save_btn = Gtk.Button(label=_("Speichern"))
        save_btn.add_css_class("suggested-action")

        def on_save(_btn):
            changes = {}
            for field_name, entry in field_entries.items():
                if not entry.get_editable():
                    continue
                new_val = entry.get_text().strip()
                old_val = str(user.get(field_name, "") or "")
                if new_val != old_val:
                    changes[field_name] = new_val

            # Collect permission changes (owner/admin+ only)
            new_perms = None
            if perm_switches:
                new_perms = [p for p, sw in perm_switches.items() if sw.get_active()]
                if set(new_perms) == set(perms):
                    new_perms = None  # No change

            if not changes and new_perms is None:
                dialog.close()
                return

            save_btn.set_sensitive(False)

            def save_worker():
                try:
                    update_kwargs = dict(changes)
                    if new_perms is not None:
                        update_kwargs["permissions"] = new_perms
                    if update_kwargs:
                        self.api_client.update_user(user_id, **update_kwargs)
                except Exception as e:
                    logger.warning(f"Profile update failed: {e}")
                GLib.idle_add(dialog.close)
                GLib.idle_add(self._on_load_users, None)

            threading.Thread(target=save_worker, daemon=True).start()

        save_btn.connect("clicked", on_save)
        btn_box.append(save_btn)

        window = self.get_root()
        if window:
            dialog.present(window)
