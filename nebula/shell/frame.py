"""Nebula shell — the frame around the screen and the desktop clock."""
import math
import time

from gi.repository import GLib, Gtk, Gtk4LayerShell as LS

import common as C
from common import box, label

INNER_R = 22         # corner radius of the "screen" inside the frame


class Frame:
    """Strips in the panel color on the left, right and bottom, plus rounded inner corners.

    Three narrow surfaces (left, right, bottom) instead of one transparent full-screen one:
    niri only has to blend these strips with the picture, not every pixel on the screen.
    The TOP layer sits above windows (windows stay out — struts in nebula-settings.kdl) and
    lets the mouse through. The menu bar isn't covered: the strips start below it."""

    def __init__(self, shell):
        self.shell = shell
        self.parts = {}
        for side in ("left", "right", "bottom"):
            win = Gtk.Window(application=shell)
            LS.init_for_window(win)
            LS.set_namespace(win, "nebula-frame")
            LS.set_layer(win, LS.Layer.TOP)
            LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
            LS.set_exclusive_zone(win, -1)
            edges = {"left": (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT),
                     "right": (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.RIGHT),
                     "bottom": (LS.Edge.LEFT, LS.Edge.RIGHT, LS.Edge.BOTTOM)}[side]
            for e in edges:
                LS.set_anchor(win, e, True)
            win.add_css_class("backdrop")
            da = Gtk.DrawingArea(hexpand=True, vexpand=True)
            da.set_draw_func(self.draw, side)
            win.set_child(da)
            C.click_through(win)
            self.parts[side] = (win, da)
        self.apply()

    def apply(self):
        self.t = C.frame_size()
        self.bar_h = C.bar_height()
        t, r = self.t, INNER_R
        for side, (win, da) in self.parts.items():
            if t <= 0:
                win.set_visible(False)
                continue
            if side == "bottom":
                LS.set_margin(win, LS.Edge.LEFT, t + r)
                LS.set_margin(win, LS.Edge.RIGHT, t + r)
                da.set_size_request(-1, t)
            else:
                LS.set_margin(win, LS.Edge.TOP, self.bar_h)
                da.set_size_request(t + r, -1)
            win.set_default_size(1, 1)
            win.present()
            da.queue_draw()

    def on_theme(self):
        for _win, da in self.parts.values():
            da.queue_draw()

    def draw(self, _da, cr, w, h, side):
        # draw the shared "screen inside the frame" outline in screen coordinates, shifted for this strip
        g = C.monitor_geometry()
        sw, sh = g.width, g.height
        t, r, top = self.t, INNER_R, self.bar_h
        ox, oy = {"left": (0, top), "right": (sw - w, top), "bottom": (t + r, sh - h)}[side]
        cr.translate(-ox, -oy)
        cr.set_source_rgb(*C.hex_to_rgb(self.shell.colors["bg"]))
        cr.set_fill_rule(1)   # EVEN_ODD: the outer rectangle minus the "screen"
        cr.rectangle(0, top, sw, sh - top)
        x0, y0, x1, y1 = t, top, sw - t, sh - t
        cr.new_sub_path()
        cr.arc(x1 - r, y0 + r, r, -math.pi / 2, 0)
        cr.arc(x1 - r, y1 - r, r, 0, math.pi / 2)
        cr.arc(x0 + r, y1 - r, r, math.pi / 2, math.pi)
        cr.arc(x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.fill()


POSITIONS = ("top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right")
WEIGHTS = {"thin": 200, "light": 300, "regular": 500, "bold": 700}


class DesktopClock:
    """A big clock and date on the wallpaper (BOTTOM layer: above the wallpaper, below windows).
    Position (9 spots), size, font, weight and color come from DESK_CLOCK_* in settings.conf.
    It updates once a minute, right as the minute turns; the digits change with a soft crossfade."""

    def __init__(self, shell):
        self.shell = shell
        win = Gtk.Window(application=shell)
        LS.init_for_window(win)
        LS.set_namespace(win, "nebula-desktop")
        LS.set_layer(win, LS.Layer.BOTTOM)
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        LS.set_exclusive_zone(win, -1)
        win.add_css_class("backdrop")
        self.times = [label("", "desk-time", xalign=0.5, ellipsize=False) for _ in range(2)]
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=450,
                               interpolate_size=False)
        for i, t in enumerate(self.times):
            self.stack.add_named(t, str(i))
        self.date = label("", "desk-date", xalign=0.5, ellipsize=False)
        self.box = box("v", 0, "desk", self.date, self.stack)
        win.set_child(self.box)
        C.click_through(win)
        self.win = win
        self.timer = None
        self.cur = 0
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(win.get_display(), self.provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        self.apply()

    def apply(self):
        s = C.settings()
        if s.get("DESKTOP_CLOCK", "1") != "1":
            self.win.set_visible(False)
            if self.timer:
                GLib.source_remove(self.timer)
                self.timer = None
            return
        pos = s.get("DESK_CLOCK_POS", "top")
        pos = pos if pos in POSITIONS else "top"
        g = C.monitor_geometry()
        vert = "top" if pos.startswith("top") else "bottom" if pos.startswith("bottom") else ""
        horiz = "left" if pos.endswith("left") else "right" if pos.endswith("right") else ""
        for edge, on in ((LS.Edge.TOP, vert == "top"), (LS.Edge.BOTTOM, vert == "bottom"),
                         (LS.Edge.LEFT, horiz == "left"), (LS.Edge.RIGHT, horiz == "right")):
            LS.set_anchor(self.win, edge, on)
        LS.set_margin(self.win, LS.Edge.TOP, int(g.height * 0.13))
        LS.set_margin(self.win, LS.Edge.BOTTOM, int(g.height * 0.14))
        LS.set_margin(self.win, LS.Edge.LEFT, int(g.width * 0.04))
        LS.set_margin(self.win, LS.Edge.RIGHT, int(g.width * 0.04))
        xa = 0.0 if horiz == "left" else 1.0 if horiz == "right" else 0.5
        for w in (*self.times, self.date):
            w.set_xalign(xa)
        self.date.set_visible(s.get("DESK_CLOCK_DATE", "1") == "1")
        self.restyle(s)
        self.tick(animate=False)
        self.win.set_default_size(1, 1)
        self.win.present()

    def on_theme(self):
        self.restyle(C.settings())

    def restyle(self, s):
        try:
            k = max(40, min(220, int(s.get("DESK_CLOCK_SIZE") or 100))) / 100
        except ValueError:
            k = 1.0
        c = self.shell.colors
        font = s.get("DESK_CLOCK_FONT", "").replace('"', "")
        weight = WEIGHTS.get(s.get("DESK_CLOCK_WEIGHT"), 300)
        color = {"accent": c["accent"], "theme": c["fg"]}.get(s.get("DESK_CLOCK_COLOR"), "#ffffff")
        fam = f'"{font}", ' if font else ""
        self.provider.load_from_string(f"""
.desk-time {{ font-family: {fam}"Inter Display", "Inter", sans-serif; font-size: {round(112 * k)}px;
    font-weight: {weight}; letter-spacing: {-3 * k:.1f}px; color: {color}; }}
.desk-date {{ font-family: {fam}"Inter", sans-serif; font-size: {max(11, round(20 * k))}px;
    color: {C.rgba(color, 0.85)}; }}
""")

    def tick(self, animate=True):
        now = time.localtime()
        h24 = C.settings().get("CLOCK_24H", "1") == "1"
        text = time.strftime("%H:%M", now) if h24 else time.strftime("%I:%M", now).lstrip("0")
        if text != self.times[self.cur].get_text():
            if animate and self.times[self.cur].get_text():
                self.cur ^= 1
                self.times[self.cur].set_text(text)
                self.stack.set_visible_child_name(str(self.cur))
            else:
                self.times[self.cur].set_text(text)
                self.stack.set_visible_child_full(str(self.cur), Gtk.StackTransitionType.NONE)
        self.date.set_text(C.date_text(now))
        # next run — exactly at the turn of the minute
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add_seconds(max(1, 60 - now.tm_sec), self._tick_cb)

    def _tick_cb(self):
        self.timer = None
        self.tick()
        return False
