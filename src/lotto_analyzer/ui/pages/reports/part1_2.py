"""UI-Seite reports: part1_2 — day selection + backtest stub."""

from lotto_common.i18n import _
from lotto_common.utils.logging_config import get_logger

logger = get_logger("reports.part1_2")

DAY_LABELS = {
    "saturday": "Samstag",
    "wednesday": "Mittwoch",
    "tuesday": "Dienstag",
    "friday": "Freitag",
}


class Part1Mixin2:
    """Day dropdown management + legacy backtest stubs."""

    def _rebuild_day_model(self) -> None:
        """Rebuild dropdown model with draw days of current game type."""
        while self._day_model.get_n_items() > 0:
            self._day_model.remove(0)
        for day in self._config.draw_days:
            self._day_model.append(DAY_LABELS.get(day, day))
        self._day_model.append(_("Alle"))

    def _get_selected_draw_day(self) -> str | None:
        """Return selected draw day string (or None for 'Alle')."""
        idx = self._day_dropdown.get_selected()
        days = self._config.draw_days
        if idx < len(days):
            return days[idx]
        return None

    def _on_day_changed(self, dropdown, _pspec) -> None:
        """Draw day changed — reload reports."""
        if getattr(self, "_switching_game", False):
            return
        self._load_reports()

    def _show_bt_run_details(self, steps: list[dict]) -> bool:
        """No-op — backtest is now in sub-tab."""
        return False

    def _on_show_backtest_reports(self, _btn) -> None:
        """Switch to backtest sub-tab."""
        if hasattr(self, "_report_stack"):
            self._report_stack.set_visible_child_name("backtest")
