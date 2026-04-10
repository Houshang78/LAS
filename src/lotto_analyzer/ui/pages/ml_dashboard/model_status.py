"""ML-Dashboard: Modell-Status + Info-Panels."""

import threading
from datetime import datetime

from lotto_common.models.draw import DrawDay

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("ml_dashboard.model_status")


class ModelStatusMixin:
    """Modell-Status pro Ziehungstag + Erklärungen."""

    def _build_model_status_section(self, content: Gtk.Box) -> None:
        # ── Status-Karten ──
        group = Adw.PreferencesGroup(
            title=_("Modell-Status"),
            description=_("Trainierte ML-Modelle pro Ziehungstag"),
        )
        content.append(group)

        self._model_rows: dict[str, Adw.ActionRow] = {}
        for key in ("rf", "gb", "lstm"):
            from lotto_analyzer.ui.pages.ml_dashboard.page import MODEL_INFO
            info = MODEL_INFO[key]
            row = Adw.ActionRow(
                title=f"{info['icon']} {info['name']}",
                subtitle=_("Laden..."),
            )
            # Status-Badge
            badge = Gtk.Label(label="—")
            badge.add_css_class("monospace")
            row.add_suffix(badge)
            row._badge = badge
            group.add(row)
            self._model_rows[key] = row

        # Train-Button
        train_btn = Gtk.Button(label=_("Training starten"))
        train_btn.set_icon_name("media-playback-start-symbolic")
        train_btn.add_css_class("suggested-action")
        train_btn.connect("clicked", self._on_train_all)
        self._train_btn = train_btn

        train_row = Adw.ActionRow(title=_("Manuelles Training"))
        train_row.add_suffix(train_btn)
        group.add(train_row)

        # Auto-Training status
        self._auto_train_row = Adw.ActionRow(
            title=_("Auto-Training"),
            subtitle=_("Status wird geladen..."),
        )
        self._auto_train_row.set_icon_name("emblem-synchronizing-symbolic")
        group.add(self._auto_train_row)

        # Last training info
        self._last_train_row = Adw.ActionRow(
            title=_("Letztes Training"),
            subtitle="—",
        )
        group.add(self._last_train_row)

        # ── Modell-Erklärungen ──
        info_group = Adw.PreferencesGroup(
            title=_("Was bedeuten die Modelle?"),
        )
        content.append(info_group)

        for key, info in MODEL_INFO.items():
            expander = Adw.ExpanderRow(title=f"{info['icon']} {info['name']}")
            desc_row = Adw.ActionRow(title=info["desc"])
            desc_row.set_title_lines(10)
            expander.add_row(desc_row)
            info_group.add(expander)

        # ── Vergleichstabelle ──
        self._comparison_group = Adw.PreferencesGroup(
            title=_("Modell-Vergleich"),
        )
        content.append(self._comparison_group)
        self._comparison_rows: list[Adw.ActionRow] = []

    def _update_model_status(self, data: dict) -> None:
        """Status-Badges aktualisieren."""
        model_ready = data.get("model_ready", {})
        confidence = data.get("confidence", 0)
        models_db = data.get("models", [])

        # Models aus DB oder API
        model_info_map = {}
        for m in models_db:
            mtype = m.get("model_type", "")
            model_info_map[mtype] = m

        for key, row in self._model_rows.items():
            ready = model_ready.get(key, False)
            badge = row._badge

            if ready:
                badge.set_label("✓ " + _("Trainiert"))
                badge.remove_css_class("error")
                badge.add_css_class("success")
            else:
                badge.set_label("✗ " + _("Nicht trainiert"))
                badge.remove_css_class("success")
                badge.add_css_class("error")

            # Zusatz-Info aus DB
            db_info = model_info_map.get(key, {})
            last_trained = db_info.get("last_trained", "")
            accuracy = db_info.get("accuracy", 0)

            parts = []
            if accuracy:
                parts.append(f"Accuracy: {accuracy:.1%}")
            if last_trained:
                try:
                    dt = datetime.fromisoformat(str(last_trained))
                    parts.append(f"Trainiert: {dt.strftime('%d.%m.%Y %H:%M')}")
                except Exception as e:
                    logger.debug(f"Datum parsen fehlgeschlagen: {e}")
                    parts.append(f"Trainiert: {last_trained}")
            if db_info.get("n_samples"):
                parts.append(f"{db_info['n_samples']} Samples")

            row.set_subtitle(" | ".join(parts) if parts else _("Keine Daten"))

        # Vergleichstabelle
        while self._comparison_rows:
            row = self._comparison_rows.pop()
            self._comparison_group.remove(row)

        if model_ready:
            header = Adw.ActionRow(
                title=f"{'Modell':<15} {'Status':<12} {'Accuracy':<10} {'Typ'}",
            )
            header.add_css_class("monospace")
            self._comparison_group.add(header)
            self._comparison_rows.append(header)

            for key in ("rf", "gb", "lstm"):
                ready = "✓" if model_ready.get(key) else "✗"
                acc = model_info_map.get(key, {}).get("accuracy", 0)
                acc_str = f"{acc:.1%}" if acc else "—"
                names = {"rf": "Random Forest", "gb": "Gradient Boost", "lstm": "LSTM"}
                row = Adw.ActionRow(
                    title=f"{names[key]:<15} {ready:<12} {acc_str:<10}",
                )
                row.add_css_class("monospace")
                self._comparison_group.add(row)
                self._comparison_rows.append(row)

        # Confidence
        if confidence > 0:
            conf_row = Adw.ActionRow(
                title=_("Gesamt-Confidence"),
                subtitle=f"{confidence:.1%}",
            )
            self._comparison_group.add(conf_row)
            self._comparison_rows.append(conf_row)

        # Auto-training status from scheduler
        ml_status = data.get("ml_status", {})
        auto_train = ml_status.get("auto_retrain", None)
        if auto_train is not None:
            self._auto_train_row.set_subtitle(
                "✓ " + _("Aktiv") if auto_train else "✗ " + _("Deaktiviert")
            )
        else:
            self._auto_train_row.set_subtitle(_("Nicht verfügbar"))

        # Last training from training_runs
        training_runs = data.get("training_runs", [])
        if training_runs:
            last = training_runs[0]
            created = str(last.get("created_at", ""))[:16]
            rf = last.get("rf_accuracy") or 0
            gb = last.get("gb_accuracy") or 0
            source = ""
            try:
                import json
                params = last.get("params", "{}")
                if isinstance(params, str):
                    params = json.loads(params)
                source = params.get("source", "")
            except Exception:
                pass
            src_label = f" [{source}]" if source else ""
            self._last_train_row.set_subtitle(
                f"{created} | RF: {rf:.1%} | GB: {gb:.1%}{src_label}"
            )
        else:
            self._last_train_row.set_subtitle(_("Kein Training durchgeführt"))

    def _on_train_all(self, _btn) -> None:
        """Training für den ausgewählten Ziehungstag starten — via Server."""
        if not self.api_client:
            from lotto_analyzer.ui.helpers import show_error_toast
            show_error_toast(self, _("Serververbindung erforderlich"))
            return

        self._train_btn.set_sensitive(False)
        draw_day = self._draw_day

        def worker():
            try:
                self.api_client.train_ml()
            except Exception as e:
                logger.error(f"Training fehlgeschlagen: {e}")
            GLib.idle_add(self._on_train_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_train_done(self) -> bool:
        self._train_btn.set_sensitive(True)
        self.refresh()
        return False
