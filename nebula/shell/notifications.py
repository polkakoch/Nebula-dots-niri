"""Nebula shell — our own notification server (org.freedesktop.Notifications).

Why not mako: mako draws every bubble on one shared surface, so niri blurs and
shadows the whole rectangle, gaps included — you'd get a slab of frosted glass
behind the stack. Here every notification is its own little layer window, sized
exactly to the card, so the blur and shadow hug each one.

If nb-shell isn't running, D-Bus activation simply starts mako instead.
"""
import html
import json
import re
import time

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Gtk4LayerShell as LS, Pango

import common as C
from common import I, box, icon, label, tr

WIDTH = 368
GAP = 10            # space between stacked cards
MAX_VISIBLE = 4
HISTORY_MAX = 60
HISTORY_FILE = C.STATE / "notifications.json"
DND_FILE = C.STATE / "dnd"

IFACE = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="GetCapabilities"><arg type="as" direction="out"/></method>
    <method name="Notify">
      <arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
      <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
      <arg type="a{sv}" direction="in"/><arg type="i" direction="in"/>
      <arg type="u" direction="out"/>
    </method>
    <method name="CloseNotification"><arg type="u" direction="in"/></method>
    <method name="GetServerInformation">
      <arg type="s" direction="out"/><arg type="s" direction="out"/>
      <arg type="s" direction="out"/><arg type="s" direction="out"/>
    </method>
    <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
    <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
    <signal name="ActivationToken"><arg type="u"/><arg type="s"/></signal>
  </interface>
</node>
"""

# reasons for NotificationClosed, straight from the spec
EXPIRED, DISMISSED, CLOSED_BY_CALL = 1, 2, 3


def dnd_on():
    return DND_FILE.exists()


def set_dnd(on):
    try:
        DND_FILE.touch() if on else DND_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    # keep mako in step too, in case it ever takes over as a fallback
    C.run_async(["makoctl", "mode", "-a" if on else "-r", "dnd"])


def plain(markup):
    """Body text for history and fallbacks: no tags, entities decoded."""
    return html.unescape(re.sub(r"<[^>]*>", "", markup or "")).strip()


def safe_markup(body):
    """Apps send 'body-markup' of varying quality. Keep what Pango understands, otherwise escape it all."""
    body = re.sub(r"<img[^>]*>", "", body or "")
    body = re.sub(r"<a\s+href=\"([^\"]*)\"[^>]*>", r'<a href="\1">', body)
    try:
        Pango.parse_markup(body, -1, "\0")
        return body
    except GLib.Error:
        return GLib.markup_escape_text(plain(body) or body)


def ago(ts):
    d = int(time.time() - ts)
    if d < 60:
        return tr("сейчас")
    if d < 3600:
        return tr("{n} мин").format(n=d // 60)
    if d < 86400:
        return tr("{n} ч").format(n=d // 3600)
    return time.strftime("%d.%m", time.localtime(ts))


def texture_from_image_data(v):
    """The spec's (iiibiiay) raw image: width, height, rowstride, alpha, bits, channels, bytes."""
    try:
        w, h, stride, alpha, bits, _ch, data = v
        pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(data)), GdkPixbuf.Colorspace.RGB,
                                             alpha, bits, w, h, stride)
        return Gdk.Texture.new_for_pixbuf(pb)
    except Exception:
        return None


def app_icon_for(n):
    """Best guess at the app's own icon: desktop entry first, then whatever it called itself."""
    entry = n.get("desktop_entry")
    if entry:
        try:
            info = Gio.DesktopAppInfo.new(entry if entry.endswith(".desktop") else entry + ".desktop")
            if info and info.get_icon():
                return info.get_icon()
        except TypeError:
            pass
    # notify-send -i puts an icon *name* into image-path; treat that as the app icon too
    for ic in (n.get("app_icon") or "", n.get("image_path") or ""):
        if ic and not ic.startswith(("/", "file://")):
            return Gio.ThemedIcon.new(ic)
    # last resort: an icon named after the app ("Spotify" -> spotify)
    name = (n.get("app_name") or "").lower().replace(" ", "-")
    disp = Gdk.Display.get_default()
    if name and disp and Gtk.IconTheme.get_for_display(disp).has_icon(name):
        return Gio.ThemedIcon.new(name)
    return None


def has_picture(n):
    """A real picture (album art, avatar, screenshot) rather than an icon name."""
    return bool(n.get("_texture")) or any((n.get(k) or "").startswith(("/", "file://"))
                                          for k in ("image_path", "app_icon"))


def image_widget(n, size):
    """Big picture on the left: an attached image, an icon file, or the app icon."""
    img = Gtk.Image()
    img.set_pixel_size(size)
    img.set_size_request(size, size)
    tex = n.get("_texture")
    if tex is None:
        path = next(p for p in (n.get("image_path") or "", n.get("app_icon") or "")
                    if p.startswith(("/", "file://")))
        tex = C.texture_scaled(path[7:] if path.startswith("file://") else path, size * 2, size * 2)
    if tex is None:
        return None
    img.set_from_paintable(tex)
    img.add_css_class("nimg")
    return img


class Toast:
    """One card on screen. Its window is exactly the card's size."""

    def __init__(self, server, n):
        self.server, self.n = server, n
        self.closing = False
        self.timer = None
        self.anim = None
        self.top = None            # current top margin (animated when the stack reflows)
        self.hovered = False

        win = Gtk.Window(application=server.shell)
        LS.init_for_window(win)
        LS.set_namespace(win, "notifications")       # niri rules give it blur, shadow and 16px corners
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        LS.set_exclusive_zone(win, 0)
        self.win = win
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.card.add_css_class("toast")
        self.card.set_size_request(WIDTH, -1)
        win.set_child(self.card)
        self.fill()

        click = Gtk.GestureClick()
        click.set_button(0)
        click.connect("released", self.on_click)
        self.card.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self.hover(True))
        motion.connect("leave", lambda *_: self.hover(False))
        self.card.add_controller(motion)

    # ── content ────────────────────────────────────────────────────────────
    def fill(self):
        n = self.n
        C.clear(self.card)
        for cls in ("critical", "low"):
            C.set_class(self.card, cls, n["urgency"] == {"critical": 2, "low": 0}[cls])

        # header: little app icon · app name · time (a close button takes its place on hover)
        head = box("h", 6, "thead")
        gicon = app_icon_for(n)
        if gicon is not None:
            ai = Gtk.Image.new_from_gicon(gicon)
            ai.set_pixel_size(16)
            head.append(ai)
        head.append(label(n["app_name"] or tr("Уведомление"), "tapp", hexpand=True))
        self.when = label(ago(n["time"]), "twhen")
        close = C.button(icon(I["close"]), "tclose", lambda: self.server.close(n["id"], DISMISSED),
                         tr("Закрыть"))
        self.corner = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        self.corner.add_named(self.when, "when")
        self.corner.add_named(close, "close")
        head.append(self.corner)
        self.card.append(head)

        # body: picture on the left, title and text on the right
        text = box("v", 2, None, hexpand=True, valign=Gtk.Align.CENTER)
        title = label(n["summary"], "ttitle", wrap=True)
        title.set_lines(2)
        title.set_ellipsize(3)
        text.append(title)
        if n["body"]:
            body = Gtk.Label(xalign=0.0, wrap=True, use_markup=True)
            body.set_wrap_mode(2)
            body.set_lines(4)
            body.set_ellipsize(3)
            body.set_max_width_chars(36)
            body.set_markup(safe_markup(n["body"]))
            body.add_css_class("tbody")
            body.connect("activate-link", lambda _l, uri: (C.spawn(["xdg-open", uri]), True)[1])
            text.append(body)
        if n.get("value") is not None:
            bar = Gtk.ProgressBar(fraction=max(0, min(100, n["value"])) / 100)
            bar.add_css_class("tprogress")
            text.append(bar)
        img = image_widget(n, 44) if has_picture(n) else None
        self.card.append(box("h", 12, "tmain", img, text))

        acts = [(k, v) for k, v in n["actions"] if k != "default"][:3]
        if acts:
            row = box("h", 6, "tactions", homogeneous=True)
            for key, name in acts:
                row.append(C.button(name or key, "taction", lambda k=key: self.server.invoke(n["id"], k)))
            self.card.append(row)

    def update(self, n):
        self.n = n
        self.fill()
        self.arm()
        self.server.layout()

    # ── behaviour ──────────────────────────────────────────────────────────
    def arm(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        ms = self.server.timeout_for(self.n)
        if ms > 0 and not self.hovered:
            self.timer = GLib.timeout_add(ms, self.expire)

    def expire(self):
        self.timer = None
        self.server.close(self.n["id"], EXPIRED)
        return False

    def hover(self, on):
        self.hovered = on
        self.corner.set_visible_child_name("close" if on else "when")
        if on:
            if self.timer:
                GLib.source_remove(self.timer)
                self.timer = None
        else:
            self.arm()

    def on_click(self, gesture, _n, _x, _y):
        btn = gesture.get_current_button()
        if btn == 3:                                   # right click: clear the whole stack
            self.server.dismiss_all()
        elif btn == 1 and any(k == "default" for k, _ in self.n["actions"]):
            self.server.invoke(self.n["id"], "default")
        else:
            self.server.close(self.n["id"], DISMISSED)

    def height(self):
        _m, nat, _b, _b2 = self.card.measure(Gtk.Orientation.VERTICAL, WIDTH)
        return nat

    # ── motion ─────────────────────────────────────────────────────────────
    def edge(self):
        return LS.Edge.LEFT if self.server.pos.endswith("left") else LS.Edge.RIGHT

    def show(self, top):
        """Slide in from the screen edge and fade up."""
        self.top = top
        side = self.server.side_margin()
        LS.set_anchor(self.win, LS.Edge.TOP, True)
        LS.set_anchor(self.win, self.edge(), True)
        LS.set_margin(self.win, LS.Edge.TOP, top)
        LS.set_margin(self.win, self.edge(), -WIDTH)
        self.win.set_opacity(0)
        self.win.present()

        def step(v):
            LS.set_margin(self.win, self.edge(), int(-WIDTH + (side + WIDTH) * v))
            self.win.set_opacity(min(1.0, v * 1.6))
        self.anim = C.Tween(self.win, 0.34 * self.server.anim_scale(), step, ease=C.ease_out_quint)
        self.arm()

    def move_to(self, top):
        if self.top == top or self.closing:
            return
        start = self.top
        self.top = top

        def step(v):
            LS.set_margin(self.win, LS.Edge.TOP, int(start + (top - start) * v))
        C.Tween(self.win, 0.24 * self.server.anim_scale(), step, ease=C.ease_out_cubic)

    def hide(self, done):
        """Slip back out towards the edge and fade."""
        self.closing = True
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        if self.anim:
            self.anim.cancel()
        side = self.server.side_margin()

        def step(v):
            LS.set_margin(self.win, self.edge(), int(side - (side + WIDTH * 0.6) * v))
            self.win.set_opacity(max(0.0, 1 - v * 1.4))

        def fin():
            self.win.destroy()
            done()
        C.Tween(self.win, 0.22 * self.server.anim_scale(), step, ease=C.ease_in_cubic, done=fin)


class Notifications:
    def __init__(self, shell):
        self.shell = shell
        self.toasts = {}            # id -> Toast, newest last
        self.history = self.load_history()
        self.next_id = max([n.get("id", 0) for n in self.history] + [0]) + 1
        self.listeners = []         # called whenever history or DND changes (the control center)
        self.conn = None
        self.pos = C.settings().get("NOTIF_POS", "top-right")
        self.owner = None
        if C.settings().get("NOTIFY", "1") != "1":
            return                  # the user prefers their own notification daemon
        self.owner = Gio.bus_own_name(Gio.BusType.SESSION, "org.freedesktop.Notifications",
                                      Gio.BusNameOwnerFlags.REPLACE, self.on_bus, self.on_acquired, self.on_lost)
        self.ticker = GLib.timeout_add_seconds(30, self.refresh_times)

    # ── D-Bus plumbing ─────────────────────────────────────────────────────
    def on_bus(self, conn, _name):
        self.conn = conn
        info = Gio.DBusNodeInfo.new_for_xml(IFACE).interfaces[0]
        conn.register_object("/org/freedesktop/Notifications", info, self.on_call, None, None)

    def on_acquired(self, *_):
        print("nebula: notification server is up", flush=True)

    def on_lost(self, *_):
        # Someone else (most likely mako) holds the name. Ask it to leave; we're queued
        # and D-Bus hands the name over the moment it exits.
        C.run_async(["pkill", "-x", "mako"])

    def on_call(self, _conn, _sender, _path, _iface, method, params, inv):
        if method == "GetCapabilities":
            inv.return_value(GLib.Variant("(as)", (["body", "body-markup", "body-hyperlinks", "actions",
                                                    "icon-static", "persistence", "x-nebula"],)))
        elif method == "GetServerInformation":
            inv.return_value(GLib.Variant("(ssss)", ("Nebula", "Nebula", "1.0", "1.2")))
        elif method == "Notify":
            inv.return_value(GLib.Variant("(u)", (self.notify(*params.unpack()),)))
        elif method == "CloseNotification":
            self.close(params.unpack()[0], CLOSED_BY_CALL)
            inv.return_value(None)

    def emit(self, signal, fmt, args):
        if self.conn:
            try:
                self.conn.emit_signal(None, "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                                      signal, GLib.Variant(fmt, args))
            except GLib.Error:
                pass

    # ── incoming ───────────────────────────────────────────────────────────
    def notify(self, app_name, replaces_id, app_icon, summary, body, actions, hints, timeout):
        # "synchronous" notifications (volume, brightness…) replace their previous self
        sync = hints.get("x-canonical-private-synchronous") or hints.get("synchronous")
        if sync and not replaces_id:
            for t in self.toasts.values():
                if t.n.get("sync") == sync:
                    replaces_id = t.n["id"]
        nid = replaces_id if replaces_id else self.next_id
        if not replaces_id:
            self.next_id += 1
        urgency = hints.get("urgency", 1)
        urgency = urgency[0] if isinstance(urgency, (bytes, bytearray)) else int(urgency)
        tex = None
        for key in ("image-data", "image_data", "icon_data"):
            if key in hints:
                tex = texture_from_image_data(hints[key])
                break
        n = {
            "id": nid, "app_name": app_name, "app_icon": app_icon, "summary": summary, "body": body,
            "actions": list(zip(actions[::2], actions[1::2])), "urgency": urgency, "time": time.time(),
            "timeout": timeout, "desktop_entry": hints.get("desktop-entry", ""), "sync": sync,
            "image_path": hints.get("image-path") or hints.get("image_path") or "",
            "value": hints.get("value"), "_texture": tex,
            "transient": bool(hints.get("transient")), "resident": bool(hints.get("resident")),
        }
        if not n["transient"]:
            self.remember(n)
        if dnd_on() and urgency < 2:
            return nid                       # quietly into history, nothing on screen
        if nid in self.toasts and not self.toasts[nid].closing:
            self.toasts[nid].update(n)
        else:
            self.pop(n)
            self.chime(n, hints)
        return nid

    def chime(self, n, hints):
        """A soft sound for new cards, if NOTIF_SOUND=1. Apps can ask for silence or their own sound."""
        if C.settings().get("NOTIF_SOUND", "0") != "1" or hints.get("suppress-sound"):
            return
        name = hints.get("sound-name") or ("dialog-warning" if n["urgency"] >= 2 else "message-new-instant")
        path = hints.get("sound-file") or f"/usr/share/sounds/freedesktop/stereo/{name}.oga"
        C.run_async(["pw-play", "--volume", "0.6", path])

    def timeout_for(self, n):
        if n["urgency"] >= 2:
            return 0 if n["timeout"] == 0 else 12000      # urgent stuff waits a bit longer
        try:
            base = int(float(C.settings().get("NOTIF_TIMEOUT") or 5) * 1000)
        except ValueError:
            base = 5000
        return base if base > 0 else 0

    def pop(self, n):
        t = Toast(self, n)
        self.toasts[n["id"]] = t
        live = [x for x in self.toasts.values() if not x.closing]
        for old in live[:-MAX_VISIBLE]:
            self.close(old.n["id"], DISMISSED, quiet=True)
        t.show(self.base_top())
        self.layout()

    # ── closing ────────────────────────────────────────────────────────────
    def close(self, nid, reason, quiet=False):
        t = self.toasts.get(nid)
        if t is None or t.closing:
            if not quiet and t is None:
                self.emit("NotificationClosed", "(uu)", (nid, reason))
            return
        self.emit("NotificationClosed", "(uu)", (nid, reason))
        t.hide(lambda: self.gone(nid, t))
        self.layout()

    def gone(self, nid, t):
        if self.toasts.get(nid) is t:
            del self.toasts[nid]

    def invoke(self, nid, key):
        self.emit("ActionInvoked", "(us)", (nid, key))
        t = self.toasts.get(nid)
        if t is None or not t.n.get("resident"):
            self.close(nid, DISMISSED)

    def dismiss_all(self):
        for nid in list(self.toasts):
            self.close(nid, DISMISSED)

    # ── layout ─────────────────────────────────────────────────────────────
    def anim_scale(self):
        s = C.settings()
        if s.get("ANIM_ENABLED") == "0":
            return 0.01
        try:
            return 1 / max(0.25, float(s.get("ANIM_SPEED") or 1))
        except ValueError:
            return 1

    def base_top(self):
        return 10 if C.bar_style() == "frame" else 8

    def side_margin(self):
        return C.frame_size() + 10 if C.bar_style() == "frame" else 12

    def layout(self):
        """Newest on top; everyone else slides down to make room."""
        top = self.base_top()
        for t in reversed([x for x in self.toasts.values() if not x.closing]):
            if t.top is None:
                t.show(top)
            else:
                t.move_to(top)
            top += t.height() + GAP

    def refresh_times(self):
        for t in self.toasts.values():
            t.when.set_text(ago(t.n["time"]))
        return True

    def apply_settings(self):
        pos = C.settings().get("NOTIF_POS", "top-right")
        if pos != self.pos:
            self.dismiss_all()
            self.pos = pos

    # ── history ────────────────────────────────────────────────────────────
    def load_history(self):
        try:
            data = json.loads(HISTORY_FILE.read_text())
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def save_history(self):
        try:
            HISTORY_FILE.write_text(json.dumps(self.history[:HISTORY_MAX], ensure_ascii=False))
        except OSError:
            pass
        C.spawn(["pkill", "-RTMIN+8", "-x", "waybar"])     # the bell/count in the bar
        for fn in list(self.listeners):
            fn()

    def remember(self, n):
        keep = {k: n[k] for k in ("id", "app_name", "app_icon", "summary", "desktop_entry", "urgency", "time")}
        keep["body"] = plain(n["body"])
        keep["image_path"] = n["image_path"]
        self.history = [h for h in self.history if h.get("id") != n["id"]]
        self.history.insert(0, keep)
        del self.history[HISTORY_MAX:]
        self.save_history()

    def forget(self, nid):
        self.history = [h for h in self.history if h.get("id") != nid]
        self.save_history()

    def clear_history(self):
        self.history = []
        self.dismiss_all()
        self.save_history()

    def restore(self):
        """Bring back the most recent one (Super+Ctrl+N)."""
        if self.history:
            h = dict(self.history[0])
            h.update(actions=[], timeout=-1, value=None, _texture=None, sync=None, resident=False, transient=True)
            if h["id"] not in self.toasts:
                self.pop(h)

    def set_dnd(self, on):
        set_dnd(on)
        if on:
            for nid, t in list(self.toasts.items()):
                if t.n["urgency"] < 2:
                    self.close(nid, DISMISSED)
        C.spawn(["pkill", "-RTMIN+8", "-x", "waybar"])
        for fn in list(self.listeners):
            fn()

    # ── FIFO: notify dismiss | clear | restore | dnd on|off|toggle | test ──
    def command(self, arg):
        if arg == "dismiss":
            self.dismiss_all()
        elif arg == "clear":
            self.clear_history()
        elif arg == "restore":
            self.restore()
        elif arg and arg.startswith("dnd"):
            want = arg.split(":", 1)[1] if ":" in arg else "toggle"
            self.set_dnd(not dnd_on() if want == "toggle" else want == "on")
        elif arg == "test":
            self.demo()

    def demo(self):
        """A few sample cards, handy for checking the look after a theme change."""
        samples = [
            ("Firefox", "firefox", tr("Загрузка завершена"), tr("Файл <b>nebula-1.0.0.zip</b> сохранён в «Загрузки»"),
             ["default", tr("Открыть"), "folder", tr("Показать в папке")], {"desktop-entry": "firefox"}),
            ("Telegram", "telegram", "Alex", tr("Скинь потом ссылку на конфиг, хочу тоже такой"), [], {}),
            ("Nebula", "battery-caution", tr("Батарея почти села"), tr("Осталось 9% — подключите зарядку"), [],
             {"urgency": 2}),
        ]
        for i, (app, ic, sm, body, acts, hints) in enumerate(samples):
            GLib.timeout_add(250 * i, lambda a=app, c=ic, s=sm, b=body, x=acts, h=hints:
                             self.notify(a, 0, c, s, b, x, h, -1) and False)
