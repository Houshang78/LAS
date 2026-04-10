"""Berichte-Seite: Part 5 — Mass-Generation Reports Sub-Tab."""

import json
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("reports.part5")


class Part5Mixin:
    """Mass-Generation Reports Sub-Tab."""

    def _build_mass_gen_tab(self) -> None:
        """Mass-Gen Batches Tab aufbauen."""
        group = Adw.PreferencesGroup(
            title=_("Mass-Generation Batches"),
            description=_(
                "Pipeline-Berichte: Generierung + Deduplizierung + Re-Generierung"
            ),
        )
        self._mg_tab_box.append(group)

        # Refresh button
        refresh_row = Adw.ActionRow(title=_("Daten laden"))
        mg_refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        mg_refresh.set_tooltip_text(_("Mass-Gen-Berichte laden"))
        mg_refresh.set_valign(Gtk.Align.CENTER)
        mg_refresh.connect("clicked", self._on_mg_tab_refresh)
        refresh_row.add_suffix(mg_refresh)
        group.add(refresh_row)

        # Scrollable list
        self._mg_tab_list = Gtk.ListBox()
        self._mg_tab_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._mg_tab_list.add_css_class("boxed-list")

        mg_scroll = Gtk.ScrolledWindow(vexpand=True)
        mg_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        mg_scroll.set_child(self._mg_tab_list)
        self._mg_tab_box.append(mg_scroll)
        self._mg_tab_rows: list[Gtk.Widget] = []

    def _on_mg_tab_refresh(self, _btn) -> None:
        """Mass-Gen Berichte laden (Batches + Cycle Reports)."""
        def worker():
            batches = []
            reports = []
            try:
                if self.api_client:
                    batches = self.api_client.mass_batches(limit=30)
            except Exception as e:
                logger.warning(f"Mass-Gen batches load: {e}")

            # Also load cycle reports with draw_day=mass_gen
            try:
                if self.api_client:
                    resp = self.api_client._request(
                        "GET", "/reports",
                        params={"draw_day": "mass_gen", "limit": 30},
                    ).json()
                    reports = resp.get("reports", [])
            except Exception as e:
                logger.debug(f"Mass-Gen cycle reports: {e}")

            GLib.idle_add(self._on_mg_tab_loaded, batches, reports)

        threading.Thread(target=worker, daemon=True).start()

    def _on_mg_tab_loaded(
        self, batches: list, reports: list,
    ) -> bool:
        """Mass-Gen Liste befuellen."""
        # Clear
        while self._mg_tab_rows:
            self._mg_tab_list.remove(self._mg_tab_rows.pop())

        # Merge: show cycle reports first (pipeline results), then raw batches
        if reports:
            header = Adw.ActionRow(title=_("Pipeline-Berichte"))
            header.add_css_class("heading")
            self._mg_tab_list.append(header)
            self._mg_tab_rows.append(header)

            for r in reports[:15]:
                cats = r.get("match_categories", "{}")
                if isinstance(cats, str):
                    try:
                        cats = json.loads(cats)
                    except Exception:
                        cats = {}

                strategy = cats.get("strategy", "?")
                draw_day = cats.get("original_draw_day", "?")
                total = cats.get("final_count", r.get("predictions_compared", 0))
                dedup = cats.get("dedup_removed", 0)
                elapsed = cats.get("total_seconds", 0)
                rate = cats.get("rate_per_second", 0)
                batch_id = cats.get("batch_id", "")[:8]
                created = str(r.get("created_at", ""))[:16]

                title = f"{created} | {strategy} | {draw_day}"
                subtitle = f"{total:,} Predictions"
                if dedup:
                    subtitle += f" | -{dedup:,} Duplikate"
                subtitle += f" | {elapsed}s"
                if rate:
                    subtitle += f" ({rate:,}/s)"
                if batch_id:
                    subtitle += f" | {batch_id}..."

                row = Adw.ActionRow(title=title, subtitle=subtitle)
                self._mg_tab_list.append(row)
                self._mg_tab_rows.append(row)

        # Raw batches (from PostgreSQL)
        if batches:
            header2 = Adw.ActionRow(title=_("PostgreSQL Batches"))
            header2.add_css_class("heading")
            self._mg_tab_list.append(header2)
            self._mg_tab_rows.append(header2)

            for b in batches[:15]:
                status = b.get("status", "?")
                strategy = b.get("strategy", "?")
                count = b.get("count", 0)
                day = b.get("draw_day", "?")
                elapsed = b.get("generation_seconds") or 0
                dedup = b.get("dedup_removed") or 0
                batch_id = str(b.get("id", ""))[:8]
                created = str(b.get("created_at", ""))[:16]

                title = f"{created} | {strategy} | {day} [{status}]"
                subtitle = f"{count:,} Predictions | {elapsed:.1f}s"
                if dedup > 0:
                    subtitle += f" | -{dedup:,} Duplikate"
                subtitle += f" | {batch_id}..."

                row = Adw.ActionRow(title=title, subtitle=subtitle)
                self._mg_tab_list.append(row)
                self._mg_tab_rows.append(row)

        if not batches and not reports:
            row = Adw.ActionRow(
                title=_("Keine Mass-Gen Berichte vorhanden"),
                subtitle=_("Starte eine Mass-Generation im Generator-Tab"),
            )
            self._mg_tab_list.append(row)
            self._mg_tab_rows.append(row)

        return False
