"""UI-Seite scraper: part3."""

from __future__ import annotations

import threading
from datetime import date, datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.game_config import get_config
from lotto_common.config import ConfigManager
from lotto_common.models.draw import DrawDay
from lotto_common.models.game_config import GameType, get_config


logger = get_logger("scraper.part3")
from collections import Counter

DAY_LABELS = {
    "saturday": "Samstag",
    "wednesday": "Mittwoch",
    "tuesday": "Dienstag",
    "friday": "Freitag",
}


class Part3Mixin:
    """Part3 Mixin."""

    def _stop_ai_spinner(self) -> bool:
        """AI-Panel-Spinner stoppen (Main-Thread, GLib.idle_add kompatibel)."""
        self._ai_panel._spinner.stop()
        self._ai_panel._spinner.set_visible(False)
        return False

    def _on_verify_source_vs_db(self, button: Gtk.Button) -> None:
        """Quelle-vs-DB Verifikation starten."""
        self._verify_btn.set_sensitive(False)

        def worker():
            try:
                report = self._verify_source_vs_db()
                if self._ai_analyst or self.api_client:
                    prompt = f"""Du bist ein Datenqualitaets-Pruefer für Lotto 6aus49.

Hier ist ein Verifikationsbericht — er vergleicht die Daten aus der Quelle (Webseite oder CSV)
mit dem was in der SQLite-Datenbank gespeichert wurde.

{report}

Pruefe bitte:
1. Stimmen die Quelldaten mit der DB ueberein? Gab es Datenverluste beim Speichern?
2. Wenn Abweichungen: Sind die Quell- oder DB-Daten korrekt? (6 verschiedene Zahlen 1-49, SZ 0-9)
3. Wenn Daten fehlen: Warum koennten sie nicht gespeichert worden sein? (Duplikat? Format-Fehler?)
4. Fazit: Ist die Daten-Pipeline zuverlässig?

Antworte auf Deutsch, kurz und praezise."""
                    try:
                        result = self._ai_chat(prompt)
                        GLib.idle_add(self._ai_panel.set_result, result)
                    except Exception as e:
                        GLib.idle_add(self._ai_panel.set_result, f"{report}\n\n---\nAI-Fehler: {e}")
                else:
                    GLib.idle_add(self._ai_panel.set_result, report)
            except Exception as e:
                logger.warning(f"Verifikation fehlgeschlagen: {e}")
                GLib.idle_add(self._ai_panel.set_result, f"Verifikation fehlgeschlagen: {e}")
            finally:
                GLib.idle_add(self._verify_btn.set_sensitive, True)
                GLib.idle_add(self._stop_ai_spinner)

        self._ai_panel.set_result(_("Verifikation läuft..."))
        self._ai_panel._spinner.set_visible(True)
        self._ai_panel._spinner.start()
        threading.Thread(target=worker, daemon=True).start()

    # ═══════════════════════════════════════════
    # AI-Kontrolle 2: DB-Qualitätspruefung
    # ═══════════════════════════════════════════

    def _build_quality_report(self) -> str:
        """Datenqualitaetsbericht."""
        if not self.db:
            return _("Keine Datenbank verfügbar.")

        lines = ["=== DB-QUALITAETSBERICHT ===\n"]

        for day_str in self._config.draw_days:
            day = DrawDay(day_str)
            day_name = DAY_LABELS.get(day_str, day_str)
            draws = self.db.get_draws(day)
            lines.append(f"--- {day_name} ({len(draws)} Ziehungen) ---")

            if not draws:
                lines.append("  Keine Daten vorhanden.\n")
                continue

            dates = sorted(d.draw_date for d in draws)
            lines.append(f"  Zeitraum: {dates[0]} bis {dates[-1]}")

            # Pro Jahr
            year_counts = Counter(d.draw_date.year for d in draws)
            lines.append(f"  Ziehungen pro Jahr:")
            incomplete = []
            for year in sorted(year_counts):
                count = year_counts[year]
                current_year = date.today().year
                status = ""
                if year < current_year and count < 50:
                    status = f" ⚠️ UNVOLLSTAENDIG (erwartet ~52)"
                    incomplete.append(year)
                elif year == current_year:
                    status = " (laufendes Jahr)"
                lines.append(f"    {year}: {count}{status}")

            # Lücken
            gaps = []
            for i in range(1, len(dates)):
                diff = (dates[i] - dates[i-1]).days
                if diff > 10:
                    gaps.append((dates[i-1], dates[i], diff))
            if gaps:
                lines.append(f"  Lücken (>10 Tage):")
                for d1, d2, diff in gaps[:10]:
                    lines.append(f"    {d1} → {d2} ({diff} Tage)")
                if len(gaps) > 10:
                    lines.append(f"    ... und {len(gaps)-10} weitere")

            # Duplikate
            date_counts = Counter(d.draw_date for d in draws)
            dupes = {dt: c for dt, c in date_counts.items() if c > 1}
            if dupes:
                lines.append(f"  ⚠️ Duplikate:")
                for dt, c in sorted(dupes.items()):
                    lines.append(f"    {dt}: {c}x")

            # Zahlen-Validierung
            mc = self._config.main_count
            mn = self._config.main_min
            mx = self._config.main_max
            bad = []
            for d in draws:
                if len(d.numbers) != mc:
                    bad.append((d.draw_date, f"{len(d.numbers)} Zahlen statt {mc}"))
                elif len(set(d.numbers)) != mc:
                    bad.append((d.draw_date, f"Duplikat-Zahlen: {d.numbers}"))
                elif any(n < mn or n > mx for n in d.numbers):
                    bad.append((d.draw_date, f"Ungültige Zahl: {d.numbers}"))
            if bad:
                lines.append(f"  ⚠️ Fehlerhafte Ziehungen ({len(bad)}):")
                for dt, reason in bad[:5]:
                    lines.append(f"    {dt}: {reason}")

            # Superzahl
            has_sz = sum(1 for d in draws if d.super_number is not None)
            lines.append(f"  Superzahl: {has_sz}/{len(draws)}")

            if incomplete:
                lines.append(f"  Nachcrawlen empfohlen: {incomplete}")
            lines.append("")

        total = 0
        parts = []
        _day_abbrev = {
            "saturday": "Sa", "wednesday": "Mi",
            "tuesday": "Di", "friday": "Fr",
        }
        for day_str in self._config.draw_days:
            day = DrawDay(day_str)
            cnt = self.db.get_draw_count(day)
            total += cnt
            abbr = _day_abbrev.get(day_str, day_str[:2])
            parts.append(f"{cnt} {abbr}")
        lines.append(f"GESAMT: {' + '.join(parts)} = {total} Ziehungen")
        return "\n".join(lines)

    def _on_ai_quality_check(self, button: Gtk.Button) -> None:
        """DB-Qualitätspruefung."""
        if not self.db and not self.api_client:
            self._ai_panel.set_result(_("Keine Datenbank verfügbar."))
            return

        self._quality_btn.set_sensitive(False)

        def worker():
            try:
                if self.api_client and not self.db:
                    report = self._build_quality_report_api()
                else:
                    report = self._build_quality_report()
                if self._ai_analyst or self.api_client:
                    prompt = f"""Du bist ein Datenqualitaets-Experte für Lotto 6aus49.

{report}

Analysiere:
1. Vollständigkeit: Welche Jahre/Zeiträume fehlen?
2. Lücken und Anomalien?
3. Zahlen plausibel? (6 verschiedene 1-49, Superzahl 0-9)
4. Datenqualitaet bewerten (Note 1-5, 1=perfekt)
5. Empfehlung: Was muss nachgecrawlt werden?

Antworte auf Deutsch, kurz und praezise."""
                    try:
                        result = self._ai_chat(prompt)
                        GLib.idle_add(self._ai_panel.set_result, result)
                    except Exception as e:
                        GLib.idle_add(self._ai_panel.set_result, f"{report}\n\n---\nAI-Fehler: {e}")
                else:
                    GLib.idle_add(self._ai_panel.set_result, report)
            except Exception as e:
                logger.warning(f"Qualitätspruefung fehlgeschlagen: {e}")
                GLib.idle_add(self._ai_panel.set_result, f"Qualitätspruefung fehlgeschlagen: {e}")
            finally:
                GLib.idle_add(self._quality_btn.set_sensitive, True)
                GLib.idle_add(self._stop_ai_spinner)

        self._ai_panel.set_result(_("Qualitätspruefung läuft..."))
        self._ai_panel._spinner.set_visible(True)
        self._ai_panel._spinner.start()
        threading.Thread(target=worker, daemon=True).start()

    # ═══════════════════════════════════════════
    # AI-Kontrolle 3: DB-Anomalie-Prüfung (AI)
    # ═══════════════════════════════════════════

    def _build_anomaly_report(self) -> str:
        """Detaillierter Anomalie-Bericht: Duplikate, Wochentag-Fehler, Ausreisser."""
        if not self.db:
            return _("Keine Datenbank verfügbar.")

        lines = ["=== DB-ANOMALIE-BERICHT ===\n"]

        _weekday_map = {"saturday": 5, "wednesday": 2, "tuesday": 1, "friday": 4}

        for day_str in self._config.draw_days:
            day = DrawDay(day_str)
            day_name = DAY_LABELS.get(day_str, day_str)
            draws = self.db.get_draws(day)
            lines.append(f"--- {day_name} ({len(draws)} Ziehungen) ---")

            if not draws:
                lines.append("  Keine Daten.\n")
                continue

            # 1) Duplikate: gleiche draw_date
            date_groups: dict = {}
            for d in draws:
                date_groups.setdefault(d.draw_date, []).append(d)
            dupes = {dt: grp for dt, grp in date_groups.items() if len(grp) > 1}
            if dupes:
                lines.append(f"  DUPLIKATE ({len(dupes)} Daten):")
                for dt, grp in sorted(dupes.items()):
                    nums_list = [str(g.numbers) for g in grp]
                    lines.append(f"    {dt}: {len(grp)}x — Zahlen: {', '.join(nums_list)}")
            else:
                lines.append("  Duplikate: keine")

            # 2) Falscher Wochentag: Datum passt nicht zum erwarteten Wochentag
            expected_wd = _weekday_map.get(day_str)
            wrong_days = []
            if expected_wd is not None:
                for d in draws:
                    if d.draw_date.weekday() != expected_wd:
                        actual = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][d.draw_date.weekday()]
                        wrong_days.append((d.draw_date, actual))
            if wrong_days:
                lines.append(f"  FALSCHER WOCHENTAG ({len(wrong_days)}):")
                for dt, actual in wrong_days[:10]:
                    lines.append(f"    {dt} ist {actual}, erwartet {day_name}")
                if len(wrong_days) > 10:
                    lines.append(f"    ... und {len(wrong_days) - 10} weitere")
            else:
                lines.append("  Wochentage: alle korrekt")

            # 3) Zahlen-Ausreisser
            mc = self._config.main_count
            mn = self._config.main_min
            mx = self._config.main_max
            anomalies = []
            for d in draws:
                issues = []
                if len(d.numbers) != mc:
                    issues.append(f"{len(d.numbers)} statt {mc} Zahlen")
                if len(set(d.numbers)) != len(d.numbers):
                    issues.append(f"doppelte Zahlen: {d.numbers}")
                out_of_range = [n for n in d.numbers if n < mn or n > mx]
                if out_of_range:
                    issues.append(f"ausserhalb {mn}-{mx}: {out_of_range}")
                # Bonus-Check
                if self._config.bonus_count > 1 and d.bonus_numbers:
                    if len(d.bonus_numbers) != self._config.bonus_count:
                        issues.append(f"{len(d.bonus_numbers)} statt {self._config.bonus_count} {self._config.bonus_name}")
                    out_bonus = [b for b in d.bonus_numbers if b < self._config.bonus_min or b > self._config.bonus_max]
                    if out_bonus:
                        issues.append(f"{self._config.bonus_name} ausserhalb {self._config.bonus_min}-{self._config.bonus_max}: {out_bonus}")
                elif d.super_number is not None:
                    if d.super_number < self._config.bonus_min or d.super_number > self._config.bonus_max:
                        issues.append(f"Superzahl {d.super_number} ausserhalb {self._config.bonus_min}-{self._config.bonus_max}")
                if issues:
                    anomalies.append((d.draw_date, issues))

            if anomalies:
                lines.append(f"  ZAHLEN-ANOMALIEN ({len(anomalies)}):")
                for dt, issues in anomalies[:10]:
                    lines.append(f"    {dt}: {'; '.join(issues)}")
                if len(anomalies) > 10:
                    lines.append(f"    ... und {len(anomalies) - 10} weitere")
            else:
                lines.append("  Zahlen-Anomalien: keine")

            # 4) Verdaechtige Daten-Muster (gleiche Zahlen an verschiedenen Tagen)
            nums_set_counts: dict = {}
            for d in draws:
                key = tuple(sorted(d.numbers))
                nums_set_counts.setdefault(key, []).append(d.draw_date)
            repeated = {k: v for k, v in nums_set_counts.items() if len(v) > 1}
            if repeated:
                lines.append(f"  GLEICHE ZAHLENKOMBINATION ({len(repeated)}):")
                for nums, dates in sorted(repeated.items(), key=lambda x: -len(x[1]))[:5]:
                    lines.append(f"    {list(nums)}: {len(dates)}x ({', '.join(str(d) for d in dates[:3])}{'...' if len(dates)>3 else ''})")
            else:
                lines.append("  Zahlenkombinationen: alle einmalig")

            lines.append("")

        return "\n".join(lines)

    def _on_ai_anomaly_check(self, button: Gtk.Button) -> None:
        """AI-gestuetzte DB-Anomalie-Prüfung."""
        if not self.db and not self.api_client:
            self._ai_panel.set_result(_("Keine Datenbank verfügbar."))
            return

        self._anomaly_btn.set_sensitive(False)

        def worker():
            try:
                if self.api_client and not self.db:
                    report = self._build_quality_report_api()
                else:
                    report = self._build_anomaly_report()
                if self._ai_analyst or self.api_client:
                    game_name = self._config.display_name
                    prompt = f"""Du bist ein Datenbank-Experte für {game_name}-Lottozahlen.

{report}

Pruefe gruendlich auf Anomalien:
1. Gibt es Duplikate (gleiche Daten)? Falls ja: Welche müssen gelöscht werden?
2. Stimmen die Wochentage? (z.B. Samstag-Ziehungen müssen am Samstag stattfinden)
3. Sind alle Zahlen im gültigen Bereich? Gibt es verdaechtige Muster?
4. Gibt es identische Zahlenkombinationen — ist das statistisch plausibel?
5. Gesamtbewertung: Ist die Datenbank konsistent und fehlerfrei?
6. Konkrete Handlungsempfehlungen falls Probleme gefunden wurden.

Antworte auf Deutsch, strukturiert und praezise."""
                    try:
                        result = self._ai_chat(prompt)
                        GLib.idle_add(self._ai_panel.set_result, result)
                    except Exception as e:
                        GLib.idle_add(self._ai_panel.set_result, f"{report}\n\n---\nAI-Fehler: {e}")
                else:
                    GLib.idle_add(self._ai_panel.set_result, report)
            except Exception as e:
                logger.warning(f"Anomalie-Prüfung fehlgeschlagen: {e}")
                GLib.idle_add(self._ai_panel.set_result, f"Anomalie-Prüfung fehlgeschlagen: {e}")
            finally:
                GLib.idle_add(self._anomaly_btn.set_sensitive, True)
                GLib.idle_add(self._stop_ai_spinner)

        self._ai_panel.set_result(_("AI-Anomalie-Prüfung läuft..."))
        self._ai_panel._spinner.set_visible(True)
        self._ai_panel._spinner.start()
        threading.Thread(target=worker, daemon=True).start()

    # ═══════════════════════════════════════════
    # AI-Kontrolle 4: Statistik-Datengrundlage
    # ═══════════════════════════════════════════

    def _on_check_stat_data(self, button: Gtk.Button) -> None:
        """Prüfen ob die Daten für Statistik-Analyse korrekt sind."""
        if not self.db and not self.api_client:
            self._ai_panel.set_result(_("Keine Datenbank verfügbar."))
            return

        self._stat_check_btn.set_sensitive(False)

        def worker():
            try:
                if self.api_client and not self.db:
                    report = self._build_stat_verification_api()
                else:
                    report = self._build_stat_verification()
                if self._ai_analyst or self.api_client:
                    prompt = f"""Du bist ein Lotto-Datenanalyst. Pruefe ob die Datengrundlage für die
Statistik-Analyse korrekt und zuverlässig ist.

{report}

Pruefe bitte:
1. Sind genug Daten für eine aussagekraeftige Statistik vorhanden? (Minimum ~100 Ziehungen)
2. Sind die Häufigkeitsverteilungen plausibel? (Bei 6 aus 49 sollte jede Zahl ca. 12.2% der Ziehungen vorkommen)
3. Stimmt die Superzahl-Verteilung? (Gleichverteilt 0-9, ca. 10% pro Zahl)
4. Gibt es Hinweise auf Datenprobleme die die Statistik verfaelschen koennten?
5. Fazit: Kann man der Statistik-Analyse vertrauen?

Antworte auf Deutsch, kurz und praezise."""
                    try:
                        result = self._ai_chat(prompt)
                        GLib.idle_add(self._ai_panel.set_result, result)
                    except Exception as e:
                        GLib.idle_add(self._ai_panel.set_result, f"{report}\n\n---\nAI-Fehler: {e}")
                else:
                    GLib.idle_add(self._ai_panel.set_result, report)
            except Exception as e:
                logger.warning(f"Statistik-Prüfung fehlgeschlagen: {e}")
                GLib.idle_add(self._ai_panel.set_result, f"Statistik-Prüfung fehlgeschlagen: {e}")
            finally:
                GLib.idle_add(self._stat_check_btn.set_sensitive, True)
                GLib.idle_add(self._stop_ai_spinner)

        self._ai_panel.set_result(_("Statistik-Datengrundlage wird geprüft..."))
        self._ai_panel._spinner.set_visible(True)
        self._ai_panel._spinner.start()
        threading.Thread(target=worker, daemon=True).start()

    def _build_stat_verification(self) -> str:
        """Bericht: Sind die Daten für die Statistik-Analyse korrekt?

        Ohne StatisticsEngine nur Basisdaten (Anzahl, Zeitraum) liefern.
        Vollständige Analyse nur via API verfügbar.
        """
        logger.warning("Statistik-Verifikation: StatisticsEngine nicht verfügbar (core-Import entfernt)")

        lines = ["=== STATISTIK-DATENGRUNDLAGE ===\n"]

        for day_str in self._config.draw_days:
            day = DrawDay(day_str)
            day_name = DAY_LABELS.get(day_str, day_str)
            draws = self.db.get_draws(day)
            lines.append(f"--- {day_name}: {len(draws)} Ziehungen ---")

            if len(draws) < 10:
                lines.append("  Zu wenig Daten für Statistik!\n")
                continue

            # Basisdaten ohne StatisticsEngine
            dates = sorted(d.draw_date for d in draws)
            lines.append(f"  Zeitraum: {dates[0]} bis {dates[-1]}")

            # Häufigkeitsverteilung manuell berechnen
            num_counts = Counter()
            for d in draws:
                for n in d.numbers:
                    num_counts[n] += 1

            if num_counts:
                counts = list(num_counts.values())
                avg = sum(counts) / len(counts)
                expected = len(draws) * self._config.main_count / self._config.num_range
                min_c = min(counts)
                max_c = max(counts)
                lines.append(f"  Erwartete Häufigkeit pro Zahl: {expected:.1f}")
                lines.append(f"  Tatsaechlich: min={min_c}, max={max_c}, avg={avg:.1f}")
                if expected > 0:
                    deviation = (max_c - min_c) / expected * 100
                    lines.append(f"  Spreizung: {deviation:.1f}% (normal: <50%)")

            # Aktuelle Daten
            recent_year = date.today().year
            recent_count = sum(1 for d in draws if d.draw_date.year == recent_year)
            lines.append(f"  Daten {recent_year}: {recent_count} Ziehungen")
            if recent_count == 0:
                lines.append(f"  Keine aktuellen Daten für {recent_year}!")

            lines.append("")

        lines.append("\nHinweis: Vollständige Statistik-Analyse nur via Server-API verfügbar.")
        return "\n".join(lines)

    def _build_quality_report_api(self) -> str:
        """Qualitäts-/Anomalie-Bericht via API (Client-Modus)."""
        lines = ["=== DB-BERICHT (via Server-API) ===\n"]
        try:
            integrity = self.api_client.db_integrity()
            db_stats = self.api_client.get_db_stats()
        except Exception as e:
            return f"Fehler beim Laden der Server-Daten: {e}"

        _table_map = {
            "saturday": "draws_saturday", "wednesday": "draws_wednesday",
            "tuesday": "ej_draws_tuesday", "friday": "ej_draws_friday",
        }

        for day_str in self._config.draw_days:
            day_name = DAY_LABELS.get(day_str, day_str)
            table = _table_map.get(day_str, "")
            count = db_stats.get(table, 0)
            lines.append(f"--- {day_name}: {count} Ziehungen ---")

        # Integritäts-Daten
        if isinstance(integrity, dict):
            for day_str, info in integrity.items():
                if isinstance(info, dict):
                    coverage = info.get("coverage_pct", "?")
                    gaps = info.get("gaps", [])
                    lines.append(f"  {_day_names.get(day_str, day_str)}: "
                                 f"Abdeckung {coverage}%")
                    if gaps:
                        lines.append(f"    Lücken: {len(gaps)}")
                        for g in gaps[:5]:
                            lines.append(f"      {g}")

        total = sum(db_stats.get(t, 0) for t in _table_map.values())
        lines.append(f"\nGESAMT: {total} Ziehungen")
        lines.append(f"DB-Größe: {db_stats.get('db_size_mb', '?')} MB")
        return "\n".join(lines)

    def _build_stat_verification_api(self) -> str:
        """Statistik-Verifikation via API (Client-Modus)."""
        lines = ["=== STATISTIK-DATENGRUNDLAGE (via Server) ===\n"]

        for day_str in self._config.draw_days:
            day_name = DAY_LABELS.get(day_str, day_str)
            try:
                stats = self.api_client.get_statistics(
                    day_str, year_from=self._config.start_year, year_to=date.today().year,
                )
            except Exception as e:
                lines.append(f"--- {day_name}: Fehler: {e} ---\n")
                continue

            total = stats.get("total_draws", 0)
            lines.append(f"--- {day_name}: {total} Ziehungen ---")

            freqs = stats.get("frequencies", [])
            if freqs:
                counts = [f.get("count", 0) for f in freqs]
                avg = sum(counts) / max(len(counts), 1)
                mn_c, mx_c = min(counts), max(counts)
                expected = total * self._config.main_count / self._config.num_range
                lines.append(f"  Erwartete Häufigkeit: {expected:.1f}")
                lines.append(f"  Tatsaechlich: min={mn_c}, max={mx_c}, avg={avg:.1f}")
                if expected > 0:
                    dev = (mx_c - mn_c) / expected * 100
                    lines.append(f"  Spreizung: {dev:.1f}%")

            hot = stats.get("hot_numbers", [])
            cold = stats.get("cold_numbers", [])
            if hot:
                lines.append(f"  Hot: {hot[:5]}")
            if cold:
                lines.append(f"  Cold: {cold[:5]}")
            lines.append("")

        return "\n".join(lines)
