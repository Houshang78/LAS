"""UI-Seite reports: part4 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config

logger = get_logger("reports.part4")

from lotto_common.models.game_config import GameType, get_config


class Part4Mixin:
    """Part4 Mixin."""

    # ── Spieltyp / API-Client ──

    def set_game_type(self, game_type: GameType) -> None:
        """Spieltyp wechseln — Dropdown + Berichte aktualisieren."""
        self._game_type = game_type
        self._config = get_config(game_type)
        self._switching_game = True
        self._rebuild_day_model()
        self._day_dropdown.set_selected(0)
        self._switching_game = False
        self._load_reports()

    def set_api_client(self, client: "APIClient | None") -> None:
        """API-Client setzen."""
        super().set_api_client(client)
        if hasattr(self, '_bt_chat_panel') and self._bt_chat_panel:
            self._bt_chat_panel.api_client = client

    def refresh(self) -> None:
        """Berichte nur neu laden wenn Daten veraltet (>5min)."""
        if not self.is_stale():
            return
        self._hits_cache.clear()
        self._accuracy_cache.clear()
        self._prizes_cache.clear()
        self._load_reports()

    def _on_show_backtest_reports(self, _btn) -> None:
        """Backtest-Berichte als Dialog anzeigen."""
        import json as json_mod

        dialog = Adw.Dialog()
        dialog.set_title(_("Backtest-Berichte"))
        dialog.set_content_width(600)
        dialog.set_content_height(500)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                          margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        scroll.set_child(content)
        dialog.set_child(scroll)

        def worker():
            runs = []
            try:
                if self.api_client:
                    runs = self.api_client.get_backtest_runs(limit=20)
            except Exception as e:
                logger.warning(f"Backtest-Runs laden fehlgeschlagen: {e}")
            GLib.idle_add(show_runs, runs)

        def show_runs(runs):
            if not runs:
                content.append(Gtk.Label(label=_("Keine Backtest-Berichte vorhanden.")))
                return

            for run in runs:
                frame = Gtk.Frame()
                frame.add_css_class("card")
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                              margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)

                day = run.get("draw_day", "?")
                status = run.get("status", "?")
                best = run.get("best_strategy", "—")
                window = run.get("window_months", "?")
                steps = run.get("step_count", 0)
                total = run.get("total_steps", 0)
                created = run.get("created_at", "")[:16]

                header = Gtk.Label(
                    label=f"{day.capitalize()} — {window}mo Fenster — {status.upper()}",
                    xalign=0,
                )
                header.add_css_class("heading")
                box.append(header)

                details = Gtk.Label(
                    label=f"{_('Beste Strategie')}: {best} | {_('Schritte')}: {steps}/{total} | {created}",
                    xalign=0,
                )
                details.add_css_class("dim-label")
                box.append(details)

                # Ergebnis-Summary
                try:
                    summary = json_mod.loads(run.get("result_summary", "{}"))
                    verdict = summary.get("_verdict", {})
                    if verdict:
                        v_label = Gtk.Label(
                            label=f"{_('Bewertung')}: {verdict.get('rating', '—')} — {verdict.get('message', '')}",
                            xalign=0, wrap=True,
                        )
                        box.append(v_label)

                    # Strategie-Details
                    for strat, data in sorted(summary.items()):
                        if strat.startswith("_"):
                            continue
                        if isinstance(data, dict):
                            s_label = Gtk.Label(
                                label=f"  {strat}: Avg {data.get('avg_matches', 0):.2f}, "
                                      f"3+: {data.get('hit_rate_3plus', 0):.1f}%, "
                                      f"Wins: {data.get('wins_3plus', 0)}",
                                xalign=0,
                            )
                            s_label.add_css_class("caption")
                            box.append(s_label)
                except (json_mod.JSONDecodeError, TypeError):
                    pass

                frame.set_child(box)
                content.append(frame)

        threading.Thread(target=worker, daemon=True).start()
        dialog.present(self.get_root())
