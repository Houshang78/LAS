"""Server-Workers Tab.

Worker-Count-Konfiguration + Live-Status der APScheduler-Jobs +
7-Tage-Statistik + Recent-Runs. Datenquelle: L2.3-Endpoints
/workers/config, /workers/status, /health/detailed (LAS-Server).

Auto-Refresh alle 30s solange die Page sichtbar ist.
"""

import threading
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger
from lotto_analyzer.ui.pages.base_page import BasePage

logger = get_logger("server_workers")


_STATUS_ICON = {
    "success": "emblem-ok-symbolic",
    "error":   "dialog-error-symbolic",
    "missed":  "dialog-warning-symbolic",
}


def _fmt_dt(s: str | None) -> str:
    if not s:
        return "—"
    try:
        # Robust parser: accept ISO with or without TZ
        s2 = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s2).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return s


def _fmt_ms(v) -> str:
    if v is None:
        return "—"
    try:
        v = float(v)
    except Exception:
        return str(v)
    if v < 1000:
        return f"{int(v)} ms"
    return f"{v / 1000:.1f} s"


class ServerWorkersPage(BasePage):
    """Worker-Count + Job-Monitoring im Desktop-Client."""

    POLL_INTERVAL_SEC = 30  # Auto-Refresh-Takt
    RECENT_LIMIT = 50

    def __init__(self, config_manager, db, app_mode, api_client=None,
                 app_db=None, backtest_db=None):
        super().__init__(
            config_manager=config_manager, db=db, app_mode=app_mode,
            api_client=api_client, app_db=app_db, backtest_db=backtest_db,
        )
        self._poll_id: int | None = None
        self._build_ui()
        self._start_polling()

    # ── UI ──

    def _build_ui(self) -> None:
        # Outer scroll
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.append(scroll)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        outer.set_margin_top(18)
        outer.set_margin_bottom(18)
        outer.set_margin_start(18)
        outer.set_margin_end(18)
        scroll.set_child(outer)

        # Header
        header = Gtk.Label(label=_("Worker & Health"), xalign=0)
        header.add_css_class("title-2")
        outer.append(header)

        subtitle = Gtk.Label(
            label=_("APScheduler-Worker, Job-Statistiken (7d), Recent-Runs."),
            xalign=0,
        )
        subtitle.add_css_class("dim-label")
        outer.append(subtitle)

        # ── Worker-Count Card ──
        outer.append(self._build_worker_count_card())

        # ── Scheduler / Health Card ──
        outer.append(self._build_health_card())

        # ── Per-Job 7d Stats ──
        outer.append(self._build_per_job_card())

        # ── Recent Runs Tabelle ──
        outer.append(self._build_recent_card())

    def _section(self, title: str) -> tuple[Gtk.Box, Gtk.Box]:
        """Card mit Titel zurückgeben (frame, content-box)."""
        frame = Gtk.Frame()
        frame.add_css_class("card")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(14)
        box.set_margin_end(14)
        frame.set_child(box)

        lbl = Gtk.Label(label=title, xalign=0)
        lbl.add_css_class("heading")
        box.append(lbl)
        return frame, box

    def _build_worker_count_card(self) -> Gtk.Widget:
        frame, box = self._section(_("Worker-Anzahl"))

        info = Gtk.Label(
            label=_(
                "Anzahl paralleler Worker im APScheduler. "
                "Änderung wird beim nächsten Server-Restart aktiv. "
                "Aktiver Wert kommt aus ENV LASS_WORKER_COUNT, "
                "DB-Setting oder Default 1 (in dieser Reihenfolge).",
            ),
            xalign=0, wrap=True,
        )
        info.add_css_class("dim-label")
        box.append(info)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.append(row)

        # SpinButton 1-32
        adj = Gtk.Adjustment(value=1, lower=1, upper=32, step_increment=1)
        self._spin_workers = Gtk.SpinButton()
        self._spin_workers.set_adjustment(adj)
        self._spin_workers.set_numeric(True)
        self._spin_workers.set_width_chars(4)
        row.append(self._spin_workers)

        self._lbl_active = Gtk.Label(label="", xalign=0)
        self._lbl_active.add_css_class("dim-label")
        row.append(self._lbl_active)

        spacer = Gtk.Box(hexpand=True)
        row.append(spacer)

        self._btn_apply = Gtk.Button(label=_("Speichern"))
        self._btn_apply.add_css_class("suggested-action")
        self._btn_apply.connect("clicked", self._on_apply_workers)
        row.append(self._btn_apply)

        self._lbl_workers_status = Gtk.Label(label="", xalign=0)
        self._lbl_workers_status.set_wrap(True)
        box.append(self._lbl_workers_status)

        return frame

    def _build_health_card(self) -> Gtk.Widget:
        frame, box = self._section(_("Server-Gesundheit"))

        grid = Gtk.Grid(column_spacing=18, row_spacing=6)
        box.append(grid)

        self._lbl_sched_status = Gtk.Label(xalign=0)
        self._lbl_sched_jobs = Gtk.Label(xalign=0)
        self._lbl_sched_started = Gtk.Label(xalign=0)
        self._lbl_jobs_7d = Gtk.Label(xalign=0)

        rows = [
            (_("Scheduler:"), self._lbl_sched_status),
            (_("Geplante Jobs:"), self._lbl_sched_jobs),
            (_("Gestartet:"), self._lbl_sched_started),
            (_("Jobs (7d):"), self._lbl_jobs_7d),
        ]
        for r, (label_text, value_widget) in enumerate(rows):
            l = Gtk.Label(label=label_text, xalign=0)
            l.add_css_class("dim-label")
            grid.attach(l, 0, r, 1, 1)
            grid.attach(value_widget, 1, r, 1, 1)

        # Models — mehrzeilig
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        box.append(sep)
        models_lbl = Gtk.Label(label=_("ML-Modelle"), xalign=0)
        models_lbl.add_css_class("heading")
        box.append(models_lbl)
        self._models_list = Gtk.Label(xalign=0)
        self._models_list.set_wrap(True)
        self._models_list.set_use_markup(True)
        box.append(self._models_list)

        # Predictions per draw_day
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep2.set_margin_top(8)
        box.append(sep2)
        preds_lbl = Gtk.Label(label=_("Predictions (nächste Ziehung)"), xalign=0)
        preds_lbl.add_css_class("heading")
        box.append(preds_lbl)
        self._preds_list = Gtk.Label(xalign=0)
        self._preds_list.set_wrap(True)
        self._preds_list.set_use_markup(True)
        box.append(self._preds_list)

        return frame

    def _build_per_job_card(self) -> Gtk.Widget:
        frame, box = self._section(_("Pro-Job-Statistik (letzte 7 Tage)"))

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroller.set_min_content_height(180)
        box.append(scroller)

        # ColumnView mit StringList
        self._per_job_store = Gtk.StringList()
        # we'll render plain text rows because column-view setup is verbose;
        # keep it simple with TextView
        self._per_job_view = Gtk.TextView()
        self._per_job_view.set_editable(False)
        self._per_job_view.set_cursor_visible(False)
        self._per_job_view.set_monospace(True)
        scroller.set_child(self._per_job_view)

        return frame

    def _build_recent_card(self) -> Gtk.Widget:
        frame, box = self._section(
            _("Recent-Runs (letzte {n})").format(n=self.RECENT_LIMIT),
        )

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(260)
        box.append(scroller)

        self._recent_view = Gtk.TextView()
        self._recent_view.set_editable(False)
        self._recent_view.set_cursor_visible(False)
        self._recent_view.set_monospace(True)
        scroller.set_child(self._recent_view)

        # Refresh-Button + Status-Label
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(row)
        btn_refresh = Gtk.Button(label=_("Jetzt aktualisieren"))
        btn_refresh.connect("clicked", lambda *_: self._refresh_async())
        row.append(btn_refresh)
        self._lbl_last_refresh = Gtk.Label(xalign=0)
        self._lbl_last_refresh.add_css_class("dim-label")
        row.append(self._lbl_last_refresh)

        return frame

    # ── Polling / Refresh ──

    def _start_polling(self) -> None:
        if self._poll_id is not None:
            return
        # Sofort einmal + dann alle N Sekunden
        self._refresh_async()
        self._poll_id = GLib.timeout_add_seconds(
            self.POLL_INTERVAL_SEC, self._on_poll_tick,
        )

    def _on_poll_tick(self) -> bool:
        # D4.3: Backoff respektieren — bei wiederholten Connection-Fehlern
        # nicht weiter hämmern.
        if not self.api_client:
            return True
        if self.poll_should_skip():
            return True
        if self.get_visible():
            self._refresh_async()
        return True  # re-arm

    def _refresh_async(self) -> None:
        if not self.api_client:
            self._lbl_workers_status.set_text(_("Kein API-Client verbunden."))
            return
        threading.Thread(target=self._refresh_blocking, daemon=True).start()

    def _refresh_blocking(self) -> None:
        # D4.3: Connection-Health-Tracking. Wenn alle 3 Calls connection-fail,
        # → poll_record_failure (Backoff). Sonst → success.
        connect_failures = 0
        other_success = 0

        def _try(label, fn):
            nonlocal connect_failures, other_success
            try:
                val = fn()
                other_success += 1
                return val
            except (ConnectionError, TimeoutError, OSError) as e:
                connect_failures += 1
                logger.warning(f"{label}: {e}")
                return {"error": str(e)}
            except Exception as e:
                other_success += 1
                logger.warning(f"{label}: {e}")
                return {"error": str(e)}

        cfg = _try("workers/config", self.api_client.get_workers_config)
        status = _try(
            "workers/status",
            lambda: self.api_client.get_workers_status(limit=self.RECENT_LIMIT),
        )
        health = _try("health/detailed", self.api_client.get_health_detailed)

        if connect_failures and other_success == 0:
            self.poll_record_failure(ConnectionError(f"{connect_failures}/3 failed"))
        else:
            self.poll_record_success()

        GLib.idle_add(self._render, cfg, status, health)

    def _render(self, cfg: dict, status: dict, health: dict) -> bool:
        # Worker-Count
        wc = cfg.get("worker_count")
        if isinstance(wc, int):
            # SpinButton nur setzen wenn der User gerade nicht editiert
            if not self._spin_workers.has_focus():
                self._spin_workers.set_value(wc)
        src = cfg.get("source", "?")
        env_v = cfg.get("env_value")
        db_v = cfg.get("db_value")
        active_text = _("Aktiv: {n} (Quelle: {src})").format(n=wc, src=src)
        if env_v is not None:
            active_text += f" · ENV={env_v}"
        if db_v is not None:
            active_text += f" · DB={db_v}"
        self._lbl_active.set_text(active_text)
        if cfg.get("error"):
            self._lbl_workers_status.set_text(_("Fehler: {e}").format(e=cfg["error"]))
        else:
            self._lbl_workers_status.set_text(cfg.get("note", ""))

        # Health
        sched = health.get("scheduler") or {}
        running = sched.get("running")
        if running is True:
            self._lbl_sched_status.set_markup("<span color='#22c55e'>● " + _("läuft") + "</span>")
        elif running is False:
            self._lbl_sched_status.set_markup("<span color='#ef4444'>● " + _("aus") + "</span>")
        else:
            self._lbl_sched_status.set_text("?")
        self._lbl_sched_jobs.set_text(str(sched.get("job_count", "?")))
        self._lbl_sched_started.set_text(_fmt_dt(sched.get("started_at")))

        jobs7 = health.get("jobs_7d") or {}
        if jobs7.get("total"):
            txt = _("{ok} ok / {err} err / {miss} missed · fail-rate {fr:.1%}").format(
                ok=jobs7.get("success", 0),
                err=jobs7.get("error_count", 0),
                miss=jobs7.get("missed", 0),
                fr=float(jobs7.get("fail_rate", 0)),
            )
            self._lbl_jobs_7d.set_text(txt)
        else:
            self._lbl_jobs_7d.set_text(_("(keine Runs in 7d)"))

        # Models
        models = health.get("models") or {}
        if isinstance(models, dict) and models and "error" not in models:
            lines = []
            for fn in sorted(models.keys()):
                m = models[fn]
                if isinstance(m, dict):
                    lines.append(
                        f"<tt>{fn}</tt> — "
                        + _("trainiert {ts} ({age:.1f}h alt, {kb:.0f} KB)").format(
                            ts=_fmt_dt(m.get("trained_at")),
                            age=float(m.get("age_hours", 0) or 0),
                            kb=float(m.get("size_kb", 0) or 0),
                        )
                    )
            self._models_list.set_markup("\n".join(lines) if lines else _("(keine)"))
        else:
            self._models_list.set_text(_("(keine Modelle gefunden)"))

        # Predictions
        preds = health.get("predictions") or {}
        if isinstance(preds, dict) and preds and "error" not in preds:
            lines = []
            for dd in ["saturday", "wednesday", "tuesday", "friday"]:
                info = preds.get(dd)
                if not isinstance(info, dict):
                    continue
                if info.get("error"):
                    lines.append(f"<tt>{dd:>10}</tt> — {info['error']}")
                    continue
                per = info.get("per_strategy") or {}
                per_str = ", ".join(f"{k}={v}" for k, v in per.items()) or "—"
                lines.append(
                    f"<tt>{dd:>10}</tt> @ {info.get('draw_date', '?')} — "
                    + _("Total {n}").format(n=info.get("total", 0))
                    + f" ({per_str})"
                )
            self._preds_list.set_markup("\n".join(lines) if lines else _("(keine)"))
        else:
            self._preds_list.set_text(_("(keine Daten)"))

        # Per-Job-Stats
        per_job = status.get("per_job_7d") or []
        buf = self._per_job_view.get_buffer()
        if per_job:
            header = (
                f"{'Job':<28} {'Total':>6} {'OK':>5} {'Err':>5} "
                f"{'Miss':>5} {'Fail%':>6} {'AvgMs':>9} {'Last':>20}\n"
            )
            sep = "-" * len(header) + "\n"
            lines = [header, sep]
            for j in per_job:
                lines.append(
                    f"{(j.get('job_name', '?'))[:28]:<28} "
                    f"{j.get('total', 0):>6} "
                    f"{j.get('success', 0):>5} "
                    f"{j.get('error_count', 0):>5} "
                    f"{j.get('missed', 0):>5} "
                    f"{(j.get('fail_rate', 0)*100):>5.1f}% "
                    f"{_fmt_ms(j.get('avg_ms')):>9} "
                    f"{_fmt_dt(j.get('last_run')):>20}\n"
                )
            buf.set_text("".join(lines))
        else:
            buf.set_text(_("(keine Daten — Scheduler läuft eventuell nicht oder noch keine Job-Runs)"))

        # Recent runs
        recent = status.get("recent_runs") or []
        rbuf = self._recent_view.get_buffer()
        if recent:
            header = f"{'When':<20} {'Status':<8} {'Job':<28} {'Dur':>9}  Error\n"
            sep = "-" * len(header) + "\n"
            lines = [header, sep]
            for r in recent:
                err = r.get("error") or ""
                if err and len(err) > 80:
                    err = err[:80] + "…"
                lines.append(
                    f"{_fmt_dt(r.get('started_at')):<20} "
                    f"{(r.get('status', '?')):<8} "
                    f"{(r.get('job_name', '?'))[:28]:<28} "
                    f"{_fmt_ms(r.get('duration_ms')):>9}  "
                    f"{err}\n"
                )
            rbuf.set_text("".join(lines))
        else:
            rbuf.set_text(_("(keine Runs)"))

        self._lbl_last_refresh.set_text(
            _("Letzte Aktualisierung: {ts}").format(
                ts=datetime.now().strftime("%H:%M:%S"),
            ),
        )
        return False  # idle_add: nicht wiederholen

    def _on_apply_workers(self, *_args) -> None:
        if not self.api_client:
            self._lbl_workers_status.set_text(_("Kein API-Client."))
            return
        new_count = int(self._spin_workers.get_value())
        self._btn_apply.set_sensitive(False)

        def _job():
            try:
                resp = self.api_client.put_workers_config(new_count)
                msg = resp.get("note") or _("Gespeichert.")
                err = None
            except Exception as e:
                msg = ""
                err = str(e)

            def _back():
                self._btn_apply.set_sensitive(True)
                if err:
                    self._lbl_workers_status.set_text(_("Fehler: {e}").format(e=err))
                else:
                    self._lbl_workers_status.set_text(
                        _("OK — {n} gespeichert. {note}").format(n=new_count, note=msg),
                    )
                self._refresh_async()
                return False

            GLib.idle_add(_back)

        threading.Thread(target=_job, daemon=True).start()

    def stop(self) -> None:
        """Vom Window aufgerufen wenn Page entladen wird."""
        if self._poll_id is not None:
            GLib.source_remove(self._poll_id)
            self._poll_id = None
