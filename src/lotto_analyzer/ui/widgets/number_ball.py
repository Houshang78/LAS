"""Lotto-Kugel Widget für GTK4."""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
import math
import cairo

BALL_SIZE = 48
COLORS = {
    "default": (0.208, 0.518, 0.894),
    "match": (0.149, 0.635, 0.412),
    "no_match": (0.627, 0.627, 0.627),
    "highlight": (0.878, 0.106, 0.141),
    "super": (0.902, 0.624, 0.0),
}


class NumberBall(Gtk.DrawingArea):
    """Eine Lotto-Kugel mit Zahl."""
    def __init__(self, number=0, style="default", size=BALL_SIZE):
        super().__init__()
        self._number = number
        self._style = style
        self._size = size
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self._draw)

    @property
    def number(self):
        return self._number

    @number.setter
    def number(self, value):
        self._number = value
        self.queue_draw()

    @property
    def style(self):
        return self._style

    @style.setter
    def style(self, value):
        self._style = value
        self.queue_draw()

    def _draw(self, area, cr, width, height):
        r, g, b = COLORS.get(self._style, COLORS["default"])
        cx, cy = width / 2, height / 2
        radius = min(width, height) / 2 - 2
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.set_source_rgb(r, g, b)
        cr.fill_preserve()
        cr.set_source_rgba(0, 0, 0, 0.2)
        cr.set_line_width(1.5)
        cr.stroke()
        # Glanz
        gradient = cairo.RadialGradient(
            cx - radius * 0.2, cy - radius * 0.2, 0, cx, cy, radius)
        gradient.add_color_stop_rgba(0, 1, 1, 1, 0.3)
        gradient.add_color_stop_rgba(1, 1, 1, 1, 0)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.set_source(gradient)
        cr.fill()
        # Zahl
        if self._number > 0:
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL,
                                cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(radius * 0.8)
            text = str(self._number)
            extents = cr.text_extents(text)
            cr.move_to(cx - extents.width / 2 - extents.x_bearing,
                       cy - extents.height / 2 - extents.y_bearing)
            cr.set_source_rgb(1, 1, 1)
            cr.show_text(text)


class NumberBallRow(Gtk.Box):
    """Reihe von 6 Lotto-Kugeln + optionale Superzahl."""
    def __init__(self, numbers=None, super_number=None,
                 matching=None, size=BALL_SIZE):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.set_halign(Gtk.Align.CENTER)
        self._balls = []
        self._super_ball = None
        numbers = numbers or []
        matching = matching or []
        for num in sorted(numbers):
            style = "match" if num in matching else "default"
            ball = NumberBall(num, style=style, size=size)
            self._balls.append(ball)
            self.append(ball)
        if super_number is not None:
            sep = Gtk.Label(label="|")
            sep.add_css_class("dim-label")
            self.append(sep)
            self._super_ball = NumberBall(super_number, style="super", size=size)
            self.append(self._super_ball)

    def set_numbers(self, numbers, super_number=None, matching=None):
        while self.get_first_child():
            self.remove(self.get_first_child())
        self._balls.clear()
        matching = matching or []
        for num in sorted(numbers):
            style = "match" if num in matching else "default"
            ball = NumberBall(num, style=style)
            self._balls.append(ball)
            self.append(ball)
        if super_number is not None:
            sep = Gtk.Label(label="|")
            sep.add_css_class("dim-label")
            self.append(sep)
            self._super_ball = NumberBall(super_number, style="super")
            self.append(self._super_ball)
