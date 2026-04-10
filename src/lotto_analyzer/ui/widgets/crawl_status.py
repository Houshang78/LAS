"""Auto-Crawl Status Widget."""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

class CrawlStatusWidget(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("card")
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        self.set_margin_start(8)
        self.set_margin_end(8)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_top(12)
        header.set_margin_start(12)
        header.append(Gtk.Image.new_from_icon_name("emblem-synchronizing-symbolic"))
        title = Gtk.Label(label="Auto-Crawl Status")
        title.add_css_class("heading")
        header.append(title)
        self.append(header)
        self._status_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        self._status_label = Gtk.Label(label="Bereit")
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.set_margin_start(12)
        status_box.append(self._status_icon)
        status_box.append(self._status_label)
        self.append(status_box)
        self._last_check = Gtk.Label(label="Letzte Prüfung: —")
        self._last_check.set_halign(Gtk.Align.START)
        self._last_check.set_margin_start(12)
        self._last_check.add_css_class("dim-label")
        self.append(self._last_check)
        self._next_check = Gtk.Label(label="Nächste Prüfung: —")
        self._next_check.set_halign(Gtk.Align.START)
        self._next_check.set_margin_start(12)
        self._next_check.add_css_class("dim-label")
        self.append(self._next_check)
        self._retry_label = Gtk.Label(label="")
        self._retry_label.set_halign(Gtk.Align.START)
        self._retry_label.set_margin_start(12)
        self._retry_label.set_visible(False)
        self.append(self._retry_label)
        self._refresh_btn = Gtk.Button(label="Jetzt aktualisieren")
        self._refresh_btn.set_tooltip_text("Crawl-Status aktualisieren")
        self._refresh_btn.add_css_class("suggested-action")
        self._refresh_btn.set_margin_top(8)
        self._refresh_btn.set_margin_bottom(12)
        self._refresh_btn.set_margin_start(12)
        self._refresh_btn.set_margin_end(12)
        self.append(self._refresh_btn)

    def set_status(self, status, message=""):
        icons = {"ok": "emblem-ok-symbolic", "searching": "emblem-synchronizing-symbolic",
                 "warning": "dialog-warning-symbolic", "error": "dialog-error-symbolic"}
        self._status_icon.set_from_icon_name(icons.get(status, "emblem-ok-symbolic"))
        self._status_label.set_label(message or status)
    def set_last_check(self, text): self._last_check.set_label(f"Letzte Prüfung: {text}")
    def set_next_check(self, text): self._next_check.set_label(f"Nächste Prüfung: {text}")
    def set_retry(self, current, maximum):
        if current > 0:
            self._retry_label.set_label(f"Retry: {current}/{maximum}")
            self._retry_label.set_visible(True)
        else: self._retry_label.set_visible(False)
    @property
    def refresh_button(self): return self._refresh_btn
