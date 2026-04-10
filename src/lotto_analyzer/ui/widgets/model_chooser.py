"""AI-Modell Auswahl Widget."""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject
from lotto_common.models.ai_config import AIModel

class ModelChooser(Gtk.Box):
    __gsignals__ = {"model-changed": (GObject.SignalFlags.RUN_LAST, None, (str,))}
    def __init__(self, current_model=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._model_values = []
        self.append(Gtk.Label(label="Modell:"))
        self._dropdown = Gtk.DropDown()
        model_names = Gtk.StringList()
        for model_id, display in AIModel.display_names().items():
            model_names.append(display)
            self._model_values.append(model_id)
        self._dropdown.set_model(model_names)
        if current_model and current_model in self._model_values:
            self._dropdown.set_selected(self._model_values.index(current_model))
        else:
            self._dropdown.set_selected(2)
        self._dropdown.connect("notify::selected", self._on_changed)
        self._dropdown.set_hexpand(True)
        self.append(self._dropdown)
    @property
    def selected_model(self):
        idx = self._dropdown.get_selected()
        if 0 <= idx < len(self._model_values): return self._model_values[idx]
        return self._model_values[0]
    def _on_changed(self, dropdown, pspec):
        self.emit("model-changed", self.selected_model)
