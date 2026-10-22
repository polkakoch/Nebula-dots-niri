"""Nebula shell — shared paths, theme, settings, running processes and small widgets."""
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk, Gtk4LayerShell as LS

from i18n import LANG, tr  # noqa: F401  (re-exported, so modules can `from common import tr`)

NB_DIR = Path(__file__).resolve().parent.parent
BIN = NB_DIR / "bin"
HOME = Path.home()
CONF = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
STATE = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / "nebula"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "nebula"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "nebula"
for _d in (STATE, CACHE, RUNTIME):
    _d.mkdir(parents=True, exist_ok=True)

# Nerd Font icons (Material Design). Escaped, so they don't get lost when the file is edited.
I = {
    "wifi": "\U000f05a9", "wifi_off": "\U000f05aa", "bt": "\U000f00af", "bt_off": "\U000f00b2",
    "moon": "\U000f0f65", "night": "\U000f0594", "sun": "\U000f05a8", "coffee": "\U000f0176",
    "speed": "\U000f04c5", "leaf": "\U000f032a", "camera": "\U000f0100", "bright": "\U000f00e0",
    "vol": "\U000f057e", "vol_low": "\U000f057f", "vol_mid": "\U000f0580", "mute": "\U000f075f",
    "mic": "\U000f036c", "mic_off": "\U000f036d", "lock": "\U000f033e", "power": "\U000f0425",
    "cog": "\U000f0493", "right": "\U000f0142", "left": "\U000f0141", "up": "\U000f0143", "down": "\U000f0140", "search": "\U000f0349",
    "palette": "\U000f03d8", "wall": "\U000f0e09", "monitor": "\U000f0379", "clock": "\U000f0954",
    "account": "\U000f0009", "term": "\U000f018d", "image": "\U000f02e9", "folder": "\U000f024b",
    "plus": "\U000f0415", "shuffle": "\U000f049f", "play": "\U000f040a", "pause": "\U000f03e4",
    "next": "\U000f04ad", "prev": "\U000f04ae", "music": "\U000f0386", "bell": "\U000f009a",
    "bell_off": "\U000f009b", "calc": "\U000f00ec", "web": "\U000f059f", "logout": "\U000f05fd",
    "reboot": "\U000f0709", "sleep": "\U000f04b2", "check": "\U000f012c", "close": "\U000f0156",
    "refresh": "\U000f0450", "clip": "\U000f0147", "apps": "\U000f003b", "window": "\U000f05d8",
    "earth": "\U000f01e7", "user": "\U000f0004", "delete": "\U000f01b4", "bar": "\U000f08c6",
    "headphones": "\U000f02cb", "speaker": "\U000f04c3", "fetch": "\U000f0e51", "theme": "\U000f03d8",
    "mouse": "\U000f037d", "claude": "\U000f0674", "dice": "\U000f01ce", "keyboard": "\U000f030c",
    "star": "\U000f04ce", "puzzle": "\U000f0431", "rocket": "\U000f0463",
    "wifi_s": ["\U000f092f", "\U000f091f", "\U000f0922", "\U000f0925", "\U000f0928"],
}


# ─── settings (settings.conf — plain KEY="value", readable by bash too) ──────
DEFAULTS = {
    "WALL_DIR": str(HOME / "Pictures/Wallpapers"), "TERMINAL": "kitty", "OSD_DURATION": "1.6",
    "FRAME": "1", "FRAME_SIZE": "8", "BAR_STYLE": "", "BAR_HEIGHT": "34",
    "BAR_LEFT": "logo workspaces window", "BAR_CENTER": "media",
    "BAR_RIGHT": "tray volume brightness language network battery control clock",
    "BAR_MEDIA_COVER": "1", "BAR_MEDIA_LEN": "40", "DOCK": "autohide", "DOCK_APPS": "auto", "DESKTOP_CLOCK": "1",
    "DESK_CLOCK_POS": "top", "DESK_CLOCK_SIZE": "100", "DESK_CLOCK_FONT": "", "DESK_CLOCK_WEIGHT": "light",
    "DESK_CLOCK_COLOR": "light", "DESK_CLOCK_DATE": "1", "ECO": "0",
    "CLOCK_24H": "1", "CLOCK_SECONDS": "0", "CLOCK_DATE": "1",
    "WIN_OPACITY": "0.9", "WIN_BORDER": "1", "WIN_RADIUS": "14", "WIN_GAPS": "10", "WIN_MAXIMIZED": "1",
    "ANIM_ENABLED": "1", "ANIM_SPEED": "1.0",
    "FETCH_DIR": str(HOME / "Pictures/Fastfetch"), "FETCH_MODE": "fixed", "FETCH_SIZE": "16",
    "SEARCH_URL": "https://www.google.com/search?q=", "NIGHT_TEMP": "4000",
    "TP_TAP": "1", "TP_NATURAL": "1", "TP_SPEED": "0.15", "TP_SCROLL": "0.7", "MOUSE_SPEED": "0",
    "MOUSE_NATURAL": "0", "FOCUS_FOLLOWS": "1", "HOT_CORNER": "top-left",
    "KB_LAYOUTS": "us,ru", "KB_SWITCH": "caps", "FUN": "1", "GREETING": "1",
    "WALL_ON_LOGIN": "0", "UI_LANG": "auto", "NOTIFY": "1", "NOTIF_TIMEOUT": "5", "NOTIF_SOUND": "0", "NOTIF_POS": "top-right",
    "CLAUDE": "0", "CLAUDE_OPEN": "terminal", "CLAUDE_MODE": "default", "CLAUDE_CONTINUE": "0", "CLAUDE_DOLPHIN": "1",
}


_SETTINGS = [None, {}]   # (mtime, dict) — the file is only re-read when it changes


def settings():
    path = NB_DIR / "settings.conf"
    try:
        mt = path.stat().st_mtime_ns
    except OSError:
        mt = None
    if mt is not None and _SETTINGS[0] == mt:
        return dict(_SETTINGS[1])
    out = dict(DEFAULTS)
    try:
        for line in path.read_text().splitlines():
            m = re.match(r'\s*([A-Z_][A-Z0-9_]*)=(.*)$', line)
            if not m:
                continue
            v = m.group(2).strip()
            if v[:1] in "\"'":
                q = v[0]
                v = v[1:v.find(q, 1)] if v.find(q, 1) > 0 else v[1:]
            else:
                v = v.split("#")[0].strip()
            v = v.replace("\\\"", "\"").replace("$HOME", str(HOME))
            if v.startswith("~/"):
                v = str(HOME) + v[1:]
            out[m.group(1)] = v
    except OSError:
        pass
    _SETTINGS[0], _SETTINGS[1] = mt, out
    return dict(out)


def set_setting(key, value, done=None):
    """nb-settings set — writes settings.conf and regenerates the niri/waybar configs."""
    run_async([str(BIN / "nb-settings"), "set", key, str(value)], done)


# ─── theme ──────────────────────────────────────────────────────────────────
def current_theme_id():
    try:
        return (STATE / "theme").read_text().strip() or "catppuccin-mocha"
    except OSError:
        return "catppuccin-mocha"


def read_theme_file(path):
    c = {}
    for line in Path(path).read_text().splitlines():
        if not line.lstrip().startswith("#"):
            for k, v in re.findall(r'(\w+)=("[^"]*"|\S+)', line):
                c[k] = v.strip('"')
    c.setdefault("on_accent", c.get("bg", "#000000"))
    c.setdefault("mode", "dark")
    return c


def theme_path(tid):
    if tid == "matugen":
        return CACHE / "matugen.theme"
    return NB_DIR / "themes" / f"{tid}.theme"


def load_theme():
    p = theme_path(current_theme_id())
    if not p.is_file():
        p = NB_DIR / "themes" / "catppuccin-mocha.theme"
    return read_theme_file(p)


def list_themes():
    out = []
    for f in sorted((NB_DIR / "themes").glob("*.theme")):
        try:
            c = read_theme_file(f)
            out.append((f.stem, c.get("name", f.stem), c))
        except OSError:
            pass
    m = CACHE / "matugen.theme"
    out.append(("matugen", tr("Из обоев"), read_theme_file(m) if m.is_file() else None))
    return out


def rgba(hexc, a=1.0):
    h = hexc.lstrip("#")
    if len(h) < 6:
        h = "000000"
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a:.3f})"


def hex_to_rgb(hexc):
    h = hexc.lstrip("#")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


# ─── processes ──────────────────────────────────────────────────────────────
def spawn(argv):
    """Start detached (setsid -f): not our child, so it outlives the shell."""
    if isinstance(argv, str):
        argv = ["sh", "-c", argv]
    try:
        subprocess.run(["setsid", "-f", *argv], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, cwd=str(HOME), timeout=3)
    except Exception:
        pass


def run_async(argv, done=None, stdin=None):
    """Run asynchronously and call done(ok, stdout) on the main thread."""
    flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
    if stdin is not None:
        flags |= Gio.SubprocessFlags.STDIN_PIPE
    try:
        p = Gio.Subprocess.new([str(a) for a in argv], flags)
    except GLib.Error:
        if done:
            GLib.idle_add(lambda: done(False, "") and False)
        return None

    def fin(proc, res):
        try:
            _ok, out, _err = proc.communicate_utf8_finish(res)
        except GLib.Error:
            out = ""
        if done:
            done(proc.get_successful(), out or "")
    p.communicate_utf8_async(stdin, None, fin)
    return p


def run_sync(argv, timeout=2):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def has(cmd):
    return GLib.find_program_in_path(cmd) is not None


def copy_text(text):
    p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, start_new_session=True)
    p.communicate(text.encode())


def uptime_text():
    try:
        s = int(float(Path("/proc/uptime").read_text().split()[0]))
    except OSError:
        return ""
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    parts = []
    if d:
        parts.append(tr("{0} д").format(d))
    if h:
        parts.append(tr("{0} ч").format(h))
    parts.append(tr("{0} мин").format(m))
    return tr("работает ") + " ".join(parts)


_DAYS_RU = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
_MONTHS_RU = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
              "октября", "ноября", "декабря")
_DAYS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
              "October", "November", "December")


def date_text(now=None, year=False):
    """'Среда, 21 октября' or 'Wednesday, October 21' — done by hand, so it doesn't depend on system locales."""
    now = now or time.localtime()
    if LANG == "ru":
        s = f"{_DAYS_RU[now.tm_wday].capitalize()}, {now.tm_mday} {_MONTHS_RU[now.tm_mon - 1]}"
        return f"{s} {now.tm_year}" if year else s
    s = f"{_DAYS_EN[now.tm_wday]}, {_MONTHS_EN[now.tm_mon - 1]} {now.tm_mday}"
    return f"{s}, {now.tm_year}" if year else s


def user_name():
    import pwd
    pw = pwd.getpwuid(os.getuid())
    return (pw.pw_gecos.split(",")[0] or pw.pw_name), pw.pw_name


# ─── widgets ────────────────────────────────────────────────────────────────
def icon(glyph, cls="icon", size=None):
    lbl = Gtk.Label(label=glyph)
    lbl.add_css_class("icon")
    if cls and cls != "icon":
        for c in cls.split():
            lbl.add_css_class(c)
    return lbl


def label(text="", cls=None, xalign=0.0, ellipsize=True, wrap=False, max_chars=None, **kw):
    lbl = Gtk.Label(label=text, xalign=xalign, **kw)
    if ellipsize:
        lbl.set_ellipsize(3)   # END
    if wrap:
        lbl.set_wrap(True)
        lbl.set_wrap_mode(2)   # WORD_CHAR: a long link or path can't stretch the panel
        lbl.set_ellipsize(0)
    if max_chars:
        lbl.set_max_width_chars(max_chars)
    if cls:
        for c in cls.split():
            lbl.add_css_class(c)
    return lbl


def box(orient="h", spacing=0, cls=None, *children, **kw):
    b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if orient == "h" else Gtk.Orientation.VERTICAL,
                spacing=spacing, **kw)
    if cls:
        for c in cls.split():
            b.add_css_class(c)
    for ch in children:
        if ch is not None:
            b.append(ch)
    return b


def button(child=None, cls=None, on_click=None, tooltip=None):
    b = Gtk.Button()
    if isinstance(child, str):
        b.set_label(child)
    elif child is not None:
        b.set_child(child)
    b.set_can_focus(False)
    if cls:
        for c in cls.split():
            b.add_css_class(c)
    if on_click:
        b.connect("clicked", lambda *_: on_click())
    if tooltip:
        b.set_tooltip_text(tooltip)
    return b


def set_class(widget, cls, on):
    (widget.add_css_class if on else widget.remove_css_class)(cls)


def clear(container):
    ch = container.get_first_child()
    while ch:
        nxt = ch.get_next_sibling()
        container.remove(ch)
        ch = nxt


def texture_scaled(path, w, h, crop=True):
    """A picture scaled down to the size it's shown at (saves memory across hundreds of previews)."""
    from gi.repository import GdkPixbuf
    try:
        if crop:
            # decode straight at the target size (big pictures never get fully unpacked)
            _fmt, fw, fh = GdkPixbuf.Pixbuf.get_file_info(str(path))
            if fw and fh:
                s = max(w / fw, h / fh)
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), max(1, round(fw * s)),
                                                             max(1, round(fh * s)), False)
            else:
                pb = GdkPixbuf.Pixbuf.new_from_file(str(path))
            s = max(w / pb.get_width(), h / pb.get_height())
            sw, sh = max(1, round(pb.get_width() * s)), max(1, round(pb.get_height() * s))
            if (sw, sh) != (pb.get_width(), pb.get_height()):
                pb = pb.scale_simple(sw, sh, GdkPixbuf.InterpType.BILINEAR)
            pb = pb.new_subpixbuf((sw - w) // 2, (sh - h) // 2, min(w, sw), min(h, sh))
        else:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), w, h, True)
        return Gdk.Texture.new_for_pixbuf(pb)
    except Exception:
        return None


def ease_out_cubic(t):
    return 1 - (1 - t) ** 3


def ease_out_quint(t):
    return 1 - (1 - t) ** 5


def ease_in_cubic(t):
    return t * t * t


def spring(t):
    """A spring without a visible overshoot."""
    import math
    return 1 - math.exp(-7.5 * t) * math.cos(t * 2.2)


class Tween:
    """Animates a value: fn(v) on every frame of the window.
    Frames come from the compositor (tick callback). The timer is only a safety net: if no frame
    has arrived for 40 ms (the window is just appearing, or almost off screen), it takes the step
    itself — so the value is never computed twice in one frame."""

    def __init__(self, widget, duration, fn, ease=ease_out_cubic, done=None, start=0.0, end=1.0):
        self.widget, self.duration, self.fn, self.ease, self.done = widget, duration, fn, ease, done
        self.start, self.end = start, end
        self.t0 = time.monotonic()
        self.finished = False
        self.last = 0.0
        self.tick_id = widget.add_tick_callback(lambda *_: self._step("tick"))
        self.timer_id = GLib.timeout_add(20, lambda: self._step("timer"))

    def _step(self, src):
        if self.finished:
            return GLib.SOURCE_REMOVE
        now = time.monotonic()
        if src == "tick":
            self.last = now
        elif now - self.last < 0.04:
            return GLib.SOURCE_CONTINUE   # frames are coming, the timer isn't needed
        t = min(1.0, (time.monotonic() - self.t0) / self.duration) if self.duration > 0 else 1.0
        self.fn(self.start + (self.end - self.start) * self.ease(t))
        if t >= 1.0:
            # the source we came from removes itself via SOURCE_REMOVE
            if src == "tick":
                self.tick_id = None
            else:
                self.timer_id = None
            self._stop()
            if self.done:
                self.done()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _stop(self):
        self.finished = True
        if self.tick_id is not None:
            self.widget.remove_tick_callback(self.tick_id)
            self.tick_id = None
        if self.timer_id is not None:
            GLib.source_remove(self.timer_id)
            self.timer_id = None

    def cancel(self):
        if not self.finished:
            self._stop()


def monitor_geometry():
    disp = Gdk.Display.get_default()
    mons = disp.get_monitors()
    if mons.get_n_items():
        return mons.get_item(0).get_geometry()
    r = Gdk.Rectangle()
    r.width, r.height = 1920, 1080
    return r


class Backdrop(Gtk.Window):
    """A transparent full-screen layer under the shell's windows: click outside to close."""

    def __init__(self, app, on_click):
        super().__init__(application=app)
        LS.init_for_window(self)
        LS.set_namespace(self, "nebula-backdrop")
        LS.set_layer(self, LS.Layer.TOP)
        LS.set_keyboard_mode(self, LS.KeyboardMode.NONE)
        LS.set_exclusive_zone(self, -1)
        for e in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(self, e, True)
        self.add_css_class("backdrop")
        area = Gtk.Box()
        area.set_hexpand(True)
        area.set_vexpand(True)
        g = Gtk.GestureClick()
        g.set_button(0)
        g.connect("pressed", lambda *_: on_click())
        area.add_controller(g)
        self.set_child(area)


# ─── sheets that grow out of the frame ──────────────────────────────────────
BAR_STYLE_IDS = ("frame", "floating", "classic", "pills", "islands", "notch", "minimal")


def bar_style():
    """frame | floating | classic | pills | islands | notch | minimal (empty — go by the old FRAME key)."""
    s = settings()
    st = s.get("BAR_STYLE", "")
    if st not in BAR_STYLE_IDS:
        st = "frame" if s.get("FRAME", "1") == "1" else "floating"
    return st


def bar_height():
    try:
        return max(24, min(56, int(settings().get("BAR_HEIGHT") or 34)))
    except ValueError:
        return 34


def frame_size():
    """Thickness of the frame around the screen; 0 means no frame (the bar isn't in the frame style)."""
    if bar_style() != "frame":
        return 0
    try:
        return int(settings().get("FRAME_SIZE") or 8)
    except ValueError:
        return 8


EAR = 20       # the concave "ears" that let a sheet grow seamlessly out of the bar/frame
SHEET_R = 22   # radius of a sheet's free corners
GAP = 8        # distance of floating cards from the screen edge / menu bar (styles without a frame)


class Sheet(Gtk.Overlay):
    """A backing in the frame's color that "grows" out of the screen edge.

    kind: top — hangs from the menu bar (ears on top, rounded bottom);
          right — slides out of the right frame (ears top-left and bottom-left);
          bottom — rises from the bottom frame (ears at the bottom, rounded top).
    progress (0…1) — how far the sheet has "grown" (for top/bottom); the ears are always visible.
    """

    def __init__(self, kind, content, colors_fn):
        super().__init__()
        self.kind, self.colors_fn, self.progress = kind, colors_fn, 1.0
        self.da = Gtk.DrawingArea()
        self.da.set_draw_func(self.draw)
        self.set_child(self.da)
        self.content = content
        self.add_overlay(content)
        self.set_measure_overlay(content, True)
        self.refresh()

    def set_progress(self, p):
        self.progress = p
        self.da.queue_draw()

    def refresh(self):
        """Re-read the style: with a frame — a sheet with ears; without — a floating card GAP away from the edge."""
        self.band = frame_size()
        self.floating = bar_style() != "frame"
        E, G, T = EAR, GAP, self.band
        if self.floating:
            pad = {"top": (G, E, 0, E), "right": (G, G, G, E), "bottom": (0, E, G, E)}[self.kind]
        else:
            pad = {"top": (0, E, 0, E), "right": (0, 0, 0, E), "bottom": (0, E, T, E)}[self.kind]
        self.content.set_margin_top(pad[0])
        self.content.set_margin_end(pad[1])
        self.content.set_margin_bottom(pad[2])
        self.content.set_margin_start(pad[3])
        self.da.queue_draw()

    def draw(self, _da, cr, w, h):
        import math
        c = self.colors_fn()
        E, R, T, p, G = EAR, SHEET_R, self.band, self.progress, GAP
        if self.floating:
            # floating card: all corners rounded, a thin outline; it "grows" from the screen edge
            if self.kind == "top":
                x0, x1, y0 = E, w - E, G
                y1 = y0 + max(2 * R, (h - y0) * p)
            elif self.kind == "bottom":
                x0, x1, y1 = E, w - E, h - G
                y0 = y1 - max(2 * R, (y1) * p)
            else:
                x0, x1, y0, y1 = E, w - G, G, h - G
            r = min(R, (y1 - y0) / 2, (x1 - x0) / 2)
            cr.new_sub_path()
            cr.arc(x1 - r, y0 + r, r, -math.pi / 2, 0)
            cr.arc(x1 - r, y1 - r, r, 0, math.pi / 2)
            cr.arc(x0 + r, y1 - r, r, math.pi / 2, math.pi)
            cr.arc(x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2)
            cr.close_path()
            cr.set_source_rgb(*hex_to_rgb(c["bg"]))
            cr.fill_preserve()
            fr, fg_, fb = hex_to_rgb(c["fg"])
            cr.set_source_rgba(fr, fg_, fb, 0.09)
            cr.set_line_width(1)
            cr.stroke()
            return
        cr.set_source_rgb(*hex_to_rgb(c["bg"]))
        if self.kind == "top":
            hh = max(E, h * p)
            r = min(R, (hh) / 2)
            cr.move_to(0, 0)
            cr.line_to(w, 0)
            cr.arc_negative(w, E, E, -math.pi / 2, -math.pi)          # right ear
            cr.line_to(w - E, hh - r)
            cr.arc(w - E - r, hh - r, r, 0, math.pi / 2)
            cr.line_to(E + r, hh)
            cr.arc(E + r, hh - r, r, math.pi / 2, math.pi)
            cr.line_to(E, E)
            cr.arc_negative(0, E, E, 0, -math.pi / 2)                 # left ear
            cr.close_path()
        elif self.kind == "right":
            cr.move_to(0, 0)
            cr.line_to(w, 0)
            cr.line_to(w, h)
            cr.line_to(0, h)
            cr.line_to(0, h - T)
            cr.arc_negative(0, h - T - E, E, math.pi / 2, 0)          # ear into the bottom frame
            cr.line_to(E, E)
            cr.arc_negative(0, E, E, 0, -math.pi / 2)                 # ear into the menu bar
            cr.close_path()
        else:  # bottom
            top = h - max(E + T, h * p)
            r = min(R, (h - T - top) / 2) if h - T - top > 0 else 0
            cr.move_to(0, h)
            cr.line_to(0, h - T)
            cr.arc_negative(0, h - T - E, E, math.pi / 2, 0)
            cr.line_to(E, top + r)
            cr.arc(E + r, top + r, r, math.pi, 3 * math.pi / 2)
            cr.line_to(w - E - r, top)
            cr.arc(w - E - r, top + r, r, -math.pi / 2, 0)
            cr.line_to(w - E, h - T - E)
            cr.arc_negative(w, h - T - E, E, math.pi, math.pi / 2)
            cr.line_to(w, h)
            cr.close_path()
        cr.fill()


def click_through(win):
    """The window ignores the mouse: an empty input region (the frame, the desktop clock)."""
    import cairo

    def apply(*_):
        surf = win.get_surface()
        if surf:
            surf.set_input_region(cairo.Region())
    win.connect("realize", apply)
    if win.get_realized():
        apply()
