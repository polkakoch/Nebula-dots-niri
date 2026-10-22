"""Nebula shell — the Control Center: a side panel on the right with tiles, sliders and settings.

The main page is a grid of tiles (network, Do Not Disturb, brightness,
sound, music), with notifications and the settings list below. Settings open as subpages that
slide in from the right; "‹ Back" slides back.
"""
import os
import time
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk, Gtk4LayerShell as LS

import common as C
import gallery
import services as S
from common import I, box, icon, label, tr

W = 380            # panel width
GAP = 8            # distance from the screen edge
# The hidden position leaves a couple of pixels on screen — niri sends no frames to a fully
# invisible surface (the timer in Tween is a safety net for that too)
OFF = -(W + C.EAR - 2)


# ─── small building blocks ──────────────────────────────────────────────────
def card(*children, cls="", spacing=6):
    return box("v", spacing, ("card " + cls).strip(), *children)


def make_switch(active, on_toggle):
    sw = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
    sw._guard = False

    def changed(s, _p):
        if not s._guard:
            on_toggle(s.get_active())
    sw.connect("notify::active", changed)

    def setv(v):
        sw._guard = True
        sw.set_active(bool(v))
        sw._guard = False
    sw.setv = setv
    return sw


def opt(title, sub=None, widget=None):
    texts = box("v", 1, None, label(title, "t"), label(sub, "s", wrap=True) if sub else None,
                hexpand=True, valign=Gtk.Align.CENTER)
    return box("h", 12, "opt", texts, widget)


def segmented(options, current, on_change):
    seg = box("h", 2, "segmented", homogeneous=True)
    btns = {}

    def pick(v, fire=True):
        for k, b in btns.items():
            C.set_class(b, "on", k == v)
        if fire:
            on_change(v)
    for value, text in options:
        b = C.button(text, None, lambda v=value: pick(v))
        btns[value] = b
        seg.append(b)
    pick(current, fire=False)
    seg.setv = lambda v: pick(v, fire=False)
    return seg


class Slider:
    """A thick slider with an icon inside; the setter is called after a short delay."""

    def __init__(self, glyph, setter, lo=0, hi=100, delay=50, thin=False, fmt=None):
        self.scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, draw_value=False, hexpand=True)
        self.scale.set_range(lo, hi)
        self.scale.set_increments(1, 5)
        self.setter, self.delay, self.pending, self.guard = setter, delay, None, False
        self.scale.connect("value-changed", self.changed)
        self.fmt = fmt
        if thin:
            self.scale.add_css_class("thin")
            self.value_lbl = label("", "small dim", xalign=1.0, ellipsize=False)
            self.value_lbl.set_size_request(46, -1)
            self.widget = box("h", 10, None, self.scale, self.value_lbl)
            self.icon = None
        else:
            self.icon = icon(glyph, "slider-icon")
            self.icon.set_halign(Gtk.Align.START)
            self.icon.set_valign(Gtk.Align.CENTER)
            self.icon.set_can_target(False)
            ov = Gtk.Overlay()
            ov.set_child(self.scale)
            ov.add_overlay(self.icon)
            self.widget = ov
            self.value_lbl = None

    def changed(self, s):
        v = s.get_value()
        if self.value_lbl is not None and self.fmt:
            self.value_lbl.set_text(self.fmt(v))
        if self.guard:
            return
        if self.pending:
            GLib.source_remove(self.pending)

        def fire():
            self.pending = None
            self.setter(self.scale.get_value())
            return False
        self.pending = GLib.timeout_add(self.delay, fire)

    def setv(self, v):
        self.guard = True
        self.scale.set_value(v)
        if self.value_lbl is not None and self.fmt:
            self.value_lbl.set_text(self.fmt(v))
        self.guard = False


class Avatar(Gtk.Stack):
    def __init__(self, size):
        super().__init__()
        self.size = size
        self.pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        self.pic.set_size_request(size, size)
        self.pic.add_css_class("avatar")
        self.pic.set_overflow(Gtk.Overflow.HIDDEN)
        self.fallback = label("", "avatar-fallback", xalign=0.5, ellipsize=False)
        self.fallback.set_size_request(size, size)
        self.add_named(self.pic, "pic")
        self.add_named(self.fallback, "fb")
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.mtime = None
        self.update()

    def update(self):
        face = S.FACE
        try:
            mt = face.stat().st_mtime
        except OSError:
            mt = None
        if mt and mt == self.mtime:
            return
        self.mtime = mt
        scale = max(1, self.get_scale_factor() or 1)
        tex = C.texture_scaled(face, self.size * 2 * scale, self.size * 2 * scale) if mt else None
        if tex:
            self.pic.set_paintable(tex)
            self.set_visible_child_name("pic")
        else:
            real, _login = C.user_name()
            ini = "".join(w[0] for w in real.split()[:2]).upper() or "?"
            self.fallback.set_markup(f"<span size='{int(self.size * 0.4 * 1024)}'>{GLib.markup_escape_text(ini)}</span>")
            self.set_visible_child_name("fb")


class Cropper(Gtk.DrawingArea):
    """Cropping the profile photo: drag to move, scroll or the slider to zoom.
    The visible area is a circle — exactly how the photo looks everywhere (panel, lock screen, login)."""

    SIZE = 240

    def __init__(self):
        super().__init__(content_width=self.SIZE, content_height=self.SIZE, halign=Gtk.Align.CENTER)
        self.add_css_class("cropper")
        self.pb = None
        self.zoom, self.cx, self.cy = 1.0, 0.5, 0.5    # crop center, as fractions of the picture
        self.on_zoom = None
        self.set_draw_func(self.draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", lambda *_: self.__setattr__("start", (self.cx, self.cy)))
        drag.connect("drag-update", self.on_drag)
        self.add_controller(drag)
        sc = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        sc.connect("scroll", lambda _c, _dx, dy: self.set_zoom(self.zoom * (0.92 if dy > 0 else 1.08)) or True)
        self.add_controller(sc)
        self.set_cursor(Gdk.Cursor.new_from_name("grab"))

    def load(self, path):
        from gi.repository import GdkPixbuf
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 900, 900, True)
            pb = pb.apply_embedded_orientation() or pb
        except Exception:
            self.pb = None
            return False
        self.pb = pb
        self.zoom, self.cx, self.cy = 1.0, 0.5, 0.5
        self.queue_draw()
        return True

    def base_scale(self):
        """The scale at which the picture exactly covers the crop square (zoom = 1)."""
        return self.SIZE / min(self.pb.get_width(), self.pb.get_height())

    def clamp(self):
        k = self.base_scale() * self.zoom
        hw = self.SIZE / 2 / (self.pb.get_width() * k)
        hh = self.SIZE / 2 / (self.pb.get_height() * k)
        self.cx = min(max(self.cx, hw), 1 - hw)
        self.cy = min(max(self.cy, hh), 1 - hh)

    def set_zoom(self, z):
        if not self.pb:
            return
        self.zoom = min(4.0, max(1.0, z))
        self.clamp()
        self.queue_draw()
        if self.on_zoom:
            self.on_zoom(self.zoom)

    def on_drag(self, _g, dx, dy):
        if not self.pb:
            return
        k = self.base_scale() * self.zoom
        self.cx = self.start[0] - dx / (self.pb.get_width() * k)
        self.cy = self.start[1] - dy / (self.pb.get_height() * k)
        self.clamp()
        self.queue_draw()

    def paint(self, cr, size):
        """Draw a size×size crop (for the screen and for saving)."""
        k = self.base_scale() * self.zoom * size / self.SIZE
        cr.save()
        cr.translate(size / 2 - self.cx * self.pb.get_width() * k, size / 2 - self.cy * self.pb.get_height() * k)
        cr.scale(k, k)
        Gdk.cairo_set_source_pixbuf(cr, self.pb, 0, 0)
        cr.get_source().set_filter(1)   # GOOD
        cr.paint()
        cr.restore()

    def draw(self, _da, cr, w, h):
        import math
        if not self.pb:
            return
        self.paint(cr, self.SIZE)
        # darken around the circle and add a thin outline
        cr.set_fill_rule(1)
        cr.rectangle(0, 0, w, h)
        cr.arc(w / 2, h / 2, self.SIZE / 2 - 2, 0, 2 * math.pi)
        cr.set_source_rgba(0, 0, 0, 0.55)
        cr.fill()
        cr.arc(w / 2, h / 2, self.SIZE / 2 - 2, 0, 2 * math.pi)
        cr.set_source_rgba(1, 1, 1, 0.7)
        cr.set_line_width(1.5)
        cr.stroke()

    def save(self, dst, size=512):
        import cairo
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, size, size)
        cr = cairo.Context(surf)
        self.paint(cr, size)
        surf.write_to_png(str(dst))


# ─── menu bar: modules and style previews ────────────────────────────────────
BAR_MODS = [
    ("logo", tr("Логотип"), "\U000f08c7"), ("workspaces", tr("Рабочие столы"), "\U000f0570"),
    ("window", tr("Заголовок окна"), "\U000f05d8"), ("media", tr("Плеер"), "\U000f0386"),
    ("tray", tr("Трей"), "\U000f0147"), ("volume", tr("Громкость"), "\U000f057e"),
    ("brightness", tr("Яркость"), "\U000f00e0"), ("language", tr("Язык"), "\U000f030c"),
    ("network", tr("Сеть"), "\U000f05a9"), ("bluetooth", "Bluetooth", "\U000f00af"),
    ("battery", tr("Батарея"), "\U000f0079"), ("cpu", tr("Процессор"), "\U000f0ee0"),
    ("memory", tr("Память"), "\U000f035b"), ("control", tr("Пункт управления"), "\U000f0493"),
    ("clock", tr("Часы"), "\U000f0954"), ("power", tr("Питание"), "\U000f0425"),
]
BAR_ZONES = [("left", tr("Слева")), ("center", tr("В центре")), ("right", tr("Справа")), ("hidden", tr("Не показаны"))]
BAR_STYLES = [("frame", tr("Рамка"), tr("Переходит в рамку экрана")), ("floating", tr("Плавающая"), tr("Стекло с блюром")),
              ("classic", tr("Классика"), tr("Во всю ширину, с блюром")), ("islands", tr("Острова"), tr("Слева, центр, справа")),
              ("pills", tr("Таблетки"), tr("Каждый модуль отдельно")), ("notch", tr("Чёлка"), tr("Центр свисает сверху")),
              ("minimal", tr("Минимал"), tr("Без фона"))]
BAR_MIME = "application/x-nebula-barmod"
KB_LAYOUTS = [("us,ru", "EN + RU"), ("us,ru,ua", "+ UA"), ("us,ua", "EN + UA"), ("us", tr("Только EN"))]
KB_SWITCHES = [("caps", "Caps Lock"), ("alt_shift", "Alt+Shift"), ("ctrl_shift", "Ctrl+Shift"), ("ralt", tr("Прав. Alt"))]
CORNERS = [("off", tr("Нет")), ("top-left", "↖"), ("top-right", "↗"), ("bottom-left", "↙"), ("bottom-right", "↘")]


def draw_bar_preview(cr, w, h, style, c, selected):
    """A tiny screen: a wallpaper (a gradient from the palette) and a menu bar in the chosen style."""
    import math

    def rr(x, y, ww, hh, r):
        r = min(r, ww / 2, hh / 2)
        cr.new_sub_path()
        cr.arc(x + ww - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + ww - r, y + hh - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + hh - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
    bg, fg, acc = C.hex_to_rgb(c["bg"]), C.hex_to_rgb(c["fg"]), C.hex_to_rgb(c["accent"])
    acc2 = C.hex_to_rgb(c.get("accent2", c["accent"]))
    import cairo
    rr(0, 0, w, h, 10)
    cr.save()
    cr.clip()
    g = cairo.LinearGradient(0, 0, w, h)
    g.add_color_stop_rgba(0, *acc, 0.55)
    g.add_color_stop_rgba(1, *acc2, 0.25)
    cr.set_source_rgb(*bg)
    cr.paint()
    cr.set_source(g)
    cr.paint()
    bh = 9
    if style == "frame":
        t = 3
        cr.set_source_rgb(*bg)
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(0, 0, w, h)
        rr(t, bh, w - 2 * t, h - bh - t, 6)
        cr.fill()
        cr.set_fill_rule(cairo.FILL_RULE_WINDING)
        y = bh / 2
    elif style == "floating":
        cr.set_source_rgba(*bg, 0.80)
        rr(5, 4, w - 10, bh, 4)
        cr.fill()
        y = 4 + bh / 2
    elif style == "pills":
        cr.set_source_rgba(*bg, 0.92)
        for x, ww in ((5, 16), (24, 22), (w / 2 - 14, 28), (w - 47, 18), (w - 26, 21)):
            rr(x, 4, ww, bh, 4.5)
            cr.fill()
        y = 4 + bh / 2
    elif style == "classic":
        cr.set_source_rgba(*bg, 0.70)
        cr.rectangle(0, 0, w, bh + 1)
        cr.fill()
        y = (bh + 1) / 2
    elif style == "islands":
        cr.set_source_rgba(*bg, 0.92)
        for x0, x1 in ((5, 30), (w / 2 - 12, w / 2 + 12), (w - 45, w - 6)):
            rr(x0, 4, x1 - x0, bh, 4.5)
            cr.fill()
        y = 4 + bh / 2
    elif style == "notch":
        cr.set_source_rgb(*bg)
        x0, x1, r = w / 2 - 14, w / 2 + 14, 4.5
        cr.move_to(x0, 0)
        cr.line_to(x1, 0)
        cr.arc(x1 - r, bh + 1 - r, r, 0, math.pi / 2)
        cr.arc(x0 + r, bh + 1 - r, r, math.pi / 2, math.pi)
        cr.close_path()
        cr.fill()
        y = (bh + 1) / 2
    else:
        y = 6
    # "text and icons" on the bar
    cr.set_source_rgba(*fg, 0.85)
    for x, ww in ((9, 4), (16, 10), (w / 2 - 8, 16), (w - 22, 12), (w - 40, 5)):
        rr(x, y - 1.2, ww, 2.4, 1.2)
        cr.fill()
    # a window
    top = bh + (6 if style == "frame" else 8)
    cr.set_source_rgba(*bg, 0.55)
    rr(10 if style != "frame" else 8, top, w - (20 if style != "frame" else 16), h - top - 8, 4)
    cr.fill()
    cr.restore()
    rr(0.75, 0.75, w - 1.5, h - 1.5, 10)
    if selected:
        cr.set_source_rgb(*acc)
        cr.set_line_width(2.5)
    else:
        cr.set_source_rgba(*fg, 0.12)
        cr.set_line_width(1)
    cr.stroke()


# ─── the panel ──────────────────────────────────────────────────────────────
class Panel:
    def __init__(self, shell):
        self.shell = shell
        self.visible = False
        self.anim = None
        self.page = "main"
        self.pages = {}
        self.wifi = None
        self.bt = S.Bluetooth()
        self.clock_timer = None
        shell.notifs.listeners.append(self.on_notify_changed)

        win = Gtk.Window(application=shell)
        LS.init_for_window(win)
        LS.set_namespace(win, "nebula-panel")
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(win, LS.KeyboardMode.EXCLUSIVE)
        for e in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.RIGHT):
            LS.set_anchor(win, e, True)
        LS.set_margin(win, LS.Edge.RIGHT, OFF)
        self.win = win

        self.root = box("v", 0, "panel")
        self.root.set_size_request(W, -1)
        self.root.set_overflow(Gtk.Overflow.HIDDEN)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
                               transition_duration=300, hhomogeneous=True, vhomogeneous=False, vexpand=True)
        self.root.append(self.stack)
        self.sheet = C.Sheet("right", self.root, lambda: shell.colors)
        win.set_child(self.sheet)

        self.builders = {
            "wifi": self.build_wifi, "bluetooth": self.build_bt, "sound": self.build_sound,
            "appearance": self.build_appearance, "fetch": self.build_fetch, "display": self.build_display,
            "time": self.build_time, "bar": self.build_bar, "desktop": self.build_desktop, "windows": self.build_windows,
            "profile": self.build_profile, "notifications": self.build_notifications,
            "walls": self.build_walls, "clip": self.build_clip, "power": self.build_power,
            "input": self.build_input, "claude": self.build_claude, "extras": self.build_extras,
        }
        self.build_main()

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)

    # ── show / hide ────────────────────────────────────────────────────────
    def toggle(self, page=None):
        if self.visible and (page is None or page == self.page):
            self.hide()
        else:
            self.show(page)

    def show(self, page=None):
        self.shell.close_others(self)
        first = not self.visible
        self.visible = True
        self.sheet.refresh()
        self.refresh_main()
        if page and page in self.builders:
            self.push(page, animate=not first)
        elif first:
            self.go_main(animate=False)
        if first:
            self.shell.backdrop_show(self)
            self.win.present()
            if self.anim:
                self.anim.cancel()
            start = OFF
            self.root.set_opacity(1)
            self.anim = C.Tween(self.win, 0.42,
                                lambda v: LS.set_margin(self.win, LS.Edge.RIGHT, int(start + (0 - start) * v)),
                                C.ease_out_quint)

    def hide(self, then=None):
        if not self.visible:
            return
        self.visible = False
        self.shell.backdrop_hide(self)
        self.stop_clock()
        if self.anim:
            self.anim.cancel()
        end = OFF

        def done():
            if not self.visible:
                self.win.set_visible(False)
                self.go_main(animate=False)   # this also leaves whatever page was open
            if then:
                then()
        self.anim = C.Tween(self.win, 0.26,
                            lambda v: LS.set_margin(self.win, LS.Edge.RIGHT, int(end * v)),
                            C.ease_in_cubic, done=done)

    def on_key(self, _c, keyval, _code, _state):
        if Gdk.keyval_name(keyval) == "Escape":
            if self.page != "main":
                self.go_main()
            else:
                self.hide()
            return True
        return False

    def on_theme(self):
        self.sheet.da.queue_draw()
        for p in ("appearance",):
            if p in self.pages and hasattr(self, "theme_tiles"):
                for t in self.theme_tiles:
                    t.da.queue_draw()

    # ── navigation ─────────────────────────────────────────────────────────
    def leave_page(self):
        pg = self.pages.get(self.page)
        if pg and pg.get("leave"):
            pg["leave"]()

    def push(self, name, animate=True):
        if name != self.page:
            self.leave_page()
        if name not in self.pages:
            self.pages[name] = self.builders[name]()
            self.stack.add_named(self.pages[name]["widget"], name)
        self.page = name
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT if animate
                                       else Gtk.StackTransitionType.NONE)
        refresh = self.pages[name].get("refresh")
        if refresh:
            refresh()
        self.stack.set_visible_child_name(name)
        self.stop_clock() if name != "time" else None

    def go_main(self, animate=True):
        if self.page != "main":
            self.leave_page()
        self.page = "main"
        self.stop_clock()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_RIGHT if animate
                                       else Gtk.StackTransitionType.NONE)
        self.stack.set_visible_child_name("main")

    def subpage(self, title, header_widget=None):
        back = C.button(box("h", 2, None, icon(I["left"]), Gtk.Label(label=tr("Назад"))), "back", self.go_main)
        head = box("h", 8, "pagehead", back, label(title, "ptitle", xalign=0.5, hexpand=True))
        spacer = Gtk.Box()
        spacer.set_size_request(70, -1)
        head.append(header_widget or spacer)
        if header_widget:
            header_widget.set_size_request(70, -1)
            header_widget.set_halign(Gtk.Align.END)
        content = box("v", 12)
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sc.set_child(content)
        outer = box("v", 0, "page", head, sc)
        return outer, content

    def file_dialog(self, title, done, folder=False, multiple=False, images=True):
        """A file dialog on top of everything: hide the panel (it holds the keyboard), then bring it back."""
        page = self.page

        def open_dialog():
            dlg = Gtk.FileDialog(title=title, modal=True)
            if images and not folder:
                f = Gtk.FileFilter()
                f.set_name(tr("Картинки"))
                f.add_mime_type("image/*")
                store = Gio.ListStore.new(Gtk.FileFilter)
                store.append(f)
                dlg.set_filters(store)
                dlg.set_default_filter(f)
            pics = C.HOME / "Pictures"
            if pics.is_dir():
                dlg.set_initial_folder(Gio.File.new_for_path(str(pics)))

            def fin(d, res):
                paths = []
                try:
                    if folder:
                        f = d.select_folder_finish(res)
                        paths = [f.get_path()] if f else []
                    elif multiple:
                        lst = d.open_multiple_finish(res)
                        paths = [lst.get_item(i).get_path() for i in range(lst.get_n_items())] if lst else []
                    else:
                        f = d.open_finish(res)
                        paths = [f.get_path()] if f else []
                except GLib.Error:
                    paths = []
                paths = [p for p in paths if p]
                if paths:
                    done(paths)
                GLib.timeout_add(250, lambda: self.show(page) or False)
            if folder:
                dlg.select_folder(None, None, fin)
            elif multiple:
                dlg.open_multiple(None, None, fin)
            else:
                dlg.open(None, None, fin)
        self.hide(then=open_dialog)

    # ══ main page ══════════════════════════════════════════════════════════
    def build_main(self):
        content = box("v", 10, "page")

        # profile
        self.avatar = Avatar(42)
        av_btn = C.button(self.avatar, None, lambda: self.push("profile"), tr("Профиль"))
        av_btn.add_css_class("avatar")
        real, login = C.user_name()
        self.who_name = label(real, "name")
        self.who_sub = label("", "sub")
        who = box("v", 1, "who", self.who_name, self.who_sub, valign=Gtk.Align.CENTER, hexpand=True)
        lock = C.button(icon(I["lock"]), "roundbtn", lambda: (self.hide(), C.spawn([str(C.BIN / "nb-power"), "lock"])),
                        tr("Заблокировать"))
        power = C.button(icon(I["power"]), "roundbtn danger", lambda: self.push("power"), tr("Питание"))
        content.append(box("h", 10, None, av_btn, who, lock, power))

        # network + Do Not Disturb / night light
        self.t_wifi = self.toggle_row(I["wifi"], "Wi-Fi", self.on_wifi_toggle, lambda: self.push("wifi"))
        self.t_bt = self.toggle_row(I["bt"], "Bluetooth", self.on_bt_toggle, lambda: self.push("bluetooth"))
        self.t_caf = self.toggle_row(I["coffee"], tr("Не засыпать"), self.on_caf_toggle, None)
        left = card(self.t_wifi["w"], self.t_bt["w"], self.t_caf["w"], spacing=2)
        left.set_hexpand(True)
        self.m_dnd = self.minitile(I["moon"], tr("Не беспокоить"), self.on_dnd)
        self.m_night = self.minitile(I["night"], tr("Ночной свет"), self.on_night)
        # the right column splits the left card's height evenly
        right = box("v", 8, None, self.m_dnd["w"], self.m_night["w"], hexpand=True, homogeneous=True)
        content.append(box("h", 8, None, left, right, homogeneous=True, vexpand=False))

        self.m_profile = self.minitile(I["speed"], tr("Питание"), self.on_profile)
        self.m_shot = self.minitile(I["camera"], tr("Скриншот"), lambda: (self.hide(), GLib.timeout_add(
            350, lambda: C.spawn([str(C.BIN / "nb-shot")]) or False)))
        self.m_shot["s"].set_text(tr("Область экрана"))
        content.append(box("h", 8, None, self.m_profile["w"], self.m_shot["w"], homogeneous=True))

        # brightness
        self.s_bright = Slider(I["bright"], S.brightness_set)
        self.bright_card = card(label(tr("Экран"), "card-title"), self.s_bright.widget)
        content.append(self.bright_card)

        # sound
        self.s_vol = Slider(I["vol"], self.set_volume)
        vol_more = C.button(icon(I["right"]), "linkbtn", lambda: self.push("sound"), tr("Устройства"))
        self.vol_dev = label("", "tiny muted", xalign=1.0, hexpand=True)
        content.append(card(box("h", 6, None, label(tr("Звук"), "card-title"), self.vol_dev, vol_more),
                            self.s_vol.widget))

        # music
        from media import MediaCard
        self.media = MediaCard(big=False)
        self.media_card = card(self.media)
        content.append(self.media_card)
        self.media.pl.listeners.append(lambda: self.media_card.set_visible(self.media.pl.player is not None))

        # notifications
        self.notif_list = box("v", 6)
        clear = C.button(tr("Очистить"), "linkbtn", self.clear_notifs)
        self.notif_more = C.button(tr("Все"), "linkbtn", lambda: self.push("notifications"))
        content.append(card(box("h", 6, None, label(tr("Уведомления"), "card-title", hexpand=True), self.notif_more, clear),
                            self.notif_list))

        # settings
        rows = [("appearance", I["palette"], "c1", tr("Оформление"), tr("Темы и обои")),
                ("fetch", I["fetch"], "c7", "Fastfetch", tr("Картинка в терминале")),
                ("display", I["monitor"], "c2", tr("Экран"), tr("Масштаб, ночной свет")),
                ("time", I["clock"], "c4", tr("Дата и время"), tr("Язык, формат, часовой пояс")),
                ("bar", I["bar"], "c3", tr("Строка меню"), tr("Стиль, модули, плеер")),
                ("desktop", I["apps"], "c2", tr("Рабочий стол"), tr("Док, часы")),
                ("windows", I["window"], "c5", tr("Окна и анимации"), tr("Прозрачность, скорость, экономия")),
                ("input", I["mouse"], "c3", tr("Управление"), tr("Мышь, тачпад, жесты")),
                ("extras", I["puzzle"], "c4", tr("Дополнения"), tr("Приколы, Claude")),
                ("profile", I["account"], "c6", tr("Профиль"), tr("Фото пользователя"))]
        settings = box("v", 0, "card flat settings")
        self.set_values = {}
        for page, glyph, color, title, sub in rows:
            badge = icon(glyph, f"badge {color}")
            v = label(sub, "v", xalign=1.0)
            self.set_values[page] = v
            row = box("h", 10, "setrow", badge, label(title, "t", hexpand=True), v, icon(I["right"], "chev"))
            b = C.button(row, None, lambda p=page: self.push(p))
            settings.append(b)
        content.append(settings)

        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sc.set_child(content)
        self.main_scroll = sc
        self.stack.add_named(sc, "main")

    def toggle_row(self, glyph, title, on_toggle, on_open):
        circ = C.button(icon(glyph), "circle", lambda: on_toggle())
        circ.set_valign(Gtk.Align.CENTER)
        t, s = label(title, "t"), label("", "s")
        texts = box("v", 0, None, t, s, valign=Gtk.Align.CENTER, hexpand=True)
        if on_open:
            texts_btn = C.button(box("h", 4, None, texts, icon(I["right"], "chev muted")), None, on_open)
            texts_btn.set_hexpand(True)
        else:
            texts_btn = texts
        row = box("h", 10, "toggle-row", circ, texts_btn)
        return {"w": row, "circle": circ, "s": s, "icon": circ.get_child()}

    def minitile(self, glyph, title, on_click):
        circ = icon(glyph, "circle")
        circ.set_valign(Gtk.Align.CENTER)
        t, s = label(title, "t"), label("", "s")
        inner = box("h", 10, None, circ, box("v", 0, None, t, s, valign=Gtk.Align.CENTER, hexpand=True))
        b = C.button(inner, "card minitile", on_click)
        return {"w": b, "circle": circ, "s": s, "t": t}

    def refresh_main(self):
        real, login = C.user_name()
        host = Path("/proc/sys/kernel/hostname").read_text().strip()
        self.who_sub.set_text(f"{login}@{host} · {C.uptime_text()}")
        self.avatar.update()
        # network
        if self.wifi is None:
            self.wifi = S.Wifi()
            self.wifi.listeners.append(self.refresh_wifi_state)
        self.refresh_wifi_state()
        self.refresh_bt_state()

        def caf(on):
            C.set_class(self.t_caf["circle"], "on", on)
            self.t_caf["s"].set_text(tr("Включено") if on else tr("Выключено"))
        S.pgrep_async("systemd-inhibit --what=idle:sleep --who=Nebula", caf, full=True)
        # tiles
        dnd = S.dnd_get()
        C.set_class(self.m_dnd["circle"], "on", dnd)
        self.m_dnd["s"].set_text(tr("Включено") if dnd else tr("Выключено"))

        def night(on):
            C.set_class(self.m_night["circle"], "on", on)
            self.m_night["s"].set_text(tr("Включён") if on else tr("Выключен"))
        S.pgrep_async("wlsunset", night)
        S.profile_get(self.show_profile)
        # sliders
        b = S.brightness_get()
        self.bright_card.set_visible(b is not None)
        if b is not None:
            self.s_bright.setv(b)
        self.refresh_volume()
        self.media_card.set_visible(self.media.pl.player is not None)
        self.media.refresh(force=True)
        self.refresh_notifs()
        # what the settings rows say on the right
        st = C.settings()
        dock = {"autohide": tr("док прячется"), "always": tr("док виден"), "off": tr("без дока")}.get(st["DOCK"], "")
        self.set_values["desktop"].set_text(dock.capitalize())
        self.set_values["bar"].set_text({k: t for k, t, _s in BAR_STYLES}.get(C.bar_style(), ""))
        S.time_info_async(lambda tz, _n, _c: self.set_values["time"].set_text(
            tz.split("/")[-1].replace("_", " ") if tz else ""))
        S.outputs_async(lambda outs: outs and self.set_values["display"].set_text(
            tr("Масштаб {0}%").format(round(outs[0]['scale'] * 100))))
        themes = {t[0]: t[1] for t in C.list_themes()}
        self.set_values["appearance"].set_text(themes.get(C.current_theme_id(), ""))
        self.set_values["fetch"].set_text(tr("Случайная") if st["FETCH_MODE"] == "random" else tr("Выбранная"))
        self.set_values["windows"].set_text(tr("Экономия") if st["ECO"] == "1" else
                                            f"{round(float(st['WIN_OPACITY']) * 100)}% · ×{float(st['ANIM_SPEED']):g}"
                                            if st["ANIM_ENABLED"] == "1" else tr("Без анимаций"))
        self.set_values["profile"].set_text(real)
        self.set_values["input"].set_text(dict(CORNERS).get(st["HOT_CORNER"], tr("Угол выкл.")))

        extras = [t for k, t in (("FUN", tr("Приколы")), ("CLAUDE", "Claude")) if st[k] == "1"]
        self.set_values["extras"].set_text(" · ".join(extras) or tr("Выключены"))

    # ── network ────────────────────────────────────────────────────────────
    def refresh_wifi_state(self):
        w = self.wifi
        if not w or not w.available:
            self.t_wifi["s"].set_text(tr("Нет адаптера"))
            C.set_class(self.t_wifi["circle"], "on", False)
        else:
            act = w.active()
            on = w.enabled
            C.set_class(self.t_wifi["circle"], "on", on)
            self.t_wifi["icon"].set_text(I["wifi"] if on else I["wifi_off"])
            self.t_wifi["s"].set_text(act[0] if act else (tr("Не подключено") if on else tr("Выключено")))
        if "wifi" in self.pages and self.page == "wifi":
            self.pages["wifi"]["refresh"](scan=False)

    def on_wifi_toggle(self):
        if self.wifi and self.wifi.available:
            self.wifi.set_enabled(not self.wifi.enabled)

    def refresh_bt_state(self):
        def got(powered, devs):
            if powered is None:
                self.t_bt["s"].set_text(tr("Нет адаптера"))
                C.set_class(self.t_bt["circle"], "on", False)
                return
            C.set_class(self.t_bt["circle"], "on", powered)
            self.t_bt["icon"].set_text(I["bt"] if powered else I["bt_off"])
            conn = [d[1] for d in devs if d[2]]
            self.t_bt["s"].set_text(", ".join(conn) if conn else (tr("Включён") if powered else tr("Выключен")))
            self.bt_powered = powered
        self.bt.state(got)

    def on_bt_toggle(self):
        self.bt.set_power(not getattr(self, "bt_powered", False), lambda *_: self.refresh_bt_state())

    def on_caf_toggle(self):
        on = not self.t_caf["circle"].has_css_class("on")
        S.caffeine_set(on)
        C.set_class(self.t_caf["circle"], "on", on)
        self.t_caf["s"].set_text(tr("Включено") if on else tr("Выключено"))

    def on_dnd(self):
        on = not self.m_dnd["circle"].has_css_class("on")
        self.shell.notifs.set_dnd(on)
        C.set_class(self.m_dnd["circle"], "on", on)
        self.m_dnd["s"].set_text(tr("Включено") if on else tr("Выключено"))

    def on_night(self):
        on = not self.m_night["circle"].has_css_class("on")
        S.night_set(on, int(C.settings().get("NIGHT_TEMP", "4000") or 4000))
        C.set_class(self.m_night["circle"], "on", on)
        self.m_night["s"].set_text(tr("Включён") if on else tr("Выключен"))

    def show_profile(self, p):
        self.m_profile["w"].set_visible(p is not None)
        self.profile_cur = p
        names = {k: (n, g) for k, n, g in S.PROFILES}
        n, g = names.get(p, ("—", I["speed"]))
        self.m_profile["s"].set_text(n)
        self.m_profile["circle"].set_text(g)
        C.set_class(self.m_profile["circle"], "on", p == "performance")

    def on_profile(self):
        order = [k for k, _n, _g in S.PROFILES]
        cur = getattr(self, "profile_cur", "balanced")
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "balanced"
        S.profile_set(nxt, lambda *_: S.profile_get(self.show_profile))

    # ── sound ──────────────────────────────────────────────────────────────
    def refresh_volume(self):
        def got(v):
            if v:
                self.s_vol.setv(v[0])
                self.s_vol.icon.set_text(I["mute"] if v[1] else I["vol"])
                C.set_class(self.s_vol.icon, "off", v[1])
        S.volume_get_async(got)

        def devs(ds):
            d = next((x for x in ds if x[2]), None)
            self.vol_dev.set_text(d[1] if d else "")
        S.audio_devices("sinks", devs)

    def set_volume(self, v):
        S.volume_set(v)
        C.set_class(self.s_vol.icon, "off", False)
        self.s_vol.icon.set_text(I["mute"] if v < 1 else I["vol"])

    # ── notifications ──────────────────────────────────────────────────────
    def notif_widget(self, n):
        from notifications import ago, app_icon_for
        head = box("h", 6, None)
        gicon = app_icon_for(n)
        if gicon is not None:
            img = Gtk.Image.new_from_gicon(gicon)
            img.set_pixel_size(14)
            head.append(img)
        head.append(label((n.get("app_name") or "").upper(), "app", hexpand=True))
        head.append(label(ago(n.get("time") or 0), "app"))
        forget = C.button(icon(I["close"]), "nforget", lambda nid=n.get("id"): self.shell.notifs.forget(nid))
        head.append(forget)
        body = n.get("body") or ""
        w = card(head, label(n.get("summary") or "", "sum"),
                 label(body, "body", wrap=True) if body else None, cls="notif", spacing=2)
        if body:
            w.get_last_child().set_max_width_chars(40)
            w.get_last_child().set_lines(3)
            w.get_last_child().set_ellipsize(3)
        return w

    def refresh_notifs(self):
        items = self.shell.notifs.history
        C.clear(self.notif_list)
        for n in items[:3]:
            self.notif_list.append(self.notif_widget(n))
        if not items:
            self.notif_list.append(label(tr("Нет новых уведомлений"), "small muted", xalign=0.5))
        self.notif_more.set_visible(len(items) > 3)
        self.notif_items = items
        if "notifications" in self.pages and self.page == "notifications":
            self.pages["notifications"]["refresh"]()

    def clear_notifs(self):
        self.shell.notifs.clear_history()
        if self.page == "notifications":
            self.go_main()

    def on_notify_changed(self):
        if self.visible:
            dnd = S.dnd_get()
            C.set_class(self.m_dnd["circle"], "on", dnd)
            self.m_dnd["s"].set_text(tr("Включено") if dnd else tr("Выключено"))
            self.refresh_notifs()

    def build_notifications(self):
        outer, content = self.subpage(tr("Уведомления"), C.button(tr("Очистить"), "linkbtn", self.clear_notifs))
        timeout = segmented([("3", tr("3 с")), ("5", tr("5 с")), ("8", tr("8 с")), ("0", tr("Всегда"))], "5",
                            lambda v: C.set_setting("NOTIF_TIMEOUT", v))
        pos = segmented([("top-left", tr("Слева")), ("top-right", tr("Справа"))], "top-right",
                        lambda v: C.set_setting("NOTIF_POS", v))
        sound = make_switch(False, lambda on: C.set_setting("NOTIF_SOUND", int(on)))
        test = C.button(tr("Показать пример"), "ghostbtn", lambda: self.shell.notifs.demo())
        settings = card(opt(tr("Сколько показывать"), tr("Наведите мышь — уведомление подождёт"), None), timeout,
                        opt(tr("С какой стороны"), None, None), pos,
                        opt(tr("Звук"), tr("Тихий «дзынь» при новом уведомлении"), sound), test)
        history = box("v", 6)
        content.append(settings)
        content.append(history)

        def refresh():
            s = C.settings()
            timeout.setv(s["NOTIF_TIMEOUT"] if s["NOTIF_TIMEOUT"] in ("3", "5", "8", "0") else "5")
            pos.setv(s["NOTIF_POS"])
            sound.setv(s["NOTIF_SOUND"] == "1")
            C.clear(history)
            for n in getattr(self, "notif_items", [])[:50]:
                history.append(self.notif_widget(n))
            if not getattr(self, "notif_items", []):
                history.append(label(tr("Пока пусто"), "small muted", xalign=0.5))
        return {"widget": outer, "refresh": refresh}

    # ══ Wi-Fi ══════════════════════════════════════════════════════════════
    def build_wifi(self):
        sw = make_switch(False, lambda on: self.wifi.set_enabled(on))
        outer, content = self.subpage("Wi-Fi", sw)
        status = label("", "small muted", xalign=0.0)
        lst = box("v", 2)
        scan_btn = C.button(box("h", 6, None, icon(I["refresh"]), Gtk.Label(label=tr("Обновить"))), "ghostbtn",
                            lambda: (status.set_text(tr("Поиск сетей…")), self.wifi.scan()))
        tools = box("h", 8, None, status, Gtk.Box(hexpand=True), scan_btn)
        content.append(tools)
        content.append(card(lst, cls="flat", spacing=0))
        if C.has("nm-connection-editor"):
            content.append(C.button(tr("Параметры сети…"), "linkbtn",
                                    lambda: (self.hide(), C.spawn(["nm-connection-editor"]))))
        state = {"open": None}

        def connect(ssid, pw=None, row_status=None):
            if row_status:
                row_status.set_text(tr("Подключение…"))

            def done(ok, _out):
                status.set_text("" if ok else tr("Не удалось подключиться к {0}").format(ssid))
                state["open"] = None
                self.wifi.changed()
            self.wifi.connect(ssid, pw, done)

        def refresh(scan=True):
            w = self.wifi
            sw.setv(w.enabled)
            C.clear(lst)
            if not w.available:
                lst.append(label(tr("Wi-Fi адаптер не найден"), "empty", xalign=0.5))
                return
            if not w.enabled:
                lst.append(label(tr("Wi-Fi выключен"), "empty", xalign=0.5))
                return
            nets = w.networks()
            if scan:
                w.scan()
            if not nets:
                lst.append(label(tr("Сети не найдены"), "empty", xalign=0.5))
            for ssid, st, secure, active, saved in nets[:30]:
                glyph = I["wifi_s"][min(4, st // 20)]
                sub = tr("Подключено") if active else (tr("Сохранена") if saved else (tr("Защищена") if secure else tr("Открытая")))
                s_lbl = label(sub, "s")
                row = box("h", 10, "netrow" + (" active" if active else ""), icon(glyph),
                          box("v", 0, None, label(ssid, "t"), s_lbl, hexpand=True),
                          icon(I["lock"], "muted") if secure else None,
                          icon(I["check"]) if active else None)
                wrap = box("v", 0)
                pw_entry = Gtk.Entry(placeholder_text=tr("Пароль"), visibility=False, hexpand=True)
                pw_entry.add_css_class("field")
                go = C.button(tr("Подключить"), "accentbtn")
                rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=220)
                rev.set_child(box("h", 8, None, pw_entry, go, margin_start=8, margin_end=8, margin_bottom=8))
                go.connect("clicked", lambda *_a, s=ssid, e=pw_entry, l=s_lbl: connect(s, e.get_text(), l))
                pw_entry.connect("activate", lambda *_a, s=ssid, e=pw_entry, l=s_lbl: connect(s, e.get_text(), l))

                def click(s=ssid, a=active, sv=saved, sec=secure, r=rev, e=pw_entry, l=s_lbl):
                    if a:
                        l.set_text(tr("Отключение…"))
                        w.disconnect(lambda *_: w.changed())
                    elif sv or not sec:
                        connect(s, None, l)
                    else:
                        r.set_reveal_child(not r.get_reveal_child())
                        if r.get_reveal_child():
                            e.grab_focus()
                wrap.append(C.button(row, None, click))
                wrap.append(rev)
                lst.append(wrap)
            status.set_text("")
        return {"widget": outer, "refresh": refresh}

    # ══ Bluetooth ══════════════════════════════════════════════════════════
    def build_bt(self):
        sw = make_switch(False, lambda on: self.bt.set_power(on, lambda *_: (refresh(), self.refresh_bt_state())))
        outer, content = self.subpage("Bluetooth", sw)
        status = label("", "small muted")
        lst = box("v", 2)

        def scan():
            status.set_text(tr("Поиск устройств… (8 с)"))
            self.bt.scan(lambda *_: (status.set_text(""), refresh()))
        content.append(box("h", 8, None, status, Gtk.Box(hexpand=True),
                           C.button(box("h", 6, None, icon(I["refresh"]), Gtk.Label(label=tr("Искать"))), "ghostbtn", scan)))
        content.append(card(lst, cls="flat", spacing=0))
        if C.has("blueman-manager"):
            content.append(C.button(tr("Менеджер Bluetooth…"), "linkbtn",
                                    lambda: (self.hide(), C.spawn(["blueman-manager"]))))

        def refresh():
            def got(powered, devs):
                sw.setv(bool(powered))
                C.clear(lst)
                if powered is None:
                    lst.append(label(tr("Bluetooth-адаптер не найден"), "empty", xalign=0.5))
                    return
                if not powered:
                    lst.append(label(tr("Bluetooth выключен"), "empty", xalign=0.5))
                    return
                if not devs:
                    lst.append(label(tr("Нет устройств — нажмите «Искать»"), "empty", xalign=0.5))
                for mac, name, conn, paired in devs[:30]:
                    s = label(tr("Подключено") if conn else (tr("Сопряжено") if paired else tr("Новое")), "s")
                    row = box("h", 10, "netrow" + (" active" if conn else ""), icon(I["bt"]),
                              box("v", 0, None, label(name, "t"), s, hexpand=True),
                              icon(I["check"]) if conn else None)

                    def click(m=mac, c=conn, p=paired, l=s):
                        l.set_text(tr("Отключение…") if c else tr("Подключение…"))
                        self.bt.toggle_device(m, c, p, lambda *_: (refresh(), self.refresh_bt_state()))
                    lst.append(C.button(row, None, click))
            self.bt.state(got)
        return {"widget": outer, "refresh": refresh}

    # ══ Sound ══════════════════════════════════════════════════════════════
    def build_sound(self):
        outer, content = self.subpage(tr("Звук"))
        out_slider = Slider(I["vol"], self.set_volume)
        mic_slider = Slider(I["mic"], lambda v: S.volume_set(v, "@DEFAULT_AUDIO_SOURCE@"))
        outs, ins = box("v", 2), box("v", 2)
        mute_btn = C.button(tr("Выкл. звук"), "linkbtn", lambda: (S.mute_toggle(), GLib.timeout_add(120, lambda: refresh() or False)))
        mic_btn = C.button(tr("Выкл. микрофон"), "linkbtn",
                           lambda: (S.mute_toggle("@DEFAULT_AUDIO_SOURCE@"), GLib.timeout_add(120, lambda: refresh() or False)))
        content.append(card(box("h", 0, None, label(tr("Выход"), "card-title", hexpand=True), mute_btn),
                            out_slider.widget, outs))
        content.append(card(box("h", 0, None, label(tr("Вход"), "card-title", hexpand=True), mic_btn),
                            mic_slider.widget, ins))
        if C.has("pavucontrol"):
            content.append(C.button(tr("Микшер громкости…"), "linkbtn", lambda: (self.hide(), C.spawn(["pavucontrol"]))))

        def fill(container, kind, devs):
            C.clear(container)
            for name, desc, default in devs:
                glyph = I["headphones"] if any(k in name.lower() for k in ("headphone", "headset", "bluez")) \
                    else (I["mic"] if kind == "sources" else I["speaker"])
                row = box("h", 10, "netrow" + (" active" if default else ""), icon(glyph),
                          label(desc, "t", hexpand=True), icon(I["check"]) if default else None)
                container.append(C.button(row, None,
                                          lambda n=name: S.audio_set_default(kind, n, lambda *_: refresh())))

        def refresh():
            v = S.volume_get()
            if v:
                out_slider.setv(v[0])
                out_slider.icon.set_text(I["mute"] if v[1] else I["vol"])
                mute_btn.set_label(tr("Вкл. звук") if v[1] else tr("Выкл. звук"))
            m = S.volume_get("@DEFAULT_AUDIO_SOURCE@")
            if m:
                mic_slider.setv(m[0])
                mic_slider.icon.set_text(I["mic_off"] if m[1] else I["mic"])
                mic_btn.set_label(tr("Вкл. микрофон") if m[1] else tr("Выкл. микрофон"))
            S.audio_devices("sinks", lambda d: fill(outs, "sinks", d))
            S.audio_devices("sources", lambda d: fill(ins, "sources", d))
            self.refresh_volume()
        return {"widget": outer, "refresh": refresh}

    # ══ Appearance ═════════════════════════════════════════════════════════
    def build_appearance(self):
        from gallery import draw_swatch
        outer, content = self.subpage(tr("Оформление"))
        tgrid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=3,
                            max_children_per_line=3, column_spacing=6, row_spacing=6)
        self.theme_tiles = []
        for tid, name, colors in C.list_themes():
            da = Gtk.DrawingArea()
            da.set_size_request(100, 64)
            da.set_draw_func(draw_swatch, (colors, tid == "matugen"))
            tile = box("v", 0, "tile", da, label(name, "caption", xalign=0.5))
            b = C.button(tile, None, lambda t=tid: apply_theme(t))
            b.tid, b.tile, b.da = tid, tile, da
            tgrid.append(b)
            self.theme_tiles.append(b)
        content.append(card(label(tr("Тема"), "card-title"), tgrid))

        def apply_theme(tid):
            for t in self.theme_tiles:
                C.set_class(t.tile, "current", t.tid == tid)
            C.run_async([str(C.BIN / "nb-theme"), "apply", tid, "--quiet"],
                        lambda *_: self.set_values["appearance"].set_text(
                            {t[0]: t[1] for t in C.list_themes()}.get(tid, "")))

        wgrid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=3,
                            max_children_per_line=3, column_spacing=6, row_spacing=6)
        folder_lbl = label("", "small muted", hexpand=True)
        content.append(card(
            box("h", 6, None, label(tr("Обои"), "card-title", hexpand=True),
                C.button(box("h", 4, None, icon(I["shuffle"]), Gtk.Label(label=tr("Случайные"))), "linkbtn",
                         lambda: C.run_async([str(C.BIN / "nb-wall"), "random"], lambda *_: mark()))),
            wgrid,
            box("h", 6, None, folder_lbl,
                C.button(tr("Сменить папку…"), "linkbtn", lambda: self.file_dialog(
                    tr("Папка с обоями"), lambda p: C.set_setting("WALL_DIR", p[0]), folder=True)),
                C.button(tr("Все обои…"), "linkbtn", lambda: self.push("walls")))))
        state = {"dir": None, "tiles": []}

        def mark():
            cur = gallery.current_wall()
            for t in state["tiles"]:
                C.set_class(t.tile, "current", t.path == cur)

        def refresh():
            cur_t = C.current_theme_id()
            for t in self.theme_tiles:
                C.set_class(t.tile, "current", t.tid == cur_t)
            d = C.settings().get("WALL_DIR")
            folder_lbl.set_text(d.replace(str(C.HOME), "~"))
            if d != state["dir"]:
                state["dir"] = d
                C.clear(wgrid)
                state["tiles"] = []
                files = gallery.list_walls(d) if os.path.isdir(d) else []
                cur = gallery.current_wall()
                # the current wallpaper first, then the rest — up to 24
                files = ([cur] if cur in files else []) + [f for f in files if f != cur]
                for f in files[:24]:
                    pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
                    pic.set_size_request(102, 64)
                    pic.add_css_class("thumb")
                    pic.set_overflow(Gtk.Overflow.HIDDEN)
                    tile = box("v", 0, "tile", pic)
                    b = C.button(tile, None, lambda p=f: C.run_async([str(C.BIN / "nb-wall"), "set", p],
                                                                    lambda *_: mark()))
                    b.path, b.tile, b.pic = f, tile, pic
                    b.set_tooltip_text(os.path.basename(f))
                    wgrid.append(b)
                    state["tiles"].append(b)
                scale = max(1, self.win.get_scale_factor())
                gallery.load_textures([(t, gallery.thumb_path(t.path)) for t in state["tiles"]
                                       if gallery.thumb_path(t.path).exists()], 102 * scale, 64 * scale,
                                      lambda batch: [t.pic.set_paintable(tex) for t, tex in batch])
            mark()
        return {"widget": outer, "refresh": refresh}

    # ══ Wallpaper ══════════════════════════════════════════════════════════
    def build_walls(self):
        shuffle = C.button(icon(I["shuffle"]), "linkbtn", lambda: C.run_async(
            [str(C.BIN / "nb-wall"), "random"], lambda *_: mark()), tr("Случайные обои"))
        outer, content = self.subpage(tr("Обои"), shuffle)
        entry = Gtk.SearchEntry(placeholder_text=tr("Поиск по имени или путь к папке"), hexpand=True)
        entry.add_css_class("pagesearch")
        msg = label("", "small muted", xalign=0.5, wrap=True)
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=3,
                           max_children_per_line=3, column_spacing=6, row_spacing=6)
        folder_lbl = label("", "small muted", hexpand=True)
        content.append(entry)
        content.append(msg)
        content.append(grid)
        content.append(box("h", 6, None, folder_lbl,
                           C.button(tr("Сменить папку…"), "linkbtn", lambda: self.file_dialog(
                               tr("Папка с обоями"), lambda p: change_dir(p[0]), folder=True))))
        content.append(label(tr("Enter — поставить первые найденные; вставьте путь к папке и нажмите Enter — "
                             "сменить папку. Super+Shift+W — случайные."), "tiny muted", wrap=True))
        TW, TH = 98, 62
        state = {"dir": None, "tiles": [], "loaded": False, "gen": 0, "unload": None}

        def mark():
            cur = gallery.current_wall()
            for t in state["tiles"]:
                C.set_class(t.tile, "current", t.path == cur)

        def set_wall(path):
            for t in state["tiles"]:
                C.set_class(t.tile, "current", t.path == path)
            C.run_async([str(C.BIN / "nb-wall"), "set", path], lambda *_: mark())

        def change_dir(d):
            C.set_setting("WALL_DIR", d, lambda *_: (entry.set_text(""), refresh()))

        def load(tiles):
            gen = state["gen"]
            scale = max(1, self.win.get_scale_factor())

            def apply(batch):
                if gen == state["gen"]:
                    for t, tex in batch:
                        t.pic.set_paintable(tex)
            gallery.load_textures([(t, gallery.thumb_path(t.path)) for t in tiles], TW * scale, TH * scale, apply,
                                  alive=lambda: gen == state["gen"])

        def build(d):
            state["gen"] += 1
            grid.remove_all()
            state["tiles"] = []
            files = gallery.list_walls(d) if d and os.path.isdir(d) else []
            dh = d.replace(str(C.HOME), "~") if d else "—"
            folder_lbl.set_text(dh)
            if not files:
                msg.set_text(tr("В {0} нет картинок. Вставьте в поиск путь к другой папке и нажмите Enter").format(dh))
                msg.set_visible(True)
                return
            msg.set_visible(False)
            cur = gallery.current_wall()
            missing = []
            for f in files:
                pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
                pic.set_size_request(TW, TH)
                pic.add_css_class("thumb")
                pic.set_overflow(Gtk.Overflow.HIDDEN)
                tile = box("v", 0, "tile" + (" current" if f == cur else ""), pic)
                b = C.button(tile, None, lambda p=f: set_wall(p), os.path.basename(f))
                b.path, b.tile, b.pic = f, tile, pic
                b.name = os.path.splitext(os.path.basename(f))[0].casefold()
                grid.append(b)
                state["tiles"].append(b)
                if not gallery.thumb_path(f).exists():
                    missing.append(b)
            load([t for t in state["tiles"] if t not in missing])
            state["loaded"] = True
            if missing:
                msg.set_text(tr("Готовлю превью для {0} обоев…").format(len(missing)))
                msg.set_visible(True)
                C.run_async([str(C.BIN / "nb-thumbs")], lambda *_: (msg.set_visible(False), load(missing)))

        def filter_(*_):
            q = entry.get_text().strip().casefold()
            if q[:1] in ("/", "~", "$") or q.startswith("file://"):
                return
            for t in state["tiles"]:
                t.get_parent().set_visible(not q or q in t.name)

        def activate(*_):
            q = entry.get_text().strip()
            d = gallery.parse_dir(q) if q[:1] in ("/", "~", "$") or q.startswith("file://") else None
            if d:
                change_dir(d)
                return
            first = next((t for t in state["tiles"] if t.get_parent().get_visible()), None)
            if first:
                set_wall(first.path)
        entry.connect("search-changed", filter_)
        entry.connect("activate", activate)

        def refresh():
            if state["unload"]:
                GLib.source_remove(state["unload"])
                state["unload"] = None
            d = C.settings().get("WALL_DIR")
            if d != state["dir"]:
                state["dir"] = d
                build(d)
            elif not state["loaded"]:
                load(state["tiles"])
                state["loaded"] = True
            mark()
            entry.set_text("")
            GLib.idle_add(lambda: entry.grab_focus() and False)

        def leave():
            # don't keep previews in memory while the page is closed (let them go after a minute)
            def unload():
                state["unload"] = None
                state["gen"] += 1
                state["loaded"] = False
                for t in state["tiles"]:
                    t.pic.set_paintable(None)
                return False
            if state["unload"]:
                GLib.source_remove(state["unload"])
            state["unload"] = GLib.timeout_add_seconds(60, unload)
        return {"widget": outer, "refresh": refresh, "leave": leave}

    # ══ Clipboard ══════════════════════════════════════════════════════════
    def build_clip(self):
        outer, content = self.subpage(tr("Буфер обмена"), C.button(tr("Очистить"), "linkbtn", lambda: wipe()))
        entry = Gtk.SearchEntry(placeholder_text=tr("Поиск в истории"), hexpand=True)
        entry.add_css_class("pagesearch")
        lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, activate_on_single_click=True)
        lst.add_css_class("cliplist")
        empty = label("", "small muted", xalign=0.5)
        content.append(entry)
        content.append(empty)
        content.append(lst)
        content.append(label(tr("Клик — скопировать снова, Enter — первое найденное. Хранится в cliphist."),
                             "tiny muted", wrap=True))
        rows = []

        def copy(line):
            import subprocess
            try:
                data = subprocess.run(["cliphist", "decode"], input=line.encode(), capture_output=True,
                                      timeout=3).stdout
                p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, start_new_session=True)
                p.communicate(data)
            except Exception:
                pass
            self.hide()

        def delete(row):
            C.run_async(["cliphist", "delete"], None, stdin=row.line)
            lst.remove(row)
            rows.remove(row)
            if not rows:
                empty.set_text(tr("История пуста"))
                empty.set_visible(True)

        def wipe():
            C.run_async(["cliphist", "wipe"], lambda *_: refresh())

        def thumb(row):
            import threading

            def work():
                import subprocess
                from gi.repository import GdkPixbuf
                try:
                    data = subprocess.run(["cliphist", "decode"], input=row.line.encode(), capture_output=True,
                                          timeout=3).stdout
                    loader = GdkPixbuf.PixbufLoader()
                    loader.write(data)
                    loader.close()
                    pb = loader.get_pixbuf()
                    sc = 80 / max(pb.get_width(), pb.get_height())
                    pb = pb.scale_simple(max(1, int(pb.get_width() * sc)), max(1, int(pb.get_height() * sc)),
                                         GdkPixbuf.InterpType.BILINEAR)
                    tex = Gdk.Texture.new_for_pixbuf(pb)
                except Exception:
                    return
                GLib.idle_add(lambda: (row.lead.set_paintable(tex), row.leadstack.set_visible_child_name("pic"))
                              and False)
            threading.Thread(target=work, daemon=True).start()

        def make_row(line):
            text = line.split("\t", 1)[1] if "\t" in line else line
            img = text.startswith("[[ binary data")
            title = tr("Картинка · ") + text[len("[[ binary data"):].rstrip("] ").strip() if img \
                else " ".join(text.split())[:300]
            row = Gtk.ListBoxRow()
            row.add_css_class("cliprow")
            row.line, row.search = line, text.casefold()
            pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
            pic.set_size_request(40, 30)
            pic.add_css_class("thumb")
            pic.set_overflow(Gtk.Overflow.HIDDEN)
            st = Gtk.Stack()
            st.add_named(icon(I["image"] if img else I["clip"], "glyph"), "glyph")
            st.add_named(pic, "pic")
            row.lead, row.leadstack = pic, st
            t = label(title, "t", hexpand=True)
            t.set_wrap(True)
            t.set_wrap_mode(2)       # WORD_CHAR: long paths and links wrap too
            t.set_lines(2)
            t.set_ellipsize(3)
            t.set_max_width_chars(34)
            rm = C.button(icon(I["delete"]), "pinbtn danger", lambda r=row: delete(r), tr("Удалить"))
            rm.set_valign(Gtk.Align.CENTER)
            row.set_child(box("h", 8, None, st, t, rm))
            row.img = img
            return row

        lst.connect("row-activated", lambda _l, r: copy(r.line))

        def filter_(*_):
            q = entry.get_text().strip().casefold()
            for r in rows:
                r.set_visible(not q or q in r.search)

        def activate(*_):
            first = next((r for r in rows if r.get_visible()), None)
            if first:
                copy(first.line)
        entry.connect("search-changed", filter_)
        entry.connect("activate", activate)

        def refresh():
            lst.remove_all()
            rows.clear()
            entry.set_text("")
            GLib.idle_add(lambda: entry.grab_focus() and False)
            if not C.has("cliphist"):
                empty.set_text(tr("cliphist не установлен"))
                empty.set_visible(True)
                return

            def done(_ok, out):
                lines = [ln for ln in out.splitlines() if ln.strip()][:200]
                empty.set_text(tr("История пуста"))
                empty.set_visible(not lines)
                imgs = 0
                for ln in lines:
                    r = make_row(ln)
                    lst.append(r)
                    rows.append(r)
                    if r.img and imgs < 16:
                        imgs += 1
                        thumb(r)
            C.run_async(["cliphist", "list"], done)

        def leave():
            lst.remove_all()   # clipboard images don't stay in memory
            rows.clear()
        return {"widget": outer, "refresh": refresh, "leave": leave}

    # ══ Power ══════════════════════════════════════════════════════════════
    def build_power(self):
        outer, content = self.subpage(tr("Питание"))
        who = label("", "small muted", xalign=0.5, wrap=True)
        grid = Gtk.Grid(column_spacing=6, row_spacing=6, column_homogeneous=True)
        acts = (("lock", I["lock"], tr("Блокировка"), ""), ("suspend", I["sleep"], tr("Сон"), ""),
                ("logout", I["logout"], tr("Выйти"), ""), ("reboot", I["reboot"], tr("Перезагрузка"), "danger"),
                ("shutdown", I["power"], tr("Выключение"), "danger"))
        for i, (act, glyph, name, cls) in enumerate(acts):
            circ = icon(glyph, "circle")
            circ.set_halign(Gtk.Align.CENTER)
            tile = box("v", 0, f"tile powerbtn {cls}".strip(), circ, label(name, "caption", xalign=0.5))
            b = C.button(tile, None, lambda a=act: self.hide(then=lambda: C.spawn([str(C.BIN / "nb-power"), a])))
            grid.attach(b, i % 3, i // 3, 1, 1)
        content.append(card(grid))
        content.append(who)
        content.append(label(tr("Super+Esc — эта страница · Super+Shift+L — заблокировать сразу"), "tiny muted",
                             xalign=0.5, wrap=True))

        def refresh():
            real, login = C.user_name()
            host = Path("/proc/sys/kernel/hostname").read_text().strip()
            who.set_text(f"{real} · {login}@{host} · {C.uptime_text()}")
        return {"widget": outer, "refresh": refresh}

    # ══ Fastfetch ══════════════════════════════════════════════════════════
    def build_fetch(self):
        outer, content = self.subpage("Fastfetch")
        preview = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        preview.set_size_request(120, 120)
        preview.add_css_class("thumb")
        preview.set_overflow(Gtk.Overflow.HIDDEN)
        preview.set_halign(Gtk.Align.CENTER)
        cur_name = label("", "small dim", xalign=0.5)
        st = C.settings()
        mode = make_switch(st["FETCH_MODE"] == "random",
                           lambda on: C.set_setting("FETCH_MODE", "random" if on else "fixed",
                                                    lambda *_: self.set_values["fetch"].set_text(
                                                        tr("Случайная") if on else tr("Выбранная"))))
        size = Slider(None, lambda v: C.set_setting("FETCH_SIZE", int(v), lambda *_: render()), 8, 30, delay=300,
                      thin=True, fmt=lambda v: tr("{0} стр.").format(int(v)))
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=4,
                           max_children_per_line=4, column_spacing=6, row_spacing=6)
        empty = label("", "small muted", xalign=0.5, wrap=True)
        content.append(card(preview, cur_name))
        content.append(card(
            box("h", 6, None, label(tr("Картинки"), "card-title", hexpand=True),
                C.button(box("h", 4, None, icon(I["shuffle"]), Gtk.Label(label=tr("Следующая"))), "linkbtn",
                         lambda: C.run_async([str(C.BIN / "nb-fetch"), "next"], lambda *_: refresh()))),
            grid, empty,
            box("h", 8, None,
                C.button(box("h", 6, None, icon(I["plus"]), Gtk.Label(label=tr("Добавить…"))), "accentbtn",
                         lambda: self.file_dialog(tr("Картинки для fastfetch"), add, multiple=True)),
                C.button(box("h", 6, None, icon(I["folder"]), Gtk.Label(label=tr("Папка"))), "ghostbtn",
                         lambda: (self.hide(), C.spawn(["xdg-open", C.settings()["FETCH_DIR"]]))))))
        content.append(card(opt(tr("Случайная в каждом терминале"), tr("Иначе — всегда выбранная"), mode),
                            opt(tr("Размер картинки"), None, None), size.widget))
        content.append(label(tr("Совет: в Dolphin — ПКМ по картинке → «Nebula» → «Картинка для fastfetch». "
                             "Или просто кладите файлы в папку. Super+Shift+A — следующая."),
                             "tiny muted", wrap=True))

        def add(paths):
            C.run_async([str(C.BIN / "nb-fetch"), "add", *paths], lambda *_: refresh())

        def render():
            C.run_async([str(C.BIN / "nb-fetch"), "apply"])

        def refresh():
            s = C.settings()
            mode.setv(s["FETCH_MODE"] == "random")
            size.setv(int(s.get("FETCH_SIZE") or 16))
            d = Path(s["FETCH_DIR"])
            try:
                cur = (C.STATE / "fetch-image").read_text().strip()
            except OSError:
                cur = ""
            prev = C.CACHE / "fetch" / "logo.png"
            tex = C.texture_scaled(prev, 240, 240) if prev.exists() else None
            preview.set_paintable(tex)
            preview.set_visible(tex is not None)
            cur_name.set_text(os.path.basename(cur) if cur else tr("Картинка не выбрана"))
            C.clear(grid)
            files = []
            if d.is_dir():
                files = sorted([p for p in d.iterdir() if p.suffix.lower() in
                                {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}], key=lambda p: p.name.casefold())
            empty.set_text("" if files else tr("В {0} пока пусто — добавьте картинки").format(str(d).replace(str(C.HOME), '~')))
            empty.set_visible(not files)
            jobs = []
            for f in files[:60]:
                pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
                pic.set_size_request(72, 72)
                pic.add_css_class("thumb")
                pic.set_overflow(Gtk.Overflow.HIDDEN)
                tile = box("v", 0, "tile" + (" current" if str(f) == cur else ""), pic)
                b = C.button(tile, None, lambda p=str(f): C.run_async([str(C.BIN / "nb-fetch"), "set", p],
                                                                     lambda *_: refresh()))
                b.set_tooltip_text(f.name)
                grid.append(b)
                jobs.append((pic, f))
            # pictures load in the background, so big files can't freeze the Control Center
            gallery.load_textures(jobs, 144, 144, lambda batch: [p.set_paintable(t) for p, t in batch])
        return {"widget": outer, "refresh": refresh}

    # ══ Display ════════════════════════════════════════════════════════════
    def build_display(self):
        outer, content = self.subpage(tr("Экран"))
        outs_box = box("v", 12)
        content.append(outs_box)
        st = C.settings()
        night_sw = make_switch(False, lambda on: (S.night_set(on, int(C.settings().get("NIGHT_TEMP", "4000") or 4000)),
                                                  GLib.timeout_add(300, lambda: self.refresh_main() or False)))

        def set_temp(v):
            C.set_setting("NIGHT_TEMP", int(v))
            if S.night_get():
                S.night_set(True, int(v))
        temp = Slider(None, set_temp, 2500, 6000, delay=400, thin=True, fmt=lambda v: f"{int(v)} K")
        content.append(card(label(tr("Ночной свет"), "card-title"),
                            opt(tr("Тёплые цвета экрана"), tr("Меньше синего света вечером"), night_sw),
                            opt(tr("Температура"), None, None), temp.widget))

        def refresh():
            C.clear(outs_box)
            for o in S.outputs():
                cur = round(o["scale"] * 100)
                presets = [100, 125, 150, 175, 200]
                seg = segmented([(p, f"{p}%") for p in presets], cur if cur in presets else None,
                                lambda v, n=o["name"]: apply_scale(n, v))
                fine = Slider(None, lambda v, n=o["name"]: apply_scale(n, round(v / 5) * 5), 50, 300, delay=600,
                              thin=True, fmt=lambda v: f"{round(v / 5) * 5}%")
                fine.setv(cur)
                fine.scale.set_increments(5, 25)
                info = tr("{0} · {1}×{2} · {3} Гц").format(o['model'] or o['name'], o['width'], o['height'], o['refresh'])
                outs_box.append(card(label(tr("Масштаб интерфейса"), "card-title"), label(info, "small muted"),
                                     seg, opt(tr("Точнее"), None, None), fine.widget,
                                     label(tr("Применяется сразу и запоминается в conf.d/outputs.kdl"), "tiny muted",
                                           wrap=True)))
            night_sw.setv(S.night_get())
            temp.setv(int(C.settings().get("NIGHT_TEMP", "4000") or 4000))

        def apply_scale(name, pct):
            S.set_scale(name, pct / 100)
            GLib.timeout_add(700, lambda: (refresh(), self.refresh_main()) and False)
        return {"widget": outer, "refresh": refresh}

    # ══ Date, time and language ════════════════════════════════════════════
    def build_time(self):
        outer, content = self.subpage(tr("Дата и время"))
        clock = label("", "bigclock", xalign=0.5)
        date = label("", "dim", xalign=0.5)
        content.append(card(clock, date))
        # Language names are written in themselves, so they're findable whatever is on screen now
        lang = segmented([("en", "English"), ("ru", "Русский")], C.LANG,
                         lambda v: C.set_setting("UI_LANG", v) if v != C.LANG else None)
        content.append(card(label(tr("Язык интерфейса"), "card-title"), lang,
                            label(tr("Оболочка и строка меню перезапустятся на новом языке"), "tiny muted", wrap=True)))
        st = C.settings()
        sw24 = make_switch(st["CLOCK_24H"] == "1", lambda on: C.set_setting("CLOCK_24H", int(on)))
        swsec = make_switch(st["CLOCK_SECONDS"] == "1", lambda on: C.set_setting("CLOCK_SECONDS", int(on)))
        swdate = make_switch(st["CLOCK_DATE"] == "1", lambda on: C.set_setting("CLOCK_DATE", int(on)))
        content.append(card(label(tr("Часы в строке меню"), "card-title"),
                            opt(tr("24-часовой формат"), None, sw24),
                            opt(tr("Показывать секунды"), None, swsec),
                            opt(tr("День недели и дата"), None, swdate)))
        ntp = make_switch(False, lambda on: C.run_async(["timedatectl", "set-ntp", "true" if on else "false"],
                                                        lambda *_: refresh()))
        tz_list = S.timezones()
        dd = Gtk.DropDown.new_from_strings(tz_list or ["UTC"])
        dd.set_enable_search(True)
        dd.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        dd.set_hexpand(True)
        guard = {"on": False}

        def tz_changed(d, _p):
            if guard["on"]:
                return
            item = d.get_selected_item()
            if item:
                status.set_text(tr("Меняю часовой пояс… (может спросить пароль)"))
                C.run_async(["timedatectl", "set-timezone", item.get_string()],
                            lambda ok, _o: (status.set_text("" if ok else tr("Не получилось — нужен пароль администратора")),
                                            refresh()))
        dd.connect("notify::selected", tz_changed)
        status = label("", "tiny muted", wrap=True)
        content.append(card(label(tr("Время системы"), "card-title"),
                            opt(tr("Синхронизировать по сети"), tr("Точное время с серверов NTP"), ntp),
                            label(tr("Часовой пояс"), "small dim"), dd, status))

        def tick():
            now = time.localtime()
            fmt = "%H:%M:%S" if C.settings()["CLOCK_24H"] == "1" else "%I:%M:%S %p"
            clock.set_text(time.strftime(fmt, now))
            date.set_text(C.date_text(now, year=True))
            return True

        def refresh():
            s = C.settings()
            sw24.setv(s["CLOCK_24H"] == "1")
            swsec.setv(s["CLOCK_SECONDS"] == "1")
            swdate.setv(s["CLOCK_DATE"] == "1")
            tz, on, can = S.time_info()
            ntp.setv(on)
            ntp.set_sensitive(can)
            guard["on"] = True
            if tz in tz_list:
                dd.set_selected(tz_list.index(tz))
            guard["on"] = False
            tick()
            self.stop_clock()
            self.clock_timer = GLib.timeout_add(1000, tick)
        return {"widget": outer, "refresh": refresh}

    def stop_clock(self):
        if self.clock_timer:
            GLib.source_remove(self.clock_timer)
            self.clock_timer = None

    # ══ Menu bar ═══════════════════════════════════════════════════════════
    def build_bar(self):
        outer, content = self.subpage(tr("Строка меню"))
        st = C.settings()
        state = {"style": C.bar_style()}

        # style: cards with previews
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        previews = {}
        for i, (sid, title, sub) in enumerate(BAR_STYLES):
            da = Gtk.DrawingArea(content_height=74, hexpand=True)
            da.set_draw_func(lambda _d, cr, w, h, sid=sid: draw_bar_preview(
                cr, w, h, sid, self.shell.colors, state["style"] == sid))
            previews[sid] = da
            b = C.button(box("v", 5, None, da, label(title, "t", xalign=0.5), label(sub, "s muted", xalign=0.5)),
                         "stylecard", lambda sid=sid: pick(sid))
            # an odd number of styles: the last one spans the full width
            last_alone = i == len(BAR_STYLES) - 1 and i % 2 == 0
            grid.attach(b, i % 2, i // 2, 2 if last_alone else 1, 1)

        def pick(sid):
            state["style"] = sid
            for d in previews.values():
                d.queue_draw()
            frame_row.set_visible(sid == "frame")
            C.set_setting("BAR_STYLE", sid, lambda *_: self.refresh_main())
        content.append(card(label(tr("Стиль"), "card-title"), grid))

        height = Slider(None, lambda v: C.set_setting("BAR_HEIGHT", int(v)), 28, 44, delay=400, thin=True,
                        fmt=lambda v: f"{int(v)} px")
        fsize = Slider(None, lambda v: C.set_setting("FRAME_SIZE", int(v)), 4, 16, delay=350, thin=True,
                       fmt=lambda v: f"{int(v)} px")
        frame_row = box("v", 0, None, opt(tr("Толщина рамки"), tr("Окна не заходят под рамку; Super+F — поверх неё")),
                        fsize.widget)
        frame_row.set_visible(state["style"] == "frame")
        content.append(card(label(tr("Размеры"), "card-title"), opt(tr("Высота"), None), height.widget, frame_row))

        # modules: drag between zones (or click a module for a menu)
        zones = {}
        editor = box("v", 8, None)
        for zid, ztitle in BAR_ZONES:
            fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False,
                             max_children_per_line=8, min_children_per_line=1,
                             column_spacing=5, row_spacing=5, activate_on_single_click=False)
            fb.add_css_class("modzone")
            if zid == "hidden":
                fb.add_css_class("hidden")
            drop = Gtk.DropTargetAsync.new(Gdk.ContentFormats.new([BAR_MIME]), Gdk.DragAction.MOVE)
            drop.connect("accept", lambda _t, _d: self.bar_drag is not None)
            drop.connect("drag-enter", lambda _t, _d, _x, _y, fb=fb: (fb.add_css_class("drop"), Gdk.DragAction.MOVE)[1])
            drop.connect("drag-motion", lambda *_: Gdk.DragAction.MOVE)
            drop.connect("drag-leave", lambda _t, _d, fb=fb: fb.remove_css_class("drop"))
            drop.connect("drop", lambda _t, d, x, y, zid=zid, fb=fb: self.bar_drop(d, zid, fb, x, y))
            fb.add_controller(drop)
            zones[zid] = fb
            editor.append(label(ztitle, "zonetitle"))
            editor.append(fb)
        self.bar_zones = zones
        self.bar_drag = None
        reset = C.button(tr("По умолчанию"), "linkbtn", lambda: self.bar_save(
            C.DEFAULTS["BAR_LEFT"].split(), C.DEFAULTS["BAR_CENTER"].split(), C.DEFAULTS["BAR_RIGHT"].split()))
        content.append(card(box("h", 0, None, label(tr("Модули"), "card-title", hexpand=True), reset), editor,
                            label(tr("Перетаскивай модули между зонами или нажми на модуль — "
                                  "появится меню. Изменения сразу видны в строке меню."), "tiny muted", wrap=True)))

        # the player in the center
        cover = make_switch(st["BAR_MEDIA_COVER"] == "1", lambda on: C.set_setting("BAR_MEDIA_COVER", int(on)))
        mlen = Slider(None, lambda v: C.set_setting("BAR_MEDIA_LEN", int(v)), 16, 80, delay=400, thin=True,
                      fmt=lambda v: tr("{0} симв.").format(int(v)))
        content.append(card(label(tr("Плеер"), "card-title"),
                            opt(tr("Обложка в строке меню"), None, cover),
                            opt(tr("Длина названия"), None), mlen.widget,
                            label(tr("Клик по музыке в строке меню — большой плеер: обложка, фон из её цветов, "
                                  "перемотка, громкость плеера."), "tiny muted", wrap=True)))

        def refresh():
            s = C.settings()
            state["style"] = C.bar_style()
            for d in previews.values():
                d.queue_draw()
            frame_row.set_visible(state["style"] == "frame")
            height.setv(int(s["BAR_HEIGHT"] or 34))
            fsize.setv(int(s["FRAME_SIZE"] or 8))
            mlen.setv(int(s["BAR_MEDIA_LEN"] or 40))
            cover.setv(s["BAR_MEDIA_COVER"] == "1")
            self.bar_layout = {z: s[f"BAR_{z.upper()}"].split() for z in ("left", "center", "right")}
            self.bar_fill()
        return {"widget": outer, "refresh": refresh}

    def bar_fill(self):
        used = {m for z in self.bar_layout.values() for m in z}
        lay = dict(self.bar_layout)
        lay["hidden"] = [m for m, _t, _g in BAR_MODS if m not in used]
        names = {m: (t, g) for m, t, g in BAR_MODS}
        for zid, fb in self.bar_zones.items():
            fb.remove_all()
            mods = [m for m in lay[zid] if m in names]
            for m in mods:
                fb.append(self.bar_chip(m, zid, *names[m]))
            if not mods:
                ph = label(tr("пусто — перетащи сюда") if zid != "hidden" else tr("все модули на месте"), "tiny muted")
                ph.zone_placeholder = True
                fb.append(ph)

    def bar_chip(self, mod, zid, title, glyph):
        b = C.button(box("h", 6, None, icon(glyph, "modglyph"), Gtk.Label(label=title)), "modchip")
        b.connect("clicked", lambda *_: self.bar_menu(b, mod, zid))
        src = Gtk.DragSource(actions=Gdk.DragAction.MOVE)

        def prepare(*_):
            self.bar_drag = mod
            return Gdk.ContentProvider.new_for_bytes(BAR_MIME, GLib.Bytes.new(mod.encode()))

        def begin(s, _d):
            s.set_icon(Gtk.WidgetPaintable.new(b), 20, 14)
            b.add_css_class("dragging")

        def end(*_):
            self.bar_drag = None
            b.remove_css_class("dragging")
            for fb in self.bar_zones.values():
                fb.remove_css_class("drop")
        src.connect("prepare", prepare)
        src.connect("drag-begin", begin)
        src.connect("drag-end", end)
        b.add_controller(src)
        return b

    def bar_drop(self, drop, zid, fb, x, y):
        mod = self.bar_drag
        fb.remove_css_class("drop")
        if not mod:
            drop.finish(0)
            return False
        idx = None
        child = fb.get_child_at_pos(x, y)
        if child is not None and not getattr(child.get_child(), "zone_placeholder", False):
            idx = child.get_index()
            ok, r = child.compute_bounds(fb)
            if ok and x > r.get_x() + r.get_width() / 2:
                idx += 1
        self.bar_move(mod, zid, idx)
        drop.finish(Gdk.DragAction.MOVE)
        return True

    def bar_move(self, mod, zid, idx=None):
        """Move a module into zone zid at position idx (None — at the end)."""
        lay = {z: [m for m in ms if m != mod] for z, ms in self.bar_layout.items()}
        if zid != "hidden":
            old = self.bar_layout.get(zid, [])
            if idx is not None and mod in old and old.index(mod) < idx:
                idx -= 1   # the module itself was further left — positions shifted after removing it
            lst = lay[zid]
            lst.insert(len(lst) if idx is None else max(0, min(idx, len(lst))), mod)
        self.bar_save(lay["left"], lay["center"], lay["right"])

    def bar_save(self, left, center, right):
        self.bar_layout = {"left": list(left), "center": list(center), "right": list(right)}
        self.bar_fill()
        C.run_async([str(C.BIN / "nb-settings"), "bar-layout", " ".join(left), " ".join(center), " ".join(right)])

    def bar_menu(self, anchor, mod, zid):
        items = box("v", 0, "dockmenu")
        pop = Gtk.Popover(has_arrow=False, position=Gtk.PositionType.BOTTOM)
        pop.add_css_class("dockpop")

        def add(text, fn):
            b = Gtk.Button(child=label(text), css_classes=["menuitem"], can_focus=False)
            b.connect("clicked", lambda *_: (pop.popdown(), fn()))
            items.append(b)
        if zid != "hidden":
            lst = self.bar_layout[zid]
            i = lst.index(mod)
            if i > 0:
                add(tr("← Левее"), lambda: self.bar_move(mod, zid, i - 1))
            if i < len(lst) - 1:
                add(tr("Правее →"), lambda: self.bar_move(mod, zid, i + 2))
        for z, t in BAR_ZONES[:3]:
            if z != zid:
                add((tr("Перенести: ") if zid != "hidden" else tr("Добавить: ")) + t.lower(), lambda z=z: self.bar_move(mod, z))
        if zid != "hidden":
            add(tr("Убрать из строки меню"), lambda: self.bar_move(mod, "hidden"))
        pop.set_child(items)
        pop.set_parent(anchor)
        pop.connect("closed", lambda p: GLib.idle_add(lambda: p.unparent() or False))
        pop.popup()

    # ══ Desktop ════════════════════════════════════════════════════════════
    def build_desktop(self):
        outer, content = self.subpage(tr("Рабочий стол"))
        st = C.settings()
        dock = segmented([("off", tr("Выкл")), ("autohide", tr("Прятать")), ("always", tr("Всегда"))], st["DOCK"],
                         lambda v: C.set_setting("DOCK", v, lambda *_: self.refresh_main()))
        content.append(card(label(tr("Док"), "card-title"), dock,
                            label(tr("«Прятать» — выезжает, когда подводишь мышь к низу экрана или стол пустой."),
                                  "tiny muted", wrap=True)))
        pins = box("v", 0, "pinlist")
        reset = C.button(tr("Сбросить"), "linkbtn", lambda: self.shell.dock.reset_pins(),
                         tr("Самые запускаемые приложения"))
        content.append(card(box("h", 0, None, label(tr("Закреплённые в доке"), "card-title", hexpand=True), reset),
                            pins,
                            label(tr("Перетащи значок в доке, чтобы поменять порядок, или вытащи вверх — "
                                  "открепится. ПКМ по значку — меню, в поиске — Ctrl+D."),
                                  "tiny muted", wrap=True)))

        def fill_pins():
            C.clear(pins)
            d = self.shell.dock
            by_id = {a.id: a for a in self.shell.apps.apps}
            ids = [p for p in d.pins if p in by_id]
            if not ids:
                pins.append(label(tr("Пока пусто"), "s muted"))
            for i, pid in enumerate(ids):
                a = by_id[pid]
                img = Gtk.Image(pixel_size=24)
                if a.gicon is not None:
                    img.set_from_gicon(a.gicon)
                else:
                    img.set_from_icon_name("application-x-executable")
                up = C.button(icon(I["up"]), "pinbtn", lambda p=pid: d.move_pin(p, -1), tr("Левее"))
                down = C.button(icon(I["down"]), "pinbtn", lambda p=pid: d.move_pin(p, 1), tr("Правее"))
                rm = C.button(icon(I["close"]), "pinbtn danger", lambda p=pid: d.unpin(p), tr("Убрать из дока"))
                up.set_sensitive(i > 0)
                down.set_sensitive(i < len(ids) - 1)
                pins.append(box("h", 10, "pinrow", img, label(a.name, "t", hexpand=True), up, down, rm))
        fill_pins()
        self.shell.dock.pin_listeners.append(fill_pins)
        # desktop clock: position, size, font, weight, color
        def setk(key, v):
            C.set_setting(key, v)
        clock = make_switch(st["DESKTOP_CLOCK"] == "1", lambda on: (setk("DESKTOP_CLOCK", int(on)),
                                                                    clock_opts.set_reveal_child(on)))
        posgrid = Gtk.Grid(column_spacing=4, row_spacing=4, column_homogeneous=True, row_homogeneous=True)
        posgrid.add_css_class("posgrid")
        pos_btns = {}
        from frame import POSITIONS, WEIGHTS
        names = {"top-left": tr("Сверху слева"), "top": tr("Сверху"), "top-right": tr("Сверху справа"), "left": tr("Слева"),
                 "center": tr("По центру"), "right": tr("Справа"), "bottom-left": tr("Снизу слева"), "bottom": tr("Снизу"),
                 "bottom-right": tr("Снизу справа")}
        for i, pid in enumerate(POSITIONS):
            dot = Gtk.Box(halign=[Gtk.Align.START, Gtk.Align.CENTER, Gtk.Align.END][i % 3],
                          valign=[Gtk.Align.START, Gtk.Align.CENTER, Gtk.Align.END][i // 3])
            dot.add_css_class("dot")
            dot.set_margin_start(8)
            dot.set_margin_end(8)
            dot.set_margin_top(6)
            dot.set_margin_bottom(6)
            b = C.button(dot, None, lambda p=pid: pick_pos(p), names[pid])
            pos_btns[pid] = b
            posgrid.attach(b, i % 3, i // 3, 1, 1)

        def pick_pos(pid, fire=True):
            for k, b in pos_btns.items():
                C.set_class(b, "on", k == pid)
            if fire:
                setk("DESK_CLOCK_POS", pid)
        csize = Slider(None, lambda v: setk("DESK_CLOCK_SIZE", int(v)), 40, 200, delay=300, thin=True,
                       fmt=lambda v: f"{int(v)}%")
        csize.scale.set_increments(5, 20)
        fams = sorted({f.get_name() for f in self.win.get_pango_context().list_families()}, key=str.casefold)
        font_items = [tr("По умолчанию (Inter Display)")] + fams
        font_dd = Gtk.DropDown.new_from_strings(font_items)
        font_dd.set_enable_search(True)
        font_dd.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        font_dd.set_hexpand(True)
        fguard = {"on": False}

        def font_changed(d, _p):
            if not fguard["on"]:
                i = d.get_selected()
                setk("DESK_CLOCK_FONT", "" if i <= 0 else font_items[i])
        font_dd.connect("notify::selected", font_changed)
        weight = segmented([(k, t) for k, t in (("thin", tr("Тонкий")), ("light", tr("Лёгкий")), ("regular", tr("Обычный")),
                                                 ("bold", tr("Жирный"))) if k in WEIGHTS],
                           st["DESK_CLOCK_WEIGHT"], lambda v: setk("DESK_CLOCK_WEIGHT", v))
        color = segmented([("light", tr("Белый")), ("accent", tr("Акцент")), ("theme", tr("Как тема"))], st["DESK_CLOCK_COLOR"],
                          lambda v: setk("DESK_CLOCK_COLOR", v))
        cdate = make_switch(st["DESK_CLOCK_DATE"] == "1", lambda on: setk("DESK_CLOCK_DATE", int(on)))
        clock_opts = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=220)
        clock_opts.set_child(box("v", 6, None,
                                 label(tr("Положение"), "small dim"), posgrid,
                                 opt(tr("Размер"), None, None), csize.widget,
                                 label(tr("Шрифт"), "small dim"), font_dd,
                                 label(tr("Насыщенность"), "small dim"), weight,
                                 label(tr("Цвет"), "small dim"), color,
                                 opt(tr("День недели и дата"), None, cdate)))
        content.append(card(label(tr("Часы на обоях"), "card-title"),
                            opt(tr("Показывать"), tr("Видны, когда стол пустой"), clock), clock_opts))
        content.append(C.button(tr("Рамка и стиль панели — в «Строка меню»"), "linkbtn", lambda: self.push("bar")))
        content.append(C.button(tr("24-часовой формат — в «Дата и время»"), "linkbtn", lambda: self.push("time")))

        def refresh():
            s = C.settings()
            dock.setv(s["DOCK"])
            clock.setv(s["DESKTOP_CLOCK"] == "1")
            clock_opts.set_reveal_child(s["DESKTOP_CLOCK"] == "1")
            pick_pos(s["DESK_CLOCK_POS"] if s["DESK_CLOCK_POS"] in POSITIONS else "top", fire=False)
            try:
                csize.setv(int(s["DESK_CLOCK_SIZE"] or 100))
            except ValueError:
                csize.setv(100)
            fguard["on"] = True
            f = s["DESK_CLOCK_FONT"]
            font_dd.set_selected(font_items.index(f) if f in font_items else 0)
            fguard["on"] = False
            weight.setv(s["DESK_CLOCK_WEIGHT"])
            color.setv(s["DESK_CLOCK_COLOR"])
            cdate.setv(s["DESK_CLOCK_DATE"] == "1")
            fill_pins()
        return {"widget": outer, "refresh": refresh}

    # ══ Windows and animations ═════════════════════════════════════════════
    def build_windows(self):
        outer, content = self.subpage(tr("Окна и анимации"))
        opac = Slider(None, lambda v: C.set_setting("WIN_OPACITY", f"{v / 100:.2f}"), 50, 100, delay=250, thin=True,
                      fmt=lambda v: f"{int(v)}%")
        border = make_switch(True, lambda on: C.set_setting("WIN_BORDER", int(on)))
        radius = Slider(None, lambda v: C.set_setting("WIN_RADIUS", int(v)), 0, 28, delay=250, thin=True,
                        fmt=lambda v: f"{int(v)} px")
        gaps = Slider(None, lambda v: C.set_setting("WIN_GAPS", int(v)), 0, 32, delay=250, thin=True,
                      fmt=lambda v: f"{int(v)} px")
        maxi = make_switch(True, lambda on: C.set_setting("WIN_MAXIMIZED", int(on)))
        content.append(card(label(tr("Окна"), "card-title"),
                            opt(tr("Прозрачность неактивных"), tr("Активное окно всегда непрозрачное"), None), opac.widget,
                            opt(tr("Тонкая обводка"), tr("Едва заметная рамка вокруг окон"), border),
                            opt(tr("Скругление углов"), None, None), radius.widget,
                            opt(tr("Отступы между окнами"), None, None), gaps.widget,
                            opt(tr("Открывать развёрнутыми"), tr("Новые окна сразу на всю ширину"), maxi)))
        anim = make_switch(True, lambda on: C.set_setting("ANIM_ENABLED", int(on)))
        speed = segmented([("0.5", "0.5×"), ("0.75", "0.75×"), ("1.0", "1×"), ("1.5", "1.5×"), ("2.0", "2×")],
                          "1.0", lambda v: C.set_setting("ANIM_SPEED", v))
        content.append(card(label(tr("Анимации"), "card-title"),
                            opt(tr("Анимации niri"), tr("Открытие окон, столы, обзор"), anim),
                            opt(tr("Скорость"), tr("Больше — быстрее"), None), speed))
        eco = make_switch(False, lambda on: (C.set_setting("ECO", int(on)), opac.widget.set_sensitive(not on)))
        content.append(card(label(tr("Производительность"), "card-title"),
                            opt(tr("Режим экономии"), tr("Без блюра под окнами и панелями, неактивные окна непрозрачные — "
                                                  "меньше работы видеокарте, дольше батарея"), eco)))
        content.append(label(tr("Super+F — окно на весь экран поверх панели, повторно — обратно. "
                             "Super+Shift+F — развернуть колонку."), "tiny muted", wrap=True))

        def refresh():
            s = C.settings()
            opac.setv(round(float(s["WIN_OPACITY"]) * 100))
            border.setv(s["WIN_BORDER"] == "1")
            radius.setv(int(s["WIN_RADIUS"]))
            gaps.setv(int(s["WIN_GAPS"]))
            maxi.setv(s["WIN_MAXIMIZED"] == "1")
            anim.setv(s["ANIM_ENABLED"] == "1")
            eco.setv(s["ECO"] == "1")
            opac.widget.set_sensitive(s["ECO"] != "1")
            sp = f"{float(s['ANIM_SPEED']):g}"
            speed.setv({"0.5": "0.5", "0.75": "0.75", "1": "1.0", "1.5": "1.5", "2": "2.0"}.get(sp, "1.0"))
        return {"widget": outer, "refresh": refresh}

    # ══ Input: mouse, touchpad, hot corner ═════════════════════════════════
    def build_input(self):
        outer, content = self.subpage(tr("Управление"))
        layouts = segmented(KB_LAYOUTS, "us,ru", lambda v: C.set_setting("KB_LAYOUTS", v))
        switch = segmented(KB_SWITCHES, "caps", lambda v: C.set_setting("KB_SWITCH", v))
        content.append(card(label(tr("Клавиатура"), "card-title"),
                            opt(tr("Языки"), None, None), layouts,
                            opt(tr("Смена языка"), tr("С Caps Lock настоящий Caps — Shift+Caps"), None), switch))
        tap = make_switch(True, lambda on: C.set_setting("TP_TAP", int(on)))
        nat = make_switch(True, lambda on: C.set_setting("TP_NATURAL", int(on)))
        tps = Slider(None, lambda v: C.set_setting("TP_SPEED", f"{v / 100:.2f}"), -50, 100, delay=300, thin=True,
                     fmt=lambda v: f"{int(v):+d}")
        tsc = Slider(None, lambda v: C.set_setting("TP_SCROLL", f"{v / 100:.2f}"), 20, 150, delay=300, thin=True,
                     fmt=lambda v: f"{v / 100:.1f}×")
        content.append(card(label(tr("Тачпад"), "card-title"),
                            opt(tr("Касание — клик"), tr("Два пальца — правый клик, три — средний"), tap),
                            opt(tr("Естественная прокрутка"), tr("Контент едет за пальцами, как на телефоне"), nat),
                            opt(tr("Скорость указателя"), None, None), tps.widget,
                            opt(tr("Скорость прокрутки"), None, None), tsc.widget))
        ms = Slider(None, lambda v: C.set_setting("MOUSE_SPEED", f"{v / 100:.2f}"), -100, 100, delay=300, thin=True,
                    fmt=lambda v: f"{int(v):+d}")
        mnat = make_switch(False, lambda on: C.set_setting("MOUSE_NATURAL", int(on)))
        content.append(card(label(tr("Мышь"), "card-title"),
                            opt(tr("Скорость"), tr("Без ускорения: одно движение — одно расстояние"), None), ms.widget,
                            opt(tr("Обратная прокрутка колесом"), None, mnat)))
        ffm = make_switch(True, lambda on: C.set_setting("FOCUS_FOLLOWS", int(on)))
        corner = segmented(CORNERS, "top-left", lambda v: C.set_setting("HOT_CORNER", v, lambda *_: self.refresh_main()))
        content.append(card(label(tr("Окна"), "card-title"),
                            opt(tr("Фокус за мышью"), tr("Окно под курсором становится активным без клика"), ffm),
                            opt(tr("Горячий угол"), tr("Курсор в угол — обзор всех окон"), None), corner))
        tips = [
            (tr("Тачпад"), [(tr("3 пальца ← →"), tr("листать окна")), (tr("3 пальца ↑ ↓"), tr("рабочие столы")),
                        (tr("4 пальца ↑"), tr("обзор всех окон"))]),
            (tr("Строка меню"), [(tr("колесо на точках"), tr("рабочие столы")), (tr("колесо на заголовке"), tr("соседние окна")),
                             (tr("2× клик по заголовку"), tr("развернуть окно")), (tr("СКМ по заголовку"), tr("закрыть окно")),
                             (tr("колесо на логотипе"), tr("листать обои")), (tr("СКМ по логотипу"), tr("случайные обои")),
                             (tr("клик по языку"), tr("сменить раскладку")), (tr("ПКМ по батарее"), tr("режим питания"))]),
            (tr("Клавиатура"), [(tr("Super+Пробел"), tr("поиск")), ("Super+A", tr("пункт управления")),
                            ("Super+Shift+C", "Claude"), (tr("Super+колесо"), tr("рабочие столы")),
                            ("Super+Shift+/", tr("все сочетания"))]),
        ]
        cheat = box("v", 10, None)
        content.append(card(label(tr("Шпаргалка"), "card-title"), cheat))

        def fill_cheat(s):
            C.clear(cheat)
            for title, rows in tips:
                g = Gtk.Grid(column_spacing=12, row_spacing=4)
                rows = [r for r in rows if s["CLAUDE"] == "1" or r[1] != "Claude"]
                for i, (k, v) in enumerate(rows):
                    g.attach(label(k, "kbd", ellipsize=False, halign=Gtk.Align.START), 0, i, 1, 1)
                    g.attach(label(v, "tiny muted", hexpand=True), 1, i, 1, 1)
                cheat.append(box("v", 4, None, label(title, "zonetitle"), g))

        def refresh():
            s = C.settings()
            fill_cheat(s)
            layouts.setv(s["KB_LAYOUTS"].replace(" ", ""))
            switch.setv(s["KB_SWITCH"])
            tap.setv(s["TP_TAP"] == "1")
            nat.setv(s["TP_NATURAL"] == "1")
            tps.setv(round(float(s["TP_SPEED"] or 0) * 100))
            tsc.setv(round(float(s["TP_SCROLL"] or 0.7) * 100))
            ms.setv(round(float(s["MOUSE_SPEED"] or 0) * 100))
            mnat.setv(s["MOUSE_NATURAL"] == "1")
            ffm.setv(s["FOCUS_FOLLOWS"] == "1")
            corner.setv(s["HOT_CORNER"] if s["HOT_CORNER"] in dict(CORNERS) else "off")
        return {"widget": outer, "refresh": refresh}

    # ══ Claude ═════════════════════════════════════════════════════════════
    def build_claude(self):
        outer, content = self.subpage("Claude")
        nb = str(C.BIN / "nb-claude")
        code_s = label("", "tiny muted", wrap=True)
        desk_s = label("", "tiny muted", wrap=True)
        busy = label("", "tiny muted", wrap=True)
        btns = box("h", 6, None)
        run = lambda *a: (self.hide(), C.spawn([nb, *a]))

        def action(text, cls, fn):
            return C.button(text, cls, fn)

        def install_deb():
            busy.set_text(tr("Скачиваю официальный .deb и распаковываю в домашнюю папку… "
                          "Можно закрыть панель — придёт уведомление."))
            btns.set_sensitive(False)
            C.run_async([nb, "install", "deb"], lambda *_: refresh())

        def remove_deb():
            btns.set_sensitive(False)
            C.run_async([nb, "remove"], lambda *_: refresh())

        content.append(card(label("Claude Code", "card-title"),
                            opt(tr("В терминале"), None, None), code_s,
                            box("h", 6, None,
                                action(tr("Открыть"), "accentbtn", lambda: run("here")),
                                action(tr("Продолжить"), "ghostbtn", lambda: run("continue")))))
        content.append(card(label("Claude Desktop", "card-title"),
                            opt(tr("Приложение с окном"), None, None), desk_s, btns, busy))

        how = segmented([("terminal", tr("Терминал")), ("desktop", "Desktop")], "terminal",
                        lambda v: C.set_setting("CLAUDE_OPEN", v))
        mode = segmented([("default", tr("Обычный")), ("plan", tr("План")), ("acceptEdits", tr("Правки")), ("auto", tr("Авто"))],
                         "default", lambda v: C.set_setting("CLAUDE_MODE", v))
        cont = make_switch(False, lambda on: C.set_setting("CLAUDE_CONTINUE", int(on)))
        dolphin = make_switch(True, lambda on: C.set_setting("CLAUDE_DOLPHIN", int(on)))
        content.append(card(label(tr("Настройки"), "card-title"),
                            opt(tr("Super+Shift+C открывает"), None, None), how,
                            opt(tr("Разрешения Claude Code"), tr("«Обычный» — подтверждать каждое действие, «План» — "
                                "сначала только план, «Правки» — менять файлы без вопросов"), None), mode,
                            opt(tr("Продолжать прошлый разговор"), tr("Если в папке уже говорили с Claude"), cont),
                            opt(tr("Меню в Dolphin"), tr("ПКМ по папке или файлу → Claude"), dolphin)))
        content.append(label(tr("Поиск: начните с «?» — «?как переименовать много файлов» откроет Claude "
                             "с этим вопросом. Выключить дополнение целиком — Настройки → Дополнения."),
                             "tiny muted", wrap=True))

        def refresh():
            s = C.settings()
            how.setv(s["CLAUDE_OPEN"])
            mode.setv(s["CLAUDE_MODE"] if s["CLAUDE_MODE"] in ("plan", "acceptEdits", "auto") else "default")
            cont.setv(s["CLAUDE_CONTINUE"] == "1")
            dolphin.setv(s["CLAUDE_DOLPHIN"] == "1")

            def got(_ok, out):
                info = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
                code_s.set_text(tr("Версия {0}").format(info['code']) if info.get("code") else
                                tr("Не установлен: yay -S claude-code (AUR) или npm i -g @anthropic-ai/claude-code"))
                d, v = info.get("desktop"), info.get("desktop_ver", "")
                child = btns.get_first_child()
                while child:
                    nxt = child.get_next_sibling()
                    btns.remove(child)
                    child = nxt
                btns.set_sensitive(True)
                busy.set_text("")
                if d == "aur":
                    desk_s.set_text(tr("Установлен из AUR · {0}. Обновляется вместе с системой").format(v))
                    btns.append(action(tr("Открыть"), "accentbtn", lambda: run("desktop")))
                elif d == "deb":
                    desk_s.set_text(tr("Импортирован из официального .deb · {0}. Лежит в домашней папке, root не нужен").format(v))
                    btns.append(action(tr("Открыть"), "accentbtn", lambda: run("desktop")))
                    btns.append(action(tr("Обновить"), "ghostbtn", install_deb))
                    btns.append(action(tr("Удалить"), "ghostbtn", remove_deb))
                else:
                    desk_s.set_text(tr("Официально выпускается только в виде .deb. Здесь его можно импортировать: "
                                    "распаковать .deb в домашнюю папку (без root) или поставить пакет из AUR"))
                    btns.append(action(tr("Импорт .deb"), "accentbtn", install_deb))
                    if info.get("aur") == "1":
                        btns.append(action(tr("Из AUR"), "ghostbtn", lambda: run("install", "aur")))
            C.run_async([nb, "status"], got)
        return {"widget": outer, "refresh": refresh}

    # ══ Extras: fun stuff, Claude, the setup wizard ════════════════════════
    def build_extras(self):
        outer, content = self.subpage(tr("Дополнения"))
        fun = make_switch(True, lambda on: C.set_setting("FUN", int(on)))
        greet = make_switch(True, lambda on: C.set_setting("GREETING", int(on)))
        wall = make_switch(False, lambda on: C.set_setting("WALL_ON_LOGIN", int(on)))
        from launcher import surprise
        content.append(card(label(tr("Приколы"), "card-title"),
                            opt(tr("Пасхалки в поиске"), tr("«пароль», «помидор», «погода», «#ff8800», «монетка», «2d6», «шар …», «таймер 5 мин», "
                                "каомодзи, «удиви меня» и один код из девяностых"), fun),
                            opt(tr("Приветствие при входе"), tr("«Доброе утро, …» и что сегодня за день"), greet),
                            opt(tr("Новые обои при каждом входе"), tr("Случайные из папки обоев"), wall),
                            box("h", 6, None, C.button(tr("Удиви меня"), "accentbtn", surprise),
                                C.button(tr("Поздороваться"), "ghostbtn", lambda: C.spawn(
                                    [str(C.BIN / "nb-greet"), "--now"])))))

        claude = make_switch(False, lambda on: C.set_setting("CLAUDE", int(on), lambda *_: refresh()))
        more = C.button(box("h", 4, None, label(tr("Настройки Claude"), "t", hexpand=True), icon(I["right"], "chev")),
                        "ghostbtn", lambda: self.push("claude"))
        content.append(card(label("Claude", "card-title"),
                            opt(tr("Включить"), tr("Claude Code в терминале и Claude Desktop: Super+Shift+C, «?вопрос» "
                                "в поиске, меню в Dolphin. Выключено — следов Claude в системе нет"), claude),
                            more))

        content.append(card(label(tr("Начало"), "card-title"),
                            opt(tr("Мастер первоначальной настройки"), tr("Тема, обои, строка меню, клавиатура и приколы "
                                "— по шагам, как при первом входе"), None),
                            box("h", 6, None, C.button(tr("Запустить"), "accentbtn",
                                                       lambda: self.hide(then=self.shell.welcome.show)))))

        def refresh():
            s = C.settings()
            fun.setv(s["FUN"] == "1")
            greet.setv(s["GREETING"] == "1")
            wall.setv(s["WALL_ON_LOGIN"] == "1")
            claude.setv(s["CLAUDE"] == "1")
            more.set_visible(s["CLAUDE"] == "1")
        return {"widget": outer, "refresh": refresh}

    # ══ Profile ════════════════════════════════════════════════════════════
    def build_profile(self):
        outer, content = self.subpage(tr("Профиль"))
        big = Avatar(108)
        real, login = C.user_name()
        host = Path("/proc/sys/kernel/hostname").read_text().strip()
        status = label("", "tiny muted", xalign=0.5, wrap=True)
        src = C.STATE / "avatar-src"     # the original, so the crop can be changed later
        state = {"editing": False}

        crop = Cropper()
        zoom = Slider(None, lambda v: crop.set_zoom(v / 100), 100, 400, delay=0, thin=True,
                      fmt=lambda v: f"{int(v)}%")
        crop.on_zoom = lambda z: zoom.setv(round(z * 100))
        editor = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=260)
        editor.set_child(card(label(tr("Кадр"), "card-title"), crop,
                              opt(tr("Масштаб"), tr("Тяните фото, чтобы сдвинуть; колесо — приблизить"), None),
                              zoom.widget,
                              box("h", 8, None,
                                  C.button(tr("Сохранить"), "accentbtn", lambda: save()),
                                  C.button(tr("Отмена"), "ghostbtn", lambda: edit(False)), halign=Gtk.Align.CENTER),
                              spacing=8))

        def edit(on, path=None):
            if on and not crop.load(path or (src if src.exists() else S.FACE)):
                status.set_text(tr("Не удалось открыть картинку"))
                on = False
            state["editing"] = on
            zoom.setv(100)
            editor.set_reveal_child(on)
            view.set_reveal_child(not on)

        def chosen(paths):
            import shutil
            try:
                shutil.copyfile(paths[0], src)
            except OSError:
                pass
            edit(True, paths[0])

        def save():
            out = C.CACHE / "face-crop.png"
            try:
                crop.save(out)
            except Exception:
                status.set_text(tr("Не удалось сохранить"))
                return
            status.set_text(tr("Сохраняю…"))
            S.avatar_set(str(out), lambda ok: GLib.idle_add(after, ok))

        def after(ok):
            edit(False)
            big.update()
            self.avatar.update()
            status.set_text(tr("Фото обновлено") if ok else tr("Не удалось открыть картинку"))
            return False

        def remove():
            S.avatar_remove()
            try:
                src.unlink()
            except OSError:
                pass
            big.update()
            self.avatar.update()
            refresh()

        reframe = C.button(tr("Изменить кадр"), "ghostbtn", lambda: edit(True))
        view = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, transition_duration=220,
                            reveal_child=True)
        view.set_child(card(big, label(real, "who name", xalign=0.5),
                            label(f"{login}@{host}", "small muted", xalign=0.5),
                            box("h", 8, None,
                                C.button(tr("Выбрать фото…"), "accentbtn",
                                         lambda: self.file_dialog(tr("Фото профиля"), chosen)),
                                reframe,
                                C.button(tr("Убрать"), "ghostbtn", remove), halign=Gtk.Align.CENTER),
                            spacing=10))
        content.append(view)
        content.append(editor)
        content.append(status)
        content.append(label(tr("Фото хранится в ~/.face: оно здесь, на экране блокировки и — если система "
                             "поддерживает — на экране входа. В Dolphin: ПКМ по картинке → «Nebula» → «Фото профиля»."),
                             "tiny muted", wrap=True))

        def refresh():
            big.update()
            reframe.set_visible(S.FACE.exists())
            if not state["editing"]:
                status.set_text("")
        return {"widget": outer, "refresh": refresh}
