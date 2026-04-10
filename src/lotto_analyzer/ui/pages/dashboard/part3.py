"""UI-Seite dashboard: part3."""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_analyzer.ui.ui_helpers import show_toast

logger = get_logger("dashboard.part3")

from gi.repository import Gio


class Part3Mixin:
    """Part3 Mixin."""

    def _update_performance_chart(self, perf_data: list[dict]) -> None:
        """Strategie-Performance Bar-Chart und Zusammenfassung aktualisieren."""
        # Strategien aggregieren (bei mehreren Tagen Durchschnitt bilden)
        strategy_agg: dict[str, list[float]] = {}
        strategy_wins: dict[str, tuple[int, int]] = {}  # (win_count, total)
        for entry in perf_data:
            strat = entry.get("strategy", "?")
            avg = entry.get("avg_matches", 0.0)
            wins = entry.get("win_count", 0)
            total = entry.get("total_predictions", 0)
            strategy_agg.setdefault(strat, []).append(avg)
            prev_w, prev_t = strategy_wins.get(strat, (0, 0))
            strategy_wins[strat] = (prev_w + wins, prev_t + total)

        strategies = sorted(strategy_agg.keys())
        avg_values = [
            sum(strategy_agg[s]) / len(strategy_agg[s]) for s in strategies
        ]

        # Beste Strategie hervorheben
        best_idx = avg_values.index(max(avg_values)) if avg_values else -1

        self._perf_chart.plot_bar(
            strategies, avg_values,
            title=_("Avg. Treffer pro Strategie"),
            xlabel=_("Strategie"), ylabel=_("Avg. Treffer"),
            highlight_indices=[best_idx] if best_idx >= 0 else None,
        )

        # Zusammenfassung
        if strategies and best_idx >= 0:
            best_strat = strategies[best_idx]
            best_avg = avg_values[best_idx]
            wins, total = strategy_wins.get(best_strat, (0, 0))
            win_rate = (wins / total * 100) if total > 0 else 0.0
            self._perf_summary_row.set_subtitle(
                f"{best_strat} — Avg: {best_avg:.2f} Treffer, "
                f"Gewinnrate: {win_rate:.1f}% ({wins}/{total})"
            )
        else:
            self._perf_summary_row.set_subtitle(_("Keine Daten vorhanden"))

    def _update_activity_log(self, entries: list[dict]) -> None:
        """Aktivitätslog-Zeilen im UI aktualisieren."""
        # Alte Zeilen entfernen
        for row in self._activity_rows:
            self._activity_group.remove(row)
        self._activity_rows.clear()

        _status_icons = {
            "success": "emblem-ok-symbolic",
            "error": "dialog-error-symbolic",
            "no_change": "content-loading-symbolic",
        }
        _action_labels = {
            "crawl": _("Ziehungen"),
            "jackpot_check": _("Jackpot"),
            "gewinnquoten": _("Gewinnquoten"),
            "ej_gewinnquoten": _("EJ-Gewinnquoten"),
        }

        for e in entries:
            ts = e.get("timestamp", "?")
            try:
                from datetime import datetime
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                ts_short = dt.strftime("%d.%m. %H:%M")
            except Exception as e:
                logger.warning(f"Timestamp-Parsing fehlgeschlagen: {e}")
                ts_short = ts

            action_label = _action_labels.get(e.get("action", ""), e.get("action", "?"))
            source = e.get("source", "?")
            details = e.get("details", "")
            status = e.get("status", "success")
            icon_name = _status_icons.get(status, "dialog-question-symbolic")

            row = Adw.ActionRow(
                title=f"{action_label} \u2014 {source}",
                subtitle=f"{ts_short}  {details}" if details else ts_short,
            )
            row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
            self._activity_group.add(row)
            self._activity_rows.append(row)

        if not entries:
            row = Adw.ActionRow(
                title=_("Keine Einträge"),
                subtitle=_("Server hat noch keine externen Daten abgerufen"),
            )
            self._activity_group.add(row)
            self._activity_rows.append(row)

    def _on_send_activity_telegram(self, btn) -> None:
        """Aktivitätsprotokoll per Telegram senden."""
        def worker():
            try:
                if self.api_client:
                    self.api_client.send_activity_log_telegram()
                    GLib.idle_add(self._show_activity_toast, _("Aktivitätsprotokoll an Telegram gesendet"))
                else:
                    GLib.idle_add(self._show_activity_toast, _("Nur im Client-Modus verfügbar"))
            except Exception as e:
                GLib.idle_add(self._show_activity_toast, f"Fehler: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _show_activity_toast(self, message: str) -> bool:
        """Toast-Nachricht anzeigen."""
        show_toast(self, message)
        return False

    def _update_countdown(self) -> bool:
        """Countdown zur nächsten Ziehung aktualisieren."""
        if not self._next_draw_dt:
            self._countdown_label.set_label("")
            return True

        from datetime import datetime as _dt
        now = _dt.now()
        diff = self._next_draw_dt - now
        total_secs = int(diff.total_seconds())

        if total_secs <= 0:
            self._countdown_label.set_label(_("JETZT!"))
            for css in ("error", "warning", "success"):
                self._countdown_label.remove_css_class(css)
            self._countdown_label.add_css_class("error")
            return True

        days = total_secs // 86400
        hours = (total_secs % 86400) // 3600
        mins = (total_secs % 3600) // 60

        if days > 0:
            text = f"{days}T {hours}h {mins}m"
        elif hours > 0:
            text = f"{hours}h {mins}m"
        else:
            text = f"{mins}m"

        self._countdown_label.set_label(text)

        # Desktop-Benachrichtigungen
        if total_secs < 3600 and not self._notified_1h:
            self._notified_1h = True
            self._send_draw_notification(
                _("Lotto Ziehung in Kuerze!"),
                _("Die nächste Ziehung ist in %dm") % mins,
            )
        elif total_secs < 10800 and not self._notified_3h:
            self._notified_3h = True
            self._send_draw_notification(
                _("Lotto Ziehung bald!"),
                _("Die nächste Ziehung ist in %dh %dm") % (hours, mins),
            )

        # Farbe je nach Dringlichkeit
        for css in ("error", "warning", "success"):
            self._countdown_label.remove_css_class(css)
        if total_secs < 3600:
            self._countdown_label.add_css_class("error")
        elif total_secs < 86400:
            self._countdown_label.add_css_class("warning")

        return True  # Timer wiederholen

    def _send_draw_notification(self, title: str, body: str) -> None:
        """Desktop-Benachrichtigung via Gio.Notification senden."""
        try:
            root = self.get_root()
            app = root.get_application() if root else None
            if app:
                notification = Gio.Notification.new(title)
                notification.set_body(body)
                notification.set_priority(Gio.NotificationPriority.HIGH)
                app.send_notification("draw-countdown", notification)
        except Exception as e:
            logger.warning(f"Desktop-Benachrichtigung fehlgeschlagen: {e}")

    @staticmethod
    def _format_prizes_summary(prizes: list[dict]) -> str:
        """Gewinnquoten-Zusammenfassung für Dashboard-Zeile formatieren.

        Zeigt: Datum | Kl.1-3 kompakt | Spieleinsatz
        """
        if not prizes:
            return _("Keine Daten")

        draw_date = prizes[0].get("draw_date", "")
        # Datum kuerzen: "2026-03-11" → "11.03."
        try:
            from datetime import datetime
            d = datetime.strptime(draw_date, "%Y-%m-%d").date()
            date_str = d.strftime("%d.%m.")
        except (ValueError, TypeError):
            date_str = draw_date

        parts = [date_str]
        for p in prizes[:3]:
            cn = p.get("class_number", 0)
            is_jp = p.get("is_jackpot", 0)
            amount = p.get("prize_amount", 0.0)
            winners = p.get("winner_count", 0)
            if is_jp:
                parts.append(f"Kl.{cn}: Jackpot")
            elif amount > 0:
                # Kompakte Formatierung: Mio/k
                if amount >= 1_000_000:
                    amt_str = f"{amount / 1_000_000:.1f} Mio."
                elif amount >= 1_000:
                    amt_str = f"{amount / 1_000:.0f}k"
                else:
                    amt_str = f"{amount:,.0f}".replace(",", ".")
                parts.append(f"Kl.{cn}: {amt_str} ({winners}x)")
            else:
                parts.append(f"Kl.{cn}: 0 EUR")

        # Spieleinsatz
        total_stakes = prizes[0].get("total_stakes", 0.0)
        if total_stakes > 0:
            if total_stakes >= 1_000_000:
                stakes_str = f"{total_stakes / 1_000_000:.1f} Mio."
            else:
                stakes_str = (
                    f"{total_stakes:,.0f}".replace(",", "X")
                    .replace(".", ",").replace("X", ".")
                )
            parts.append(_("Einsatz: %s") % stakes_str)

        return " | ".join(parts)

    # ══════════════════════════════════════════════
    # Jackpot-Detail-Popup
    # ══════════════════════════════════════════════

    def _on_jackpot_info_clicked(self, button: Gtk.Button, day_str: str) -> None:
        """(i)-Button Klick: Gewinnquoten-Popup oeffnen."""
        _day_to_game = {
            "saturday": "6aus49", "wednesday": "6aus49",
            "tuesday": "eurojackpot", "friday": "eurojackpot",
        }

        def worker():
            prizes = []
            live_jackpot: dict = {}
            try:
                if self.api_client:
                    resp = self.api_client.get_latest_prizes(day_str)
                    prizes = resp.get("prizes", [])
                elif self.db:
                    prizes = self.db.get_latest_prizes(day_str)
            except Exception as e:
                logger.warning(f"Gewinnquoten laden fehlgeschlagen ({day_str}): {e}")
            # Live-Jackpot
            try:
                if self.api_client:
                    all_jp = self.api_client.get_live_jackpot()
                    game_key = _day_to_game.get(day_str, "")
                    info = all_jp.get(game_key, {})
                    if info and info.get("next_day", "") == day_str:
                        live_jackpot = {
                            "next_jackpot_mio": info.get("next_mio", 0),
                            "next_date": info.get("next_date", ""),
                            "next_day_str": info.get("next_day", ""),
                        }
                elif self.app_db:
                    game_key = _day_to_game.get(day_str, "")
                    next_day = self.app_db.get_setting(f"jackpot_{game_key}_next_day", "")
                    if next_day == day_str:
                        mio_str = self.app_db.get_setting(f"jackpot_{game_key}_next_mio", "0")
                        mio = float(mio_str) if mio_str else 0.0
                        if mio > 0:
                            live_jackpot = {
                                "next_jackpot_mio": mio,
                                "next_date": self.app_db.get_setting(f"jackpot_{game_key}_next_date", ""),
                                "next_day_str": next_day,
                            }
            except Exception as e:
                logger.warning(f"Live-Jackpot laden fehlgeschlagen ({day_str}): {e}")
            GLib.idle_add(self._show_prizes_dialog, day_str, prizes, live_jackpot)

        threading.Thread(target=worker, daemon=True).start()

    def _show_prizes_dialog(self, day_str: str, prizes: list[dict], live_jackpot: dict | None = None) -> bool:
        """Popup mit allen Gewinnklassen anzeigen."""
        _full_names = {
            "saturday": _("Samstag"), "wednesday": _("Mittwoch"),
            "tuesday": _("Dienstag"), "friday": _("Freitag"),
        }
        full_name = _full_names.get(day_str, day_str)

        # Datum aus Daten
        draw_date = ""
        if prizes:
            raw = prizes[0].get("draw_date", "")
            try:
                from datetime import datetime
                d = datetime.strptime(raw, "%Y-%m-%d").date()
                draw_date = d.strftime("%d.%m.%Y")
            except (ValueError, TypeError):
                draw_date = raw

        dialog = Adw.Dialog()
        dialog.set_title(_("Gewinnquoten %s") % full_name + f" — {draw_date}")
        dialog.set_content_width(620)
        dialog.set_content_height(520)

        # Toolbar-View für Header-Bar
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)
        dialog.set_child(toolbar)

        if not prizes:
            # Keine Daten
            empty = Adw.StatusPage(
                title=_("Keine Gewinnquoten"),
                description=_("Für diesen Ziehungstag liegen keine Daten vor."),
                icon_name="dialog-information-symbolic",
            )
            toolbar.set_content(empty)
            window = self.get_root()
            if window:
                dialog.present(window)
            return False

        # Popup-Schriftgröße aus Config
        popup_font_size = self.config_manager.config.popup_font_size

        # Outer box: Banner + ScrolledWindow
        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        toolbar.set_content(outer_box)

        # CSS-Provider für Schriftgröße (vor Bannern laden)
        css = (
            f"label.popup-text {{ font-size: {popup_font_size}pt; }} "
            f"label.popup-header {{ font-size: {popup_font_size}pt; font-weight: bold; }} "
            f"label.popup-jackpot {{ font-size: {popup_font_size}pt; color: @error_color; font-weight: bold; }} "
            f"label.popup-banner {{ font-size: {popup_font_size + 2}pt; font-weight: bold; color: @success_color; }}"
        )
        provider = Gtk.CssProvider()
        provider.load_from_string(css)
        Gtk.StyleContext.add_provider_for_display(
            outer_box.get_display(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Jackpot-Banner: Angebotener Jackpot-Betrag aus Live-API
        next_jackpot_mio = (live_jackpot or {}).get("next_jackpot_mio", 0)
        if next_jackpot_mio > 0:
            _day_labels_de = {
                "saturday": _("Samstag"), "wednesday": _("Mittwoch"),
                "tuesday": _("Dienstag"), "friday": _("Freitag"),
            }
            next_date_raw = (live_jackpot or {}).get("next_date", "")
            next_day_str = (live_jackpot or {}).get("next_day_str", "")
            banner_day = _day_labels_de.get(next_day_str, "")
            banner_date = ""
            if next_date_raw:
                try:
                    from datetime import datetime
                    _d = datetime.strptime(next_date_raw, "%Y-%m-%d").date()
                    banner_date = _d.strftime("%d.%m.")
                except (ValueError, TypeError):
                    pass
            date_part = f" ({banner_day}, {banner_date})" if banner_day and banner_date else ""
            banner_label = Gtk.Label(
                label=f"Jackpot: ~{next_jackpot_mio:.0f} Mio. EUR{date_part}",
                halign=Gtk.Align.CENTER,
            )
            banner_label.add_css_class("popup-banner")
            banner_label.set_margin_top(12)
            banner_label.set_margin_bottom(8)
            outer_box.append(banner_label)
            outer_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # ScrolledWindow mit Grid
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer_box.append(scrolled)

        grid = Gtk.Grid()
        grid.set_row_spacing(6)
        grid.set_column_spacing(16)
        grid.set_margin_top(16)
        grid.set_margin_bottom(16)
        grid.set_margin_start(16)
        grid.set_margin_end(16)
        scrolled.set_child(grid)

        def _header_label(text: str) -> Gtk.Label:
            lbl = Gtk.Label(label=text, xalign=0)
            lbl.add_css_class("popup-header")
            return lbl

        def _cell_label(text: str, css_class: str = "popup-text") -> Gtk.Label:
            lbl = Gtk.Label(label=text, xalign=0)
            lbl.add_css_class(css_class)
            lbl.set_selectable(True)
            return lbl

        # Header-Zeile
        for col, title in enumerate([_("Klasse"), _("Beschreibung"), _("Gewinner"), _("Betrag")]):
            grid.attach(_header_label(title), col, 0, 1, 1)

        # Daten-Zeilen
        for i, p in enumerate(prizes, 1):
            cn = p.get("class_number", 0)
            desc = p.get("description", "")
            winners = p.get("winner_count", 0)
            amount = p.get("prize_amount", 0.0)
            is_jp = p.get("is_jackpot", 0)

            grid.attach(_cell_label(f"Kl. {cn}"), 0, i, 1, 1)
            grid.attach(_cell_label(desc), 1, i, 1, 1)
            grid.attach(_cell_label(f"{winners:,}x".replace(",", ".")), 2, i, 1, 1)

            if is_jp:
                grid.attach(_cell_label(_("Unbesetzt (Jackpot)"), "popup-jackpot"), 3, i, 1, 1)
            elif amount > 0:
                amt_str = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"
                grid.attach(_cell_label(amt_str), 3, i, 1, 1)
            else:
                grid.attach(_cell_label("0,00 EUR"), 3, i, 1, 1)

        # Spieleinsatz-Zeile
        total_stakes = prizes[0].get("total_stakes", 0.0)
        if total_stakes > 0:
            row_idx = len(prizes) + 1
            # Separator
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            grid.attach(sep, 0, row_idx, 4, 1)
            row_idx += 1
            grid.attach(_header_label(_("Spieleinsatz")), 0, row_idx, 2, 1)
            stakes_str = f"{total_stakes:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"
            grid.attach(_cell_label(stakes_str), 2, row_idx, 2, 1)

        window = self.get_root()
        if window:
            dialog.present(window)
        return False

    def cleanup(self) -> None:
        """Alle Timer entfernen — wird beim Seitenwechsel/Beenden aufgerufen."""
        super().cleanup()
        if self._countdown_timer_id:
            GLib.source_remove(self._countdown_timer_id)
            self._countdown_timer_id = 0

    def _on_refresh(self, button: Gtk.Button) -> None:
        """Daten neu laden."""
        self._load_data()
