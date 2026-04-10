"""Server-Verbindungsstatus Widget."""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
import threading

class ConnectionStatus(Gtk.Box):
    def __init__(self, api_client=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.api_client = api_client
        self._icon = Gtk.Image.new_from_icon_name("network-offline-symbolic")
        self.append(self._icon)
        self._label = Gtk.Label(label="Nicht verbunden")
        self._label.add_css_class("dim-label")
        self.append(self._label)
        self._connected = False
    @property
    def is_connected(self): return self._connected
    def check_connection(self):
        if not self.api_client:
            self._set_status(False, "Kein Server konfiguriert"); return
        self._label.set_label("Verbinde...")
        def run():
            ok, msg = self.api_client.test_connection()
            GLib.idle_add(self._set_status, ok, msg)
        threading.Thread(target=run, daemon=True).start()
    def _set_status(self, connected, message=""):
        self._connected = connected
        if connected:
            self._icon.set_from_icon_name("network-transmit-receive-symbolic")
            self._label.set_label(message or "Verbunden")
        else:
            self._icon.set_from_icon_name("network-offline-symbolic")
            self._label.set_label(message or "Nicht verbunden")
    def set_offline(self): self._set_status(False, "Standalone")
