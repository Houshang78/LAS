"""TaskStatusBar: Zeigt laufende Server-Tasks als Statusleiste."""

import json
import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.utils.logging_config import get_logger

logger = get_logger("task_status")

# Operation → display name
_OP_LABELS = {
    "crawl": "Crawl",
    "ml_train": "ML-Training",
    "ml_train_custom": "Custom-Training",
    "multi_stage_train": "Multi-Stage Training",
    "hypersearch": "Hyperparameter-Suche",
    "compare_ranges": "Zeitraum-Vergleich",
    "tournament": "Strategie-Turnier",
    "ai_train": "AI-Training",
    "self_improve": "Self-Improvement",
    "backtest": "Walk-Forward Backtest",
}

# Draw day → localized display name
_DAY_LABELS = {
    "saturday": "Sa (6aus49)",
    "wednesday": "Mi (6aus49)",
    "tuesday": "Di (EJ)",
    "friday": "Fr (EJ)",
}


class TaskStatusBar(Gtk.Box):
    """Statusleiste die laufende Server-Tasks anzeigt.

    Pollt GET /tasks?status=running alle 5 Sekunden.
    Zeigt Tasks als kompakte Zeilen mit Progress und Abbrechen-Button.
    """

    def __init__(self, api_client=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.api_client = api_client
        self._poll_id: int | None = None
        self._task_rows: dict[str, Gtk.Box] = {}

        self.add_css_class("task-status-bar")

        # Revealer: nur sichtbar wenn Tasks laufen
        self._revealer = Gtk.Revealer()
        self._revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self._revealer.set_reveal_child(False)
        self.append(self._revealer)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        inner.set_margin_start(8)
        inner.set_margin_end(8)
        inner.set_margin_top(4)
        inner.set_margin_bottom(4)
        self._revealer.set_child(inner)

        # Separator oben
        inner.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Image.new_from_icon_name("emblem-synchronizing-symbolic")
        icon.set_pixel_size(16)
        header.append(icon)
        self._header_label = Gtk.Label(label="Server-Tasks")
        self._header_label.add_css_class("heading")
        header.append(self._header_label)
        inner.append(header)

        # Task-Liste
        self._task_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        inner.append(self._task_list)

    POLL_FALLBACK_SECONDS = 30  # Slow fallback when WS is connected

    def set_api_client(self, client) -> None:
        """Set API client — subscribe via WS manager, polling as fallback."""
        self.api_client = client
        self._subscribe_ws()
        self.start_polling()

    def _subscribe_ws(self) -> None:
        """Subscribe to task_update events via global WS manager."""
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.connect_client(self.api_client)
            ui_ws_manager.on("task_update", self._on_ws_task_update)
            logger.info("TaskStatusBar: subscribed via UIWebSocketManager")
        except Exception as e:
            logger.debug(f"WS subscription failed: {e}")

    def _on_ws_task_update(self, data: dict) -> bool:
        """Handle task_update from WS (called on GTK main thread via GLib.idle_add)."""
        self._poll()
        return False  # GLib.idle_add: remove source

    def start_polling(self) -> None:
        """Start slow fallback polling (30s when WS connected)."""
        if self._poll_id is not None:
            return
        if not self.api_client:
            return
        self._poll()
        self._poll_id = GLib.timeout_add_seconds(
            self.POLL_FALLBACK_SECONDS, self._poll,
        )

    def stop_polling(self) -> None:
        """Polling stoppen und WS-Abo lösen."""
        if self._poll_id is not None:
            GLib.source_remove(self._poll_id)
            self._poll_id = None
        try:
            from lotto_analyzer.ui.widgets.ws_manager import ui_ws_manager
            ui_ws_manager.off("task_update", self._on_ws_task_update)
        except Exception:
            pass

    def _poll(self) -> bool:
        """Tasks vom Server abfragen (in Background-Thread)."""
        if not self.api_client:
            return True  # weiter pollen

        def fetch():
            try:
                tasks = self.api_client.get_tasks(status="running")
                GLib.idle_add(self._update_ui, tasks)
            except Exception as e:
                logger.debug(f"Task-Polling fehlgeschlagen: {e}")

        threading.Thread(target=fetch, daemon=True).start()
        return True  # GLib.timeout_add: True = weiter pollen

    def _update_ui(self, tasks: list[dict]) -> bool:
        """UI mit aktuellen Tasks aktualisieren (Main-Thread)."""
        # Tasks sichtbar wenn welche laufen
        has_tasks = len(tasks) > 0
        self._revealer.set_reveal_child(has_tasks)

        if not has_tasks:
            self._clear_rows()
            return False

        self._header_label.set_label(f"Server-Tasks ({len(tasks)})")

        # Bestehende Task-IDs
        current_ids = {t["id"] for t in tasks}
        # Alte Rows entfernen
        for tid in list(self._task_rows.keys()):
            if tid not in current_ids:
                row = self._task_rows.pop(tid)
                self._task_list.remove(row)

        # Tasks aktualisieren/erstellen
        for task in tasks:
            tid = task["id"]
            if tid in self._task_rows:
                self._update_row(tid, task)
            else:
                self._create_row(task)

        return False

    def _create_row(self, task: dict) -> None:
        """Neue Task-Zeile erstellen."""
        tid = task["id"]
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(4)
        row.set_margin_end(4)

        # Operation label with draw day and params info
        op = task.get("operation", "?")
        op_label = _OP_LABELS.get(op, op)
        draw_day = task.get("draw_day", "")
        if draw_day:
            day_name = _DAY_LABELS.get(draw_day, draw_day)
            op_label += f" — {day_name}"
        # Extra info from params (e.g. model type, stages)
        params = task.get("params")
        if params:
            try:
                p = json.loads(params) if isinstance(params, str) else params
                if p.get("mode"):
                    op_label += f" [{p['mode']}]"
                if p.get("stages"):
                    op_label += f" [{len(p['stages'])} Stufen]"
                if p.get("n_rounds"):
                    op_label += f" [{p['n_rounds']}R]"
            except (json.JSONDecodeError, TypeError):
                pass
        lbl = Gtk.Label(label=op_label)
        lbl.set_xalign(0)
        lbl.set_hexpand(True)
        lbl.set_ellipsize(3)  # Pango.EllipsizeMode.END
        row.append(lbl)

        # Progress-Bar
        progress = Gtk.ProgressBar()
        progress.set_size_request(120, -1)
        progress.set_fraction(task.get("progress", 0))
        progress.set_show_text(True)
        pct = int(task.get("progress", 0) * 100)
        progress.set_text(f"{pct}%")
        row.append(progress)

        # Laufzeit
        created = task.get("created_at", "")
        elapsed_lbl = Gtk.Label()
        elapsed_lbl.add_css_class("dim-label")
        elapsed_lbl.set_size_request(60, -1)
        if created:
            try:
                start = datetime.fromisoformat(created)
                elapsed = datetime.now() - start
                mins = int(elapsed.total_seconds() // 60)
                secs = int(elapsed.total_seconds() % 60)
                elapsed_lbl.set_label(f"{mins}:{secs:02d}")
            except Exception as e:
                logger.debug(f"Elapsed-Zeit parsen fehlgeschlagen: {e}")
                elapsed_lbl.set_label("—")
        row.append(elapsed_lbl)

        # Abbrechen-Button
        cancel_btn = Gtk.Button(icon_name="process-stop-symbolic")
        cancel_btn.set_tooltip_text("Abbrechen")
        cancel_btn.add_css_class("flat")
        cancel_btn.add_css_class("circular")
        cancel_btn.connect("clicked", self._on_cancel, tid)
        row.append(cancel_btn)

        # In row-Daten speichern für Updates
        row._progress = progress
        row._elapsed = elapsed_lbl
        row._created = created

        self._task_list.append(row)
        self._task_rows[tid] = row

    def _update_row(self, tid: str, task: dict) -> None:
        """Bestehende Task-Zeile aktualisieren."""
        row = self._task_rows.get(tid)
        if not row:
            return
        if not hasattr(row, '_progress') or not hasattr(row, '_elapsed'):
            return

        progress = task.get("progress", 0)
        row._progress.set_fraction(progress)
        pct = int(progress * 100)
        row._progress.set_text(f"{pct}%")

        created = row._created
        if created:
            try:
                start = datetime.fromisoformat(created)
                elapsed = datetime.now() - start
                mins = int(elapsed.total_seconds() // 60)
                secs = int(elapsed.total_seconds() % 60)
                row._elapsed.set_label(f"{mins}:{secs:02d}")
            except Exception as e:
                logger.debug(f"Elapsed-Zeit aktualisieren fehlgeschlagen: {e}")

    def _clear_rows(self) -> None:
        """Alle Task-Zeilen entfernen."""
        for row in self._task_rows.values():
            self._task_list.remove(row)
        self._task_rows.clear()

    def _on_cancel(self, button: Gtk.Button, task_id: str) -> None:
        """Task abbrechen."""
        button.set_sensitive(False)

        def cancel():
            try:
                if self.api_client:
                    self.api_client.cancel_task(task_id)
            except Exception as e:
                logger.warning(f"Task-Abbruch fehlgeschlagen: {e}")

        threading.Thread(target=cancel, daemon=True).start()
