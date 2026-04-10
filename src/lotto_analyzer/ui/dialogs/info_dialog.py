"""Wiederverwendbarer Info-Dialog mit Kopieren/Speichern/Schliessen."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib


class InfoDialog(Adw.Dialog):
    """Modaler Info-Dialog: scrollbarer Text, Kopieren + Speichern."""

    def __init__(self, title: str, text: str):
        super().__init__()
        self.set_title(title)
        self.set_content_width(600)
        self.set_content_height(500)

        self._text = text
        self._build_ui()

    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(outer)

        # Header
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        outer.append(header)

        # Scrollbarer Text
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_margin_start(16)
        scrolled.set_margin_end(16)
        scrolled.set_margin_top(8)
        scrolled.set_margin_bottom(8)
        outer.append(scrolled)

        self._text_view = Gtk.TextView()
        self._text_view.set_editable(False)
        self._text_view.set_cursor_visible(False)
        self._text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._text_view.set_monospace(True)
        self._text_view.set_left_margin(8)
        self._text_view.set_right_margin(8)
        self._text_view.set_top_margin(8)
        self._text_view.set_bottom_margin(8)
        self._text_view.get_buffer().set_text(self._text)
        scrolled.set_child(self._text_view)

        # Button-Reihe
        btn_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            halign=Gtk.Align.END,
        )
        btn_box.set_margin_start(16)
        btn_box.set_margin_end(16)
        btn_box.set_margin_bottom(16)

        copy_btn = Gtk.Button(label="Kopieren")
        copy_btn.set_tooltip_text("Text in die Zwischenablage kopieren")
        copy_btn.set_icon_name("edit-copy-symbolic")
        copy_btn.connect("clicked", self._on_copy)
        btn_box.append(copy_btn)

        save_btn = Gtk.Button(label="Speichern")
        save_btn.set_tooltip_text("Text als Datei speichern")
        save_btn.set_icon_name("document-save-symbolic")
        save_btn.connect("clicked", self._on_save)
        btn_box.append(save_btn)

        close_btn = Gtk.Button(label="Schliessen")
        close_btn.set_tooltip_text("Dialog schliessen")
        close_btn.add_css_class("suggested-action")
        close_btn.connect("clicked", lambda _: self.close())
        btn_box.append(close_btn)

        outer.append(btn_box)

    def _on_copy(self, button: Gtk.Button) -> None:
        """Text in Clipboard kopieren."""
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(self._text)
        button.set_label("Kopiert!")
        GLib.timeout_add(1500, lambda: button.set_label("Kopieren") or False)

    def _on_save(self, button: Gtk.Button) -> None:
        """Text als .txt-Datei speichern (FileDialog)."""
        dialog = Gtk.FileDialog()
        dialog.set_initial_name("info.txt")
        dialog.save(self.get_root(), None, self._on_save_done)

    def _on_save_done(self, dialog: Gtk.FileDialog, result) -> None:
        """Datei schreiben."""
        try:
            gfile = dialog.save_finish(result)
            if gfile:
                path = gfile.get_path()
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self._text)
        except GLib.Error:
            pass

    @staticmethod
    def show(parent: Gtk.Widget, title: str, text: str) -> "InfoDialog":
        """Convenience: Dialog erstellen und anzeigen."""
        dlg = InfoDialog(title, text)
        dlg.present(parent)
        return dlg
