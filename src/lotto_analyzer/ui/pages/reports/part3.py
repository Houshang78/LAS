"""UI-Seite reports: part3 Mixin."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("reports.part3")

from gi.repository import Gio

import json

DAY_LABELS = {
    "saturday": "Samstag",
    "wednesday": "Mittwoch",
    "tuesday": "Dienstag",
    "friday": "Freitag",
}


class Part3Mixin:
    """Part3 Mixin."""

    # ── ML-Genauigkeit ──

    def _load_accuracy(self, report: dict) -> None:
        """Accuracy-Stats async laden und anzeigen."""
        report_id = report.get("report_id", "")
        draw_day = report.get("draw_day", "")
        draw_date = report.get("draw_date", "")

        def worker():
            try:
                cached = self._cache_get(self._accuracy_cache, report_id)
                if cached is not None:
                    accuracy = cached
                elif self.api_client and report_id:
                    data = self.api_client.get_report_hits(report_id, 0)
                    accuracy = data.get("accuracy", {})
                    self._cache_set(self._accuracy_cache, report_id, accuracy)
                elif self.db:
                    accuracy = self.db.get_prediction_accuracy_stats(
                        draw_day, draw_date,
                    )
                    self._cache_set(self._accuracy_cache, report_id, accuracy)
                else:
                    accuracy = {}
                GLib.idle_add(self._populate_accuracy, accuracy)
            except Exception as e:
                logger.warning(f"Accuracy laden fehlgeschlagen: {e}")
                GLib.idle_add(self._populate_accuracy, {})

        threading.Thread(target=worker, daemon=True).start()

    def _populate_accuracy(self, accuracy: dict) -> bool:
        """Accuracy-Grid mit Stats fuellen (Main-Thread)."""
        # Guard: ignore stale callbacks (user already switched reports)
        if not self._selected_report:
            return False

        # Grid leeren (prevents stacking on fast switches)
        while True:
            child = self._accuracy_grid.get_first_child()
            if not child:
                break
            self._accuracy_grid.remove(child)

        total = accuracy.get("total", 0)
        if not total:
            self._accuracy_group.set_visible(False)
            return False

        stats_rows = [
            (_("Gesamt Tipps:"), str(total), "", ""),
            (_("6 Richtige:"), str(accuracy.get("matches_6", 0) or 0), "", ""),
            (
                _("5+ Richtige:"),
                str(accuracy.get("matches_5plus", 0) or 0),
                f"({(accuracy.get('matches_5plus', 0) or 0) / total * 100:.1f}%)" if total else "",
                "",
            ),
            (
                _("4+ Richtige:"),
                str(accuracy.get("matches_4plus", 0) or 0),
                f"({(accuracy.get('matches_4plus', 0) or 0) / total * 100:.1f}%)" if total else "",
                "",
            ),
            (
                _("3+ Richtige:"),
                str(accuracy.get("matches_3plus", 0) or 0),
                f"({(accuracy.get('matches_3plus', 0) or 0) / total * 100:.1f}%)" if total else "",
                "",
            ),
            (
                _("Nah (2er):"),
                str(accuracy.get("matches_2", 0) or 0),
                f"({(accuracy.get('matches_2', 0) or 0) / total * 100:.1f}%)" if total else "",
                "",
            ),
            (_("Avg Treffer:"), f"{accuracy.get('avg_matches', 0) or 0:.2f}", "", ""),
            ("Avg Confidence:", f"{accuracy.get('avg_confidence', 0) or 0:.1%}", "", ""),
        ]

        for i, (label_text, value_text, pct_text, _extra) in enumerate(stats_rows):
            lbl = Gtk.Label(label=label_text)
            lbl.add_css_class("dim-label")
            lbl.set_xalign(0)
            self._accuracy_grid.attach(lbl, 0, i, 1, 1)

            val = Gtk.Label(label=value_text)
            val.add_css_class("heading")
            val.set_xalign(0)
            self._accuracy_grid.attach(val, 1, i, 1, 1)

            if pct_text:
                pct = Gtk.Label(label=pct_text)
                pct.add_css_class("dim-label")
                pct.set_xalign(0)
                self._accuracy_grid.attach(pct, 2, i, 1, 1)

        self._accuracy_group.set_visible(True)
        return False

    # ── AI-Treffer-Analyse ──

    def _on_analyze_hits(self, button: Gtk.Button) -> None:
        """AI-Analyse der Treffer-Muster starten."""
        report = self._selected_report
        if not report:
            return

        report_id = report.get("report_id", "")

        button.set_sensitive(False)
        self._analyze_spinner.set_visible(True)
        self._analyze_spinner.start()
        self._ai_hits_label.set_visible(False)

        def worker():
            try:
                if self.api_client and report_id:
                    data = self.api_client.analyze_report_hits(report_id)
                    analysis = data.get("analysis", _("Keine Analyse verfügbar."))
                else:
                    analysis = _("AI-Treffer-Analyse ist nur im Server-Modus verfügbar.")
                GLib.idle_add(self._on_analyze_done, analysis, None)
            except Exception as e:
                GLib.idle_add(self._on_analyze_done, None, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_analyze_done(self, analysis: str | None, error: str | None) -> bool:
        """AI-Analyse abgeschlossen (Main-Thread)."""
        self._analyze_hits_btn.set_sensitive(True)
        self._analyze_spinner.stop()
        self._analyze_spinner.set_visible(False)

        if error:
            self._ai_hits_label.set_label(_("Fehler") + f": {error}")
        else:
            self._ai_hits_label.set_label(analysis or _("Keine Analyse verfügbar."))
        self._ai_hits_label.set_visible(True)
        return False

    # ── Markdown-Export ──

    def _on_export_markdown(self, _button: Gtk.Button) -> None:
        """Ausgewählten Bericht als Markdown-Datei exportieren."""
        report = self._selected_report
        if not report:
            return

        day_str = report.get("draw_day", "unbekannt")
        date_str = report.get("draw_date", "").replace(".", "-")
        suggested_name = f"bericht_{day_str[:2]}_{date_str}.md"
        md_content = self._build_report_markdown(report)

        dialog = Gtk.FileDialog()
        dialog.set_title(_("Bericht als Markdown exportieren"))
        dialog.set_initial_name(suggested_name)

        md_filter = Gtk.FileFilter()
        md_filter.set_name(_("Markdown-Dateien (*.md)"))
        md_filter.add_pattern("*.md")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(md_filter)
        dialog.set_filters(filters)

        dialog.save(self.get_root(), None, self._on_export_save_done, md_content)

    def _on_export_save_done(self, dialog: Gtk.FileDialog, result, md_content: str) -> None:
        """FileDialog-Save Callback — Datei schreiben."""
        try:
            gfile = dialog.save_finish(result)
            if gfile is None:
                return
            path = gfile.get_path()
            if not path:
                return
            # Endung sicherstellen
            if not path.endswith(".md"):
                path += ".md"
            with open(path, "w", encoding="utf-8") as f:
                f.write(md_content)

            toast = Adw.Toast(title=_("Bericht exportiert") + f": {path}")
            widget = self.get_parent()
            while widget:
                if isinstance(widget, Adw.ToastOverlay):
                    widget.add_toast(toast)
                    break
                widget = widget.get_parent()
            logger.info(f"Bericht als Markdown exportiert: {path}")
        except GLib.Error:
            # Benutzer hat Dialog abgebrochen
            pass
        except Exception as e:
            logger.warning(f"Markdown-Export fehlgeschlagen: {e}")
            toast = Adw.Toast(title=_("Export fehlgeschlagen") + f": {e}")
            widget = self.get_parent()
            while widget:
                if isinstance(widget, Adw.ToastOverlay):
                    widget.add_toast(toast)
                    break
                widget = widget.get_parent()

    def _build_report_markdown(self, report: dict) -> str:
        """Bericht-Daten als Markdown-String aufbereiten."""
        day_str = DAY_LABELS.get(report.get("draw_day", ""), report.get("draw_day", ""))
        lines = []
        lines.append(f"# Zyklus-Bericht: {day_str} — {report.get('draw_date', '')}")
        lines.append("")

        # Zusammenfassung
        lines.append("## Zusammenfassung")
        lines.append("")
        lines.append(f"- **Verglichene Tipps:** {report.get('predictions_compared', 0)}")
        lines.append(f"- **Beste Treffer:** {report.get('best_match', 0)} Richtige")
        lines.append(f"- **3+ Treffer:** {report.get('wins_3plus', 0)}x")
        lines.append(f"- **Erstellt:** {report.get('created_at', '')}")
        lines.append("")

        # Treffer-Kategorien
        match_cat = report.get("match_categories", "")
        if match_cat:
            try:
                if match_cat.startswith("{"):
                    cats = json.loads(match_cat)
                else:
                    cats = {}
                    for pair in match_cat.split(","):
                        if ":" in pair:
                            k, v = pair.strip().split(":", 1)
                            cats[k.strip()] = int(v.strip())
            except (json.JSONDecodeError, ValueError):
                cats = {}

            if cats:
                lines.append("## Trefferanalyse")
                lines.append("")
                lines.append("| Kategorie | Anzahl |")
                lines.append("|---|---|")
                for cat, count in sorted(cats.items(), key=lambda x: str(x[0]), reverse=True):
                    lines.append(f"| {cat} Richtige | {count} |")
                lines.append("")

        # AI-Zusammenfassung
        ai_summary = report.get("ai_summary", "")
        if ai_summary:
            lines.append("## AI-Analyse")
            lines.append("")
            lines.append(ai_summary)
            lines.append("")

        # Metadaten
        lines.append("---")
        lines.append("")
        lines.append(f"*Exportiert aus LottoAnalyzer — Ziehungstag: {day_str}, "
                      f"Spiel: {report.get('draw_day', '')}*")

        return "\n".join(lines)

    # ── Telegram senden ──

    def _on_telegram_send(self, button: Gtk.Button) -> None:
        """Ausgewählten Bericht per Telegram senden."""
        if not self._selected_report:
            return

        report = self._selected_report
        report_id = report.get("report_id")

        button.set_sensitive(False)
        self._spinner.set_visible(True)
        self._spinner.start()

        def worker():
            try:
                if self.api_client and report_id:
                    self.api_client.send_report_telegram(report_id)
                    GLib.idle_add(self._on_telegram_done, True, None)
                elif self.api_client:
                    text = self._format_report_text(report)
                    self.api_client.telegram_send(text)
                    GLib.idle_add(self._on_telegram_done, True, None)
                else:
                    # Standalone: direkt per Telegram Bot API senden
                    self._send_telegram_standalone(report)
                    GLib.idle_add(self._on_telegram_done, True, None)
            except Exception as e:
                GLib.idle_add(self._on_telegram_done, False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_telegram_done(self, success: bool, error: str | None) -> bool:
        """Telegram-Sende-Ergebnis (Main-Thread)."""
        self._telegram_btn.set_sensitive(True)
        self._spinner.stop()
        self._spinner.set_visible(False)

        msg = _("Bericht per Telegram gesendet") if success else _("Telegram-Fehler") + f": {error}"
        if not success:
            logger.warning(msg)

        toast = Adw.Toast(title=msg)
        widget = self.get_parent()
        while widget:
            if isinstance(widget, Adw.ToastOverlay):
                widget.add_toast(toast)
                break
            widget = widget.get_parent()

        return False

    def _send_telegram_standalone(self, report: dict) -> None:
        """Bericht direkt per Telegram Bot API senden (Standalone-Modus)."""
        tg_cfg = self.config_manager.config.telegram
        if not tg_cfg.enabled or not tg_cfg.bot_token:
            raise RuntimeError("Telegram nicht konfiguriert (Bot-Token fehlt)")
        chat_id = tg_cfg.notification_chat_id
        if not chat_id:
            raise RuntimeError("Telegram notification_chat_id nicht gesetzt")

        import requests

        # Detail-Hits und Accuracy laden
        draw_day = report.get("draw_day", "")
        draw_date = report.get("draw_date", "")
        hits = []
        accuracy = {}
        if self.db and draw_day and draw_date:
            hits = self.db.get_predictions_with_min_matches(draw_day, draw_date, 3)
            accuracy = self.db.get_prediction_accuracy_stats(draw_day, draw_date)

        text = self._format_report_text(report, hits=hits, accuracy=accuracy)
        url = f"https://api.telegram.org/bot{tg_cfg.bot_token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
        }, timeout=15)
        if not resp.ok:
            raise RuntimeError(f"Telegram API Fehler: {resp.status_code} — {resp.text[:200]}")

    @staticmethod
    def _format_report_text(
        report: dict,
        hits: list[dict] | None = None,
        accuracy: dict | None = None,
    ) -> str:
        """Bericht als lesbaren Text formatieren."""
        day_str = DAY_LABELS.get(report.get("draw_day", ""), report.get("draw_day", ""))
        lines = [
            f"{_('Bericht')}: {day_str} {report.get('draw_date', '')}",
            "",
            f"{_('Verglichen')}: {report.get('predictions_compared', 0)} {_('Tipps')}",
            f"{_('Beste Treffer')}: {report.get('best_match', 0)} {_('Richtige')}",
            f"3+ {_('Treffer')}: {report.get('wins_3plus', 0)}x",
        ]
        ai = report.get("ai_summary", "")
        if ai:
            lines.append("")
            lines.append(ai)

        # Detail-Treffer anhaengen
        if hits:
            lines.append("")
            lines.append(_("Detail-Treffer:"))
            for h in hits[:20]:
                pos = h.get("position", 0)
                mc = h.get("matches", 0)
                strategy = h.get("strategy", "?")
                conf = h.get("ml_confidence", 0) or 0
                pred_nums = h.get("predicted_numbers", "")
                lines.append(f"Tipp#{pos} {mc}er ({strategy}): {pred_nums} Conf:{conf:.0%}")

        # Accuracy-Stats anhaengen
        if accuracy:
            total = accuracy.get("total", 0)
            if total:
                m3p = accuracy.get("matches_3plus", 0) or 0
                m2 = accuracy.get("matches_2", 0) or 0
                avg_m = accuracy.get("avg_matches", 0) or 0
                lines.append("")
                lines.append(f"{_('Genauigkeit')} ({total} {_('Tipps')}):")
                lines.append(
                    f"3+: {m3p}x ({m3p / total * 100:.1f}%), "
                    f"{_('Nah(2er)')}: {m2}x, Avg: {avg_m:.2f}"
                )

        return "\n".join(lines)

