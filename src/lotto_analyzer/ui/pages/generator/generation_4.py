"""Generator-Seite: Mass-Generation Mixin (Schwelle editierbar, Telegram, Pipeline)."""

import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_common.models.draw import DrawDay
from lotto_analyzer.ui.widgets.help_button import HelpButton

logger = get_logger("generator.mass_gen")

# Strategien die Mass-Gen nativ unterstützt
_MASS_STRATEGIES = {"hot", "cold", "mixed", "random", "spread", "cluster"}


class MassGenMixin:
    """Mass-Generation UI — editierbare Schwelle, Telegram Toggle, Pipeline."""

    # ══════════════════════════════════════════════
    # UI-Controls (aufgerufen von generation_1._build_generation_section)
    # ══════════════════════════════════════════════

    def _build_mass_gen_settings(self, gen_group) -> None:
        """Mass-Gen Settings: Telegram Toggle + editierbare Schwelle."""
        # Telegram-Benachrichtigungen
        self._mass_gen_telegram_switch = Gtk.Switch()
        self._mass_gen_telegram_switch.set_active(
            self.config_manager.config.generator.mass_gen_telegram,
        )
        self._mass_gen_telegram_switch.set_valign(Gtk.Align.CENTER)
        tg_row = Adw.ActionRow(
            title=_("Telegram-Benachrichtigungen"),
            subtitle=_("Fortschritts-Meldungen bei Mass-Generation (4 Schritte)"),
        )
        tg_row.add_prefix(Gtk.Image.new_from_icon_name("mail-send-symbolic"))
        tg_row.add_suffix(self._mass_gen_telegram_switch)
        tg_row.set_activatable_widget(self._mass_gen_telegram_switch)
        gen_group.add(tg_row)
        self._mass_gen_telegram_switch.connect(
            "notify::active", self._on_mass_telegram_toggled,
        )

        # Mass-Gen Schwelle (editierbar)
        threshold = self.config_manager.config.generator.mass_gen_threshold
        self._threshold_spin = Adw.SpinRow.new_with_range(1_000, 10_000_000, 1_000)
        self._threshold_spin.set_title(_("Mass-Gen Schwelle"))
        self._threshold_spin.set_value(threshold)
        self._threshold_spin.add_suffix(
            HelpButton(_(
                "Ab dieser Tipp-Anzahl wird Mass-Generation genutzt:\n"
                "PostgreSQL + Multicore + Dedup + Re-Gen.\n"
                "Unterhalb dieser Schwelle: normaler Generator (SQLite)."
            ))
        )
        self._threshold_spin.connect("notify::value", self._on_threshold_changed)
        gen_group.add(self._threshold_spin)

    def _on_mass_telegram_toggled(self, switch, _pspec) -> None:
        """Telegram-Toggle geändert — in Config speichern."""
        active = switch.get_active()
        self.config_manager.config.generator.mass_gen_telegram = active
        self.config_manager.save()

    def _on_threshold_changed(self, spin, _pspec) -> None:
        """Mass-Gen Schwelle geändert — Config + Hinweis aktualisieren."""
        value = int(spin.get_value())
        self.config_manager.config.generator.mass_gen_threshold = value
        self.config_manager.save()

        # Hinweis-Label aktualisieren
        if hasattr(self, "_mass_gen_hint") and hasattr(self, "_count_spin"):
            count = int(self._count_spin.get_value())
            self._mass_gen_hint.set_visible(count >= value)

    # ══════════════════════════════════════════════
    # Mass-Generation Pipeline starten
    # ══════════════════════════════════════════════

    def _start_mass_generate(
        self, draw_day: DrawDay, count: int, strategies: list,
    ) -> None:
        """Mass-Generation Pipeline starten — pro Strategie ein Batch."""
        total_strategies = len(strategies)
        total_count = count * total_strategies
        self._status_label.set_label(
            _("Mass-Gen Pipeline") + f": {total_count:,} "
            + _("Tipps") + f" ({total_strategies} "
            + _("Strategien") + ") — Generate + Dedup + Re-Gen..."
        )
        self._mass_gen_task_ids: list[tuple[str, str, str]] = []
        self._mass_gen_total = total_strategies
        self._mass_gen_done = 0
        self._mass_gen_failed = 0

        # Telegram-Flag aus Switch lesen
        telegram = True
        if hasattr(self, "_mass_gen_telegram_switch"):
            telegram = self._mass_gen_telegram_switch.get_active()

        def worker():
            for strat in strategies:
                strat_name = strat.value if hasattr(strat, "value") else str(strat)
                mass_strat = strat_name if strat_name in _MASS_STRATEGIES else "random"
                try:
                    data = self.api_client.mass_generate_pipeline(
                        draw_day=draw_day.value,
                        strategy=mass_strat,
                        count=count,
                        telegram=telegram,
                    )
                    task_id = data.get("task_id")
                    if task_id:
                        self._mass_gen_task_ids.append(
                            (task_id, strat_name, mass_strat),
                        )
                except Exception as e:
                    logger.error(f"Mass-Gen {strat_name} fehlgeschlagen: {e}")
                    self._mass_gen_failed += 1

            if not self._mass_gen_task_ids:
                GLib.idle_add(
                    self._on_mass_gen_all_done,
                    _("Alle Mass-Gen Auftraege fehlgeschlagen."),
                )
                return

            GLib.idle_add(self._poll_mass_gen_tasks)

        threading.Thread(target=worker, daemon=True).start()

    # ══════════════════════════════════════════════
    # Polling
    # ══════════════════════════════════════════════

    def _poll_mass_gen_tasks(self) -> bool:
        """Poll alle Mass-Gen Pipeline Tasks bis fertig."""
        def poller():
            import time
            while self._mass_gen_task_ids:
                time.sleep(5)
                if self._cancel_event.is_set():
                    GLib.idle_add(
                        self._on_mass_gen_all_done, _("Abgebrochen."),
                    )
                    return

                still_running = []
                for task_id, strat_name, mass_strat in self._mass_gen_task_ids:
                    try:
                        task = self.api_client.get_task(task_id)
                    except Exception:
                        still_running.append((task_id, strat_name, mass_strat))
                        continue

                    status = task.get("status", "")
                    progress = task.get("progress", 0)

                    if status == "completed":
                        self._mass_gen_done += 1
                        result = task.get("result", {})
                        if isinstance(result, str):
                            import json
                            try:
                                result = json.loads(result)
                            except Exception:
                                result = {}
                        batch_id = result.get("batch_id", "?")[:8]
                        final = result.get("final_count", 0)
                        elapsed = result.get("total_elapsed_seconds", 0)
                        GLib.idle_add(
                            self._status_label.set_label,
                            _("Mass-Gen") + f": {self._mass_gen_done}/{self._mass_gen_total} "
                            + _("fertig") + f" ({strat_name} → {final:,} in {elapsed}s)",
                        )
                    elif status in ("failed", "cancelled"):
                        self._mass_gen_failed += 1
                        error = task.get("error", "")
                        logger.warning(f"Mass-Gen {strat_name} failed: {error}")
                    else:
                        still_running.append((task_id, strat_name, mass_strat))
                        pct = int(progress * 100)
                        # Show step info from task progress message
                        msg_data = task.get("result", {})
                        if isinstance(msg_data, dict):
                            step_msg = msg_data.get("message", "")
                        else:
                            step_msg = ""
                        label = (
                            _("Mass-Gen") + f": {strat_name} {pct}%"
                        )
                        if step_msg:
                            label += f" — {step_msg}"
                        GLib.idle_add(self._status_label.set_label, label)

                self._mass_gen_task_ids = still_running

            GLib.idle_add(self._on_mass_gen_all_done, None)

        self._cancel_event.clear()
        threading.Thread(target=poller, daemon=True).start()
        return False

    def _on_mass_gen_all_done(self, error: str | None = None) -> bool:
        """Mass-Generation Pipeline komplett abgeschlossen."""
        with self._op_lock:
            self._generating = False
        self._gen_btn.set_sensitive(not self._is_readonly)
        self._spinner.stop()
        self._spinner.set_visible(False)

        if error:
            self._status_label.set_label(_("Mass-Gen Fehler") + f": {error}")
        else:
            done = self._mass_gen_done
            failed = self._mass_gen_failed
            total = self._mass_gen_total
            msg = (
                _("Mass-Gen Pipeline abgeschlossen")
                + f": {done}/{total} " + _("Strategien erfolgreich")
            )
            if failed:
                msg += f", {failed} " + _("fehlgeschlagen")
            msg += " — " + _("Berichte in PostgreSQL + Zyklus-Berichte gespeichert.")
            self._status_label.set_label(msg)

        return False
