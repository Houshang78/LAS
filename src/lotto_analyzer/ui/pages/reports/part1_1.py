"""UI-Seite reports: part1 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("reports.part1")
import time




class Part1Mixin1:
    """Teil 1 von Part1Mixin."""

    def _cache_get(self, cache_dict: dict, key: str):
        """Cache-Eintrag lesen, None wenn abgelaufen oder nicht vorhanden."""
        entry = cache_dict.get(key)
        if entry and (time.time() - entry[0]) < self.CACHE_TTL:
            return entry[1]
        if entry:
            del cache_dict[key]
        return None

    def _cache_set(self, cache_dict: dict, key: str, value) -> None:
        """Cache-Eintrag mit aktuellem Zeitstempel speichern."""
        cache_dict[key] = (time.time(), value)

    # ── UI aufbauen ──

    def _build_ui(self) -> None:
        # Header with title
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_box.set_margin_top(16)
        header_box.set_margin_bottom(8)
        header_box.set_margin_start(16)
        header_box.set_margin_end(16)

        title = Gtk.Label(label=_("Berichte"))
        title.add_css_class("title-1")
        title.set_hexpand(True)
        title.set_xalign(0)
        header_box.append(title)

        self.append(header_box)

        # Sub-tabs: browser-style tab bar (Zyklus / Backtest / ML-Training)
        self._report_stack = Gtk.Stack()
        self._report_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._report_stack.set_transition_duration(150)

        tab_bar = Gtk.StackSwitcher()
        tab_bar.set_stack(self._report_stack)
        tab_bar.set_margin_start(16)
        tab_bar.set_margin_end(16)
        tab_bar.set_margin_bottom(4)
        self.append(tab_bar)

        # ── Tab 1: Zyklus-Berichte (existing content) ──
        cycle_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._report_stack.add_titled(cycle_box, "cycle", _("Zyklus-Berichte"))
        self._cycle_container = cycle_box

        # Control bar: day dropdown + buttons
        ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ctrl_box.set_margin_start(16)
        ctrl_box.set_margin_end(16)
        ctrl_box.set_margin_bottom(8)

        day_label = Gtk.Label(label=_("Ziehungstag:"))
        ctrl_box.append(day_label)

        self._day_dropdown = Gtk.DropDown()
        self._day_model = Gtk.StringList()
        self._rebuild_day_model()
        self._day_dropdown.set_model(self._day_model)
        self._day_dropdown.connect("notify::selected", self._on_day_changed)
        ctrl_box.append(self._day_dropdown)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        ctrl_box.append(spacer)

        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        ctrl_box.append(self._spinner)

        self._refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        self._refresh_btn.set_tooltip_text(_("Berichte neu laden"))
        self._refresh_btn.connect("clicked", lambda _: self._load_reports())
        ctrl_box.append(self._refresh_btn)

        self._telegram_btn = Gtk.Button(icon_name="mail-send-symbolic")
        self._telegram_btn.set_tooltip_text(_("Ausgewählten Bericht per Telegram senden"))
        self._telegram_btn.add_css_class("suggested-action")
        self._telegram_btn.set_sensitive(False)
        self._telegram_btn.connect("clicked", self._on_telegram_send)
        ctrl_box.append(self._telegram_btn)

        self._export_md_btn = Gtk.Button(label=_("Als Markdown exportieren"))
        self._export_md_btn.set_icon_name("document-save-symbolic")
        self._export_md_btn.add_css_class("flat")
        self._export_md_btn.set_tooltip_text(_("Ausgewählten Bericht als Markdown-Datei exportieren"))
        self._export_md_btn.connect("clicked", self._on_export_markdown)
        self._export_md_btn.set_visible(False)
        ctrl_box.append(self._export_md_btn)

        cycle_box.append(ctrl_box)

        # ── Tab 2: Backtest-Berichte ──
        self._bt_tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._bt_tab_box.set_margin_top(8)
        self._bt_tab_box.set_margin_start(16)
        self._bt_tab_box.set_margin_end(16)
        self._report_stack.add_titled(self._bt_tab_box, "backtest", _("Backtest"))
        self._build_backtest_tab()

        # ── Tab 3: ML-Training-Berichte ──
        self._ml_tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._ml_tab_box.set_margin_top(8)
        self._ml_tab_box.set_margin_start(16)
        self._ml_tab_box.set_margin_end(16)
        self._report_stack.add_titled(self._ml_tab_box, "ml", _("ML-Training"))
        self._build_ml_tab()

        # ── Tab 4: Mass-Generation-Berichte ──
        self._mg_tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._mg_tab_box.set_margin_top(8)
        self._mg_tab_box.set_margin_start(16)
        self._mg_tab_box.set_margin_end(16)
        self._report_stack.add_titled(self._mg_tab_box, "mass_gen", _("Mass-Generation"))
        self._build_mass_gen_tab()

        self.append(self._report_stack)
        self._report_stack.set_vexpand(True)

        # Auto-load data when sub-tab changes
        def _on_stack_changed(stack, _pspec):
            page = stack.get_visible_child_name()
            if page == "backtest" and not self._bt_tab_rows:
                self._on_bt_tab_refresh(None)
            elif page == "ml" and not self._ml_tab_rows:
                self._on_ml_tab_refresh(None)
            elif page == "mass_gen" and not self._mg_tab_rows:
                self._on_mg_tab_refresh(None)

        self._report_stack.connect("notify::visible-child-name", _on_stack_changed)

        # Separator moved inside cycle tab
        cycle_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Main area: Paned (list left, detail right) — inside cycle tab
        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned.set_vexpand(True)
        self._paned.set_position(380)
        cycle_box.append(self._paned)

        # ── Liste (links) ──
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        list_box.set_size_request(300, -1)

        list_scrolled = Gtk.ScrolledWindow()
        list_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        list_scrolled.set_vexpand(True)

        self._listbox = Gtk.ListBox()
        self._listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._listbox.add_css_class("boxed-list")
        self._listbox.connect("row-selected", self._on_report_selected)

        # Platzhalter wenn keine Berichte
        self._listbox.set_placeholder(
            Gtk.Label(label=_("Keine Berichte vorhanden.") + "\n" + _("Berichte werden nach Crawl + Vergleich automatisch erstellt."))
        )

        list_scrolled.set_child(self._listbox)
        list_box.append(list_scrolled)
        self._paned.set_start_child(list_box)

        # ── Detail (rechts) ──
        detail_scrolled = Gtk.ScrolledWindow()
        detail_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        detail_scrolled.set_vexpand(True)

        self._detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self._detail_box.set_margin_top(16)
        self._detail_box.set_margin_bottom(16)
        self._detail_box.set_margin_start(16)
        self._detail_box.set_margin_end(16)

        # Platzhalter
        self._detail_placeholder = Gtk.Label(
            label=_("Bericht aus der Liste auswählen")
        )
        self._detail_placeholder.add_css_class("dim-label")
        self._detail_placeholder.set_vexpand(True)
        self._detail_placeholder.set_valign(Gtk.Align.CENTER)
        self._detail_box.append(self._detail_placeholder)

        # Detail-Widgets (initial unsichtbar)
        self._detail_title = Gtk.Label()
        self._detail_title.add_css_class("title-2")
        self._detail_title.set_xalign(0)
        self._detail_title.set_visible(False)
        self._detail_box.append(self._detail_title)

        # Statistik-Grid
        self._stats_grid = Gtk.Grid()
        self._stats_grid.set_row_spacing(8)
        self._stats_grid.set_column_spacing(16)
        self._stats_grid.set_visible(False)
        self._detail_box.append(self._stats_grid)

        # Kategorien-Bereich
        self._categories_group = Adw.PreferencesGroup(title=_("Treffer-Kategorien"))
        self._categories_group.set_visible(False)
        self._detail_box.append(self._categories_group)

        # Gewinnquoten Gruppe
        self._quoten_group = Adw.PreferencesGroup(title=_("Gewinnquoten"))
        self._quoten_group.set_visible(False)
        self._detail_box.append(self._quoten_group)
        self._prizes_cache: dict[str, tuple[float, list[dict]]] = {}

        # ML-Genauigkeit Gruppe
        self._accuracy_group = Adw.PreferencesGroup(title=_("ML-Genauigkeit"))
        self._accuracy_group.set_visible(False)
        self._detail_box.append(self._accuracy_group)

        self._accuracy_grid = Gtk.Grid()
        self._accuracy_grid.set_row_spacing(6)
        self._accuracy_grid.set_column_spacing(16)
        self._accuracy_group.add(self._accuracy_grid)

        # AI-Treffer-Analyse Gruppe
        self._ai_hits_group = Adw.PreferencesGroup(title=_("AI-Treffer-Analyse"))
        self._ai_hits_group.set_visible(False)
        self._detail_box.append(self._ai_hits_group)

        ai_hits_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        ai_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._analyze_hits_btn = Gtk.Button(label=_("Treffer-Muster analysieren"))
        self._analyze_hits_btn.set_tooltip_text(_("AI analysiert Trefferquoten und erkennt Muster"))
        self._analyze_hits_btn.add_css_class("suggested-action")
        self._analyze_hits_btn.connect("clicked", self._on_analyze_hits)
        ai_btn_box.append(self._analyze_hits_btn)

        self._analyze_spinner = Gtk.Spinner()
        self._analyze_spinner.set_visible(False)
        ai_btn_box.append(self._analyze_spinner)

        ai_hits_box.append(ai_btn_box)

        self._ai_hits_label = Gtk.Label()
        self._ai_hits_label.set_wrap(True)
        self._ai_hits_label.set_xalign(0)
        self._ai_hits_label.set_selectable(True)
        self._ai_hits_label.set_visible(False)
        ai_hits_box.append(self._ai_hits_label)

        self._ai_hits_group.add(ai_hits_box)

        # AI-Summary
        self._summary_group = Adw.PreferencesGroup(title=_("AI-Zusammenfassung"))
        self._summary_group.set_visible(False)
        self._detail_box.append(self._summary_group)

        self._summary_label = Gtk.Label()
        self._summary_label.set_wrap(True)
        self._summary_label.set_xalign(0)
        self._summary_label.set_selectable(True)
        self._summary_label.set_visible(False)
        self._summary_group.add(self._summary_label)

        # Backtest is now a separate sub-tab (Tab 2)

        detail_scrolled.set_child(self._detail_box)
        self._paned.set_end_child(detail_scrolled)

    def _build_backtest_section(self) -> None:
        """Legacy stub — backtest is now in its own sub-tab (Tab 2).

        Keep dummy attributes so old references don't crash.
        """
        self._bt_report_group = Gtk.Box()
        self._bt_run_combo = Gtk.ComboBoxText()
        self._bt_detail_box = Gtk.Box()
        self._bt_chart_box = Gtk.Box()
        self._bt_ai_btn = Gtk.Button()
        self._bt_ai_spinner = Gtk.Spinner()
        self._bt_ai_label = Gtk.Label()
        self._bt_chat_panel = None
        self._bt_runs: list[dict] = []
        self._bt_selected_run: dict | None = None
        self._bt_report_text: str = ""

        # Backtest callbacks removed — now in sub-tab

    # ── Backtest tab ──

    def _build_backtest_tab(self) -> None:
        """Build the backtest reports sub-tab content."""
        group = Adw.PreferencesGroup(
            title=_("Backtest-Ergebnisse"),
            description=_("Walk-Forward Backtesting Runs und Ergebnisse"),
        )
        self._bt_tab_box.append(group)

        refresh_row = Adw.ActionRow(title=_("Daten laden"))
        bt_refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        bt_refresh.set_tooltip_text(_("Backtest-Runs laden"))
        bt_refresh.set_valign(Gtk.Align.CENTER)
        bt_refresh.connect("clicked", self._on_bt_tab_refresh)
        refresh_row.add_suffix(bt_refresh)
        group.add(refresh_row)

        self._bt_tab_list = Gtk.ListBox()
        self._bt_tab_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._bt_tab_list.add_css_class("boxed-list")

        bt_scroll = Gtk.ScrolledWindow(vexpand=True)
        bt_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        bt_scroll.set_child(self._bt_tab_list)
        self._bt_tab_box.append(bt_scroll)
        self._bt_tab_rows: list = []

    def _on_bt_tab_refresh(self, _btn) -> None:
        def worker():
            runs = []
            try:
                if self.api_client:
                    dd = self._get_selected_draw_day()
                    resp = self.api_client.get_backtest_runs(dd or "")
                    runs = resp if isinstance(resp, list) else resp.get("runs", [])
            except Exception as e:
                logger.warning(f"Backtest runs load: {e}")
            GLib.idle_add(self._on_bt_tab_loaded, runs)

        threading.Thread(target=worker, daemon=True).start()

    def _on_bt_tab_loaded(self, runs: list) -> bool:
        while self._bt_tab_rows:
            self._bt_tab_list.remove(self._bt_tab_rows.pop())

        for run in runs[:30]:
            st = {"completed": "✓", "running": "⏳", "failed": "✗"}.get(
                run.get("status", "").lower(), "?"
            )
            day = run.get("draw_day", "?")
            window = run.get("window_months", "?")
            best = run.get("best_strategy", "—")
            avg = run.get("avg_matches", 0)
            created = str(run.get("created_at", ""))[:16]
            row = Adw.ActionRow(
                title=f"{st} {created} | {day} | {window}M",
                subtitle=f"Best: {best} | Ø {avg:.2f} matches",
            )
            self._bt_tab_list.append(row)
            self._bt_tab_rows.append(row)

        if not runs:
            row = Adw.ActionRow(title=_("Keine Backtest-Runs"))
            self._bt_tab_list.append(row)
            self._bt_tab_rows.append(row)
        return False

    # ── ML-Training tab ──

    def _build_ml_tab(self) -> None:
        """Build the ML training reports sub-tab content."""
        group = Adw.PreferencesGroup(
            title=_("ML-Training Verlauf"),
            description=_("Trainingsläufe, Accuracy und Modell-Performance"),
        )
        self._ml_tab_box.append(group)

        refresh_row = Adw.ActionRow(title=_("Daten laden"))
        ml_refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        ml_refresh.set_tooltip_text(_("Training-Historie laden"))
        ml_refresh.set_valign(Gtk.Align.CENTER)
        ml_refresh.connect("clicked", self._on_ml_tab_refresh)
        refresh_row.add_suffix(ml_refresh)
        group.add(refresh_row)

        self._ml_tab_list = Gtk.ListBox()
        self._ml_tab_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._ml_tab_list.add_css_class("boxed-list")

        ml_scroll = Gtk.ScrolledWindow(vexpand=True)
        ml_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        ml_scroll.set_child(self._ml_tab_list)
        self._ml_tab_box.append(ml_scroll)
        self._ml_tab_rows: list = []

    def _on_ml_tab_refresh(self, _btn) -> None:
        def worker():
            history = []
            try:
                if self.api_client:
                    # Read ml_models directly — get latest per model_type+draw_day
                    dd = self._get_selected_draw_day() or "saturday"
                    resp = self.api_client.ml_status()
                    if isinstance(resp, dict):
                        # Group by draw_day, take latest per model_type
                        seen = set()
                        items = sorted(
                            [(k, m) for k, m in resp.items() if isinstance(m, dict)],
                            key=lambda x: x[1].get("last_trained", ""),
                            reverse=True,
                        )
                        for key, m in items:
                            mday = m.get("draw_day", "")
                            mtype = m.get("model_type", "")
                            if dd and mday != dd:
                                continue
                            dedup = f"{mtype}_{mday}"
                            if dedup in seen:
                                continue
                            seen.add(dedup)
                            history.append({
                                "created_at": m.get("last_trained", ""),
                                "accuracy": m.get("accuracy", 0),
                                "model_type": mtype,
                                "draw_day": mday,
                            })
            except Exception as e:
                logger.warning(f"ML training history load: {e}")
            GLib.idle_add(self._on_ml_tab_loaded, history)

        threading.Thread(target=worker, daemon=True).start()

    def _on_ml_tab_loaded(self, history: list) -> bool:
        while self._ml_tab_rows:
            self._ml_tab_list.remove(self._ml_tab_rows.pop())

        for run in history[:50]:
            created = str(run.get("created_at") or run.get("last_trained", ""))[:16]
            model_type = run.get("model_type", "")
            rf_acc = run.get("rf_accuracy") or 0
            gb_acc = run.get("gb_accuracy") or 0
            acc = run.get("accuracy") or 0
            n_samples = run.get("n_samples") or 0
            duration = run.get("duration_sec") or 0
            day = run.get("draw_day", "")

            # Format depends on source (ml_models vs training_runs)
            if model_type:
                title = f"{created} | {model_type.upper()} {day}: {acc:.1%}"
            elif rf_acc or gb_acc:
                title = f"{created} | RF: {rf_acc:.1%} | GB: {gb_acc:.1%}"
            else:
                title = f"{created} | {day}"

            subtitle = f"{n_samples} Samples" if n_samples else ""
            if duration:
                subtitle += f", {duration:.0f}s"

            row = Adw.ActionRow(title=title, subtitle=subtitle or "—")
            self._ml_tab_list.append(row)
            self._ml_tab_rows.append(row)

        if not history:
            row = Adw.ActionRow(title=_("Keine Training-Runs"))
            self._ml_tab_list.append(row)
            self._ml_tab_rows.append(row)
        return False

