"""Scraper-Seite: Crawl-Monitor Mixin (Part 4).

Sektionen:
1. Status-Übersicht (pro Ziehungstag)
2. Smart Timing (ML-gelernt)
3. Quellen-Zuverlässigkeit
4. Crawl-Einstellungen (editierbar)
5. Aktionen (Trigger, Reset)
6. Crawl-Historie (Tabelle)
"""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Pango

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("scraper.monitor")

_DAY_LABELS = {
    "saturday": "Sa (6aus49)",
    "wednesday": "Mi (6aus49)",
    "tuesday": "Di (EJ)",
    "friday": "Fr (EJ)",
}

_STATUS_ICONS = {
    "idle": "emblem-ok-symbolic",
    "crawling": "emblem-synchronizing-symbolic",
    "training": "system-run-symbolic",
}


class CrawlMonitorMixin:
    """Crawl-Monitor UI-Sektion für die Scraper-Seite."""

    def _build_crawl_monitor(self) -> None:
        """Build all 6 crawl monitor sections."""
        # Main expander for the whole monitor
        monitor_group = Adw.PreferencesGroup(
            title=_("Crawl-Monitor"),
            description=_("Automatische Crawl-Überwachung, Timing und Einstellungen"),
        )
        self._content.append(monitor_group)

        # 1. Status per draw day
        self._build_status_section(monitor_group)

        # 2. Smart Timing
        self._timing_group = Adw.PreferencesGroup(title=_("Smart Timing (ML)"))
        self._content.append(self._timing_group)
        self._timing_rows: dict[str, Adw.ActionRow] = {}

        # 3. Source reliability
        self._source_group = Adw.PreferencesGroup(title=_("Quellen-Zuverlässigkeit"))
        self._content.append(self._source_group)

        # 4. Schedule settings
        self._build_settings_section()

        # 5. Actions
        self._build_actions_section()

        # 6. History
        self._build_history_section()

        # Load data
        GLib.idle_add(self._load_crawl_monitor)

        # WS subscription for live updates
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.on("scheduler_status", self._on_ws_monitor_update)
            ui_ws_manager.on("draw_update", self._on_ws_monitor_update)
        except Exception:
            pass

    # ── Section 1: Status Overview ──

    def _build_status_section(self, group) -> None:
        """Per-day status rows."""
        self._day_rows: dict[str, Adw.ActionRow] = {}
        for day, label in _DAY_LABELS.items():
            row = Adw.ActionRow(title=label, subtitle=_("Lade..."))
            icon = Gtk.Image.new_from_icon_name("content-loading-symbolic")
            icon.set_pixel_size(16)
            row.add_prefix(icon)
            row._status_icon = icon
            group.add(row)
            self._day_rows[day] = row

        # Activity row
        self._activity_row = Adw.ActionRow(
            title=_("Aktivität"), subtitle="idle",
        )
        self._activity_row.add_prefix(
            Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        )
        group.add(self._activity_row)

    # ── Section 4: Settings ──

    def _build_settings_section(self) -> None:
        """Editable crawl schedule settings."""
        group = Adw.PreferencesGroup(
            title=_("Crawl-Einstellungen"),
            description=_("Zeiten, Retries und Toggles"),
        )
        self._content.append(group)

        # Toggles
        self._crawl_enabled_switch = Adw.SwitchRow(
            title=_("Auto-Crawl aktiv"),
        )
        self._crawl_enabled_switch.connect(
            "notify::active", self._on_setting_changed,
        )
        group.add(self._crawl_enabled_switch)

        self._smart_timing_switch = Adw.SwitchRow(
            title=_("Smart Timing (ML-gelernt)"),
            subtitle=_("Crawl-Zeiten automatisch optimieren"),
        )
        self._smart_timing_switch.connect(
            "notify::active", self._on_setting_changed,
        )
        group.add(self._smart_timing_switch)

        # Time settings per day
        self._time_spins: dict[str, tuple[Adw.SpinRow, Adw.SpinRow]] = {}
        for day, label in _DAY_LABELS.items():
            hour_row = Adw.SpinRow.new_with_range(18, 23, 1)
            hour_row.set_title(f"{label} — Stunde")
            hour_row.set_snap_to_ticks(True)
            group.add(hour_row)

            min_row = Adw.SpinRow.new_with_range(0, 59, 5)
            min_row.set_title(f"{label} — Minute")
            min_row.set_snap_to_ticks(True)
            group.add(min_row)

            self._time_spins[day] = (hour_row, min_row)

        # Retry settings
        self._retry_interval_spin = Adw.SpinRow.new_with_range(1, 6, 1)
        self._retry_interval_spin.set_title(_("Retry-Intervall (Stunden)"))
        group.add(self._retry_interval_spin)

        self._max_retries_spin = Adw.SpinRow.new_with_range(1, 20, 1)
        self._max_retries_spin.set_title(_("Max Retries"))
        group.add(self._max_retries_spin)

        # Save button
        save_btn = Gtk.Button(label=_("Einstellungen speichern"))
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save_settings)
        self.register_readonly_button(save_btn)
        group.add(save_btn)
        self._settings_save_btn = save_btn

    # ── Section 5: Actions ──

    def _build_actions_section(self) -> None:
        group = Adw.PreferencesGroup(
            title=_("Aktionen"),
        )
        self._content.append(group)

        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
        )
        btn_box.set_margin_top(4)
        btn_box.set_margin_bottom(4)

        # Trigger crawl
        self._trigger_combo = Gtk.DropDown.new_from_strings(
            [l for l in _DAY_LABELS.values()],
        )
        self._trigger_combo.set_size_request(140, -1)
        btn_box.append(self._trigger_combo)

        trigger_btn = Gtk.Button(label=_("Jetzt crawlen"))
        trigger_btn.add_css_class("suggested-action")
        trigger_btn.connect("clicked", self._on_trigger_crawl)
        self.register_readonly_button(trigger_btn)
        btn_box.append(trigger_btn)

        # Reset retry
        reset_btn = Gtk.Button(label=_("Retry zurücksetzen"))
        reset_btn.set_tooltip_text(
            _("Counter auf 0 setzen und sofort nochmal versuchen"),
        )
        reset_btn.add_css_class("flat")
        reset_btn.connect("clicked", self._on_reset_retry)
        self.register_readonly_button(reset_btn)
        btn_box.append(reset_btn)

        # Reset timing
        timing_btn = Gtk.Button(label=_("Timing zurücksetzen"))
        timing_btn.set_tooltip_text(
            _("ML-gelernte Zeiten verwerfen, Config-Defaults verwenden"),
        )
        timing_btn.add_css_class("flat")
        timing_btn.add_css_class("destructive-action")
        timing_btn.connect("clicked", self._on_reset_timing)
        self.register_readonly_button(timing_btn)
        btn_box.append(timing_btn)

        group.add(btn_box)

        self._action_status = Gtk.Label(label="")
        self._action_status.set_xalign(0)
        self._action_status.set_wrap(True)
        self._action_status.set_selectable(True)
        group.add(self._action_status)

    # ── Section 6: History ──

    def _build_history_section(self) -> None:
        group = Adw.PreferencesGroup(
            title=_("Crawl-Historie"),
            description=_("Letzte 30 Crawl-Versuche"),
        )
        self._content.append(group)

        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(200)
        scroll.set_max_content_height(300)

        # Columns: Datum, Tag, Status, Quelle, Retries, Neue
        self._history_store = Gtk.ListStore(str, str, str, str, str, str)
        tree = Gtk.TreeView(model=self._history_store)
        tree.set_headers_visible(True)
        tree.add_css_class("data-table")

        for i, title in enumerate([
            _("Datum"), _("Tag"), _("Status"),
            _("Quelle"), _("Retries"), _("Neue"),
        ]):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i)
            col.set_resizable(True)
            col.set_min_width(60)
            tree.append_column(col)

        scroll.set_child(tree)
        group.add(scroll)

    # ── Data Loading ──

    def _load_crawl_monitor(self) -> bool:
        """Load all monitor data from server."""
        if not self.api_client:
            return False

        def worker():
            try:
                data = self.api_client.get_crawl_monitor()
                GLib.idle_add(self._populate_monitor, data)
            except Exception as e:
                logger.warning(f"Crawl-Monitor laden: {e}")
                GLib.idle_add(
                    self._action_status.set_label,
                    f"Fehler: {e}",
                )

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _populate_monitor(self, data: dict) -> bool:
        """Populate all sections with server data."""
        self._populate_status(data)
        self._populate_timing(data.get("timing", {}))
        self._populate_sources(data.get("sources", {}))
        self._populate_settings(data.get("schedule", {}))
        self._load_history()
        return False

    def _populate_status(self, data: dict) -> None:
        """Section 1: Status per day."""
        crawl_jobs = data.get("crawl_jobs", {})
        retry_counts = data.get("retry_counts", {})
        last_crawls = data.get("last_crawls", {})
        activity = data.get("activity", {})

        for day, row in self._day_rows.items():
            parts = []
            # Last crawl
            lc = last_crawls.get(day, {})
            if lc:
                ts = lc.get("timestamp", "")[:16]
                st = lc.get("status", "?")
                found = lc.get("draws_found", 0)
                icon_name = {
                    "success": "emblem-ok-symbolic",
                    "not_found": "dialog-warning-symbolic",
                    "error": "dialog-error-symbolic",
                    "max_retries": "dialog-error-symbolic",
                }.get(st, "content-loading-symbolic")
                row._status_icon.set_from_icon_name(icon_name)
                st_label = {
                    "success": f"Erfolg ({found} neue)",
                    "not_found": "Nicht gefunden",
                    "error": "Fehler",
                    "max_retries": "Max Retries erreicht",
                }.get(st, st)
                parts.append(f"Letzter: {ts} — {st_label}")
            # Retries
            retries = retry_counts.get(day, 0)
            if retries > 0:
                parts.append(f"Retries: {retries}")
            # Next run
            job = crawl_jobs.get(day, {})
            next_run = job.get("next_run", "")
            if next_run:
                try:
                    dt = datetime.fromisoformat(next_run)
                    parts.append(f"Nächster: {dt:%d.%m. %H:%M}")
                except (ValueError, TypeError):
                    pass
            row.set_subtitle(" | ".join(parts) if parts else _("Keine Daten"))

        # Activity
        act_status = activity.get("status", "idle")
        act_day = activity.get("day", "")
        icon = _STATUS_ICONS.get(act_status, "content-loading-symbolic")
        self._activity_row.set_subtitle(
            f"{act_status}" + (f" ({_DAY_LABELS.get(act_day, act_day)})" if act_day else ""),
        )

    def _populate_timing(self, timing: dict) -> None:
        """Section 2: Smart Timing."""
        # Clear old rows
        while row := self._timing_group.get_first_child():
            if isinstance(row, Adw.ActionRow):
                self._timing_group.remove(row)
            else:
                break

        if not timing:
            row = Adw.ActionRow(
                title=_("Keine Timing-Daten"),
                subtitle=_("Zu wenig Crawl-Versuche für ML-Analyse"),
            )
            self._timing_group.add(row)
            return

        for day, info in timing.items():
            label = _DAY_LABELS.get(day, day)
            first = info.get("first_crawl")
            retry = info.get("retry")

            parts = []
            if first:
                parts.append(
                    f"Optimal: {first['hour']:02d}:{first['minute']:02d} "
                    f"(Konf. {first['confidence']:.0%}, "
                    f"Ø {first['avg_delay_minutes']:.0f}min, "
                    f"{first['samples']} Samples)"
                )
            else:
                parts.append("Optimal: noch nicht genug Daten")

            if retry:
                parts.append(
                    f"Retry: alle {retry['interval_hours']:.1f}h "
                    f"(Ø {retry['avg_retries']:.1f} Versuche, "
                    f"Konf. {retry['confidence']:.0%})"
                )

            row = Adw.ActionRow(
                title=label,
                subtitle=" | ".join(parts),
            )
            row.set_subtitle_lines(3)
            self._timing_group.add(row)

    def _populate_sources(self, sources: dict) -> None:
        """Section 3: Source reliability."""
        while row := self._source_group.get_first_child():
            if isinstance(row, Adw.ActionRow):
                self._source_group.remove(row)
            else:
                break

        if not sources:
            self._source_group.add(
                Adw.ActionRow(title=_("Keine Quellen-Daten")),
            )
            return

        for src, data in sorted(
            sources.items(), key=lambda x: x[1].get("rate", 0), reverse=True,
        ):
            rate = data.get("rate", 0)
            total = data.get("total", 0)
            success = data.get("success", 0)
            icon = (
                "emblem-ok-symbolic" if rate >= 80
                else "dialog-warning-symbolic" if rate >= 50
                else "dialog-error-symbolic"
            )
            row = Adw.ActionRow(
                title=src,
                subtitle=f"{rate:.0f}% Erfolg ({success}/{total})",
            )
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))

            # Progress bar as suffix
            bar = Gtk.ProgressBar()
            bar.set_fraction(rate / 100)
            bar.set_size_request(80, -1)
            bar.set_valign(Gtk.Align.CENTER)
            row.add_suffix(bar)

            self._source_group.add(row)

    def _populate_settings(self, schedule: dict) -> None:
        """Section 4: Fill settings from server data."""
        self._updating_settings = True
        try:
            self._crawl_enabled_switch.set_active(
                schedule.get("enabled", True),
            )
            self._smart_timing_switch.set_active(
                schedule.get("smart_timing", True),
            )
            self._retry_interval_spin.set_value(
                schedule.get("retry_interval_hours", 3),
            )
            self._max_retries_spin.set_value(
                schedule.get("max_retries", 8),
            )

            times = schedule.get("times", {})
            for day, (h_spin, m_spin) in self._time_spins.items():
                t = times.get(day, {})
                h_spin.set_value(t.get("hour", 20))
                m_spin.set_value(t.get("minute", 0))
        finally:
            self._updating_settings = False

    def _load_history(self) -> None:
        """Section 6: Load crawl history."""
        if not self.api_client:
            return

        def worker():
            try:
                entries = self.api_client.get_crawl_history(limit=30)
                GLib.idle_add(self._populate_history, entries)
            except Exception as e:
                logger.warning(f"Crawl-Historie: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _populate_history(self, entries: list) -> bool:
        """Fill history table."""
        self._history_store.clear()
        for e in entries:
            self._history_store.append([
                (e.get("timestamp", ""))[:16],
                _DAY_LABELS.get(e.get("draw_day", ""), e.get("draw_day", "")),
                e.get("status", "?"),
                e.get("source", "—"),
                str(e.get("retry_count", 0)),
                str(e.get("draws_found", 0)),
            ])
        return False

    # ── Event Handlers ──

    def _on_setting_changed(self, *_args) -> None:
        """Ignore programmatic changes during populate."""
        pass

    def _on_save_settings(self, _btn) -> None:
        """Save all schedule settings to server."""
        if self._is_readonly or not self.api_client:
            return

        kwargs = {
            "enabled": self._crawl_enabled_switch.get_active(),
            "smart_timing": self._smart_timing_switch.get_active(),
            "retry_interval_hours": int(self._retry_interval_spin.get_value()),
            "max_retries": int(self._max_retries_spin.get_value()),
        }
        for day, (h_spin, m_spin) in self._time_spins.items():
            kwargs[f"{day}_hour"] = int(h_spin.get_value())
            kwargs[f"{day}_minute"] = int(m_spin.get_value())

        self._settings_save_btn.set_sensitive(False)
        self._action_status.set_label(_("Speichere..."))

        def worker():
            try:
                result = self.api_client.update_crawl_schedule(**kwargs)
                changed = result.get("changed", [])
                msg = (
                    f"{len(changed)} Einstellungen gespeichert"
                    if changed else "Keine Änderungen"
                )
                GLib.idle_add(self._action_status.set_label, msg)
            except Exception as e:
                GLib.idle_add(
                    self._action_status.set_label, f"Fehler: {e}",
                )
            finally:
                GLib.idle_add(self._settings_save_btn.set_sensitive, True)

        threading.Thread(target=worker, daemon=True).start()

    def _on_trigger_crawl(self, _btn) -> None:
        """Trigger manual crawl for selected day."""
        if self._is_readonly or not self.api_client:
            return
        days = list(_DAY_LABELS.keys())
        idx = self._trigger_combo.get_selected()
        if idx >= len(days):
            return
        day = days[idx]
        self._action_status.set_label(f"Crawle {_DAY_LABELS[day]}...")

        def worker():
            try:
                result = self.api_client.trigger_crawl(day)
                r = result.get("result", {})
                status = r.get("status", "?")
                msg = r.get("message", "")
                GLib.idle_add(
                    self._action_status.set_label,
                    f"Crawl {_DAY_LABELS[day]}: {status}"
                    + (f" — {msg}" if msg else ""),
                )
                GLib.idle_add(self._load_crawl_monitor)
            except Exception as e:
                GLib.idle_add(
                    self._action_status.set_label, f"Fehler: {e}",
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_reset_retry(self, _btn) -> None:
        """Reset retry counter and trigger crawl."""
        if self._is_readonly or not self.api_client:
            return
        days = list(_DAY_LABELS.keys())
        idx = self._trigger_combo.get_selected()
        if idx >= len(days):
            return
        day = days[idx]
        self._action_status.set_label(f"Reset + Crawl {_DAY_LABELS[day]}...")

        def worker():
            try:
                self.api_client.reset_crawl_retry(day)
                GLib.idle_add(
                    self._action_status.set_label,
                    f"Retry zurückgesetzt für {_DAY_LABELS[day]}",
                )
                GLib.idle_add(self._load_crawl_monitor)
            except Exception as e:
                GLib.idle_add(
                    self._action_status.set_label, f"Fehler: {e}",
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_reset_timing(self, _btn) -> None:
        """Reset ML timing data."""
        if self._is_readonly or not self.api_client:
            return
        self._action_status.set_label(_("Timing wird zurückgesetzt..."))

        def worker():
            try:
                self.api_client.reset_crawl_timing()
                GLib.idle_add(
                    self._action_status.set_label,
                    _("Timing-Daten zurückgesetzt"),
                )
                GLib.idle_add(self._load_crawl_monitor)
            except Exception as e:
                GLib.idle_add(
                    self._action_status.set_label, f"Fehler: {e}",
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_ws_monitor_update(self, data: dict) -> bool:
        """WS push → refresh monitor data."""
        self._load_crawl_monitor()
        return False

    def _cleanup_crawl_monitor(self) -> None:
        """Unsubscribe WS listeners."""
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("scheduler_status", self._on_ws_monitor_update)
            ui_ws_manager.off("draw_update", self._on_ws_monitor_update)
        except Exception:
            pass
