"""Nebula shell — "Now playing": the card (in the Control Center) and the pop-up player under the bar."""
import hashlib
import os
import threading
import time
import urllib.parse
import urllib.request

import gi

gi.require_version("Playerctl", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Gtk4LayerShell as LS, Playerctl  # noqa: E402

import common as C  # noqa: E402
from common import I, box, icon, label, tr  # noqa: E402


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def fmt(sec):
    sec = max(0, int(sec))
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


class SeekBar:
    """Track position slider that's gentle on the player.

    Dragging a Gtk.Scale fires change-value dozens of times a second. Passing
    every one of those to Spotify makes it re-buffer over and over, which is
    what made the audio stutter while scrubbing. So while the thumb moves we
    only update the time label, and send one seek once the hand stops.
    """

    SETTLE_MS = 250      # quiet time after the last movement before we seek
    HOLD_S = 1.0         # players report the old position for a moment after a seek

    def __init__(self, player):
        self.player = player                   # callable -> current Playerctl.Player or None
        self.scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, draw_value=False, hexpand=True)
        self.scale.add_css_class("thin")
        self.scale.set_range(0, 1)
        self.scale.connect("change-value", self.on_change)
        self.pos = label("0:00", "time")
        self.len = label("—", "time", xalign=1.0)
        self.target = None
        self.timer = None
        self.hold = 0.0

    def on_change(self, _s, _scroll, value):
        lo, hi = self.scale.get_adjustment().get_lower(), self.scale.get_adjustment().get_upper()
        self.target = max(lo, min(hi, value))
        self.pos.set_text(fmt(self.target))
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(self.SETTLE_MS, self.commit)
        return False

    def commit(self):
        self.timer = None
        p = self.player()
        if p is not None and self.target is not None:
            safe(lambda: p.set_position(int(self.target * 1_000_000)))
            self.hold = time.monotonic() + self.HOLD_S
        self.target = None
        return False

    def update(self, p):
        """Called by the ticker: mirror the player unless the user is mid-drag."""
        if self.target is not None or time.monotonic() < self.hold:
            return
        length = safe(lambda: int(p.print_metadata_prop("mpris:length") or 0), 0) / 1_000_000 if p else 0
        pos = safe(lambda: p.get_position(), 0) / 1_000_000 if p else 0
        if length > 0:
            self.scale.set_range(0, length)
            self.scale.set_value(min(pos, length))
            self.scale.set_sensitive(bool(safe(lambda: p.props.can_seek, True)))
            self.len.set_text(fmt(length))
        else:
            self.scale.set_range(0, 1)
            self.scale.set_value(0)
            self.scale.set_sensitive(False)
            self.len.set_text("—")
        self.pos.set_text(fmt(pos))


class Players:
    """One MPRIS manager for the whole shell; cards subscribe to its changes."""

    def __init__(self):
        self.manager = Playerctl.PlayerManager()
        self.manager.connect("name-appeared", lambda _m, n: self.add(n))
        self.manager.connect("player-vanished", lambda _m, p: self.vanish(p))
        self.players = {}
        self.current = None
        self.listeners = []
        for n in self.manager.props.player_names:
            self.add(n, notify=False)
        self.pick()

    def add(self, name, notify=True):
        if name.instance in self.players:
            return
        try:
            p = Playerctl.Player.new_from_name(name)
        except GLib.Error:
            return
        for sig in ("metadata", "playback-status", "shuffle", "loop-status", "seeked", "volume"):
            p.connect(sig, lambda *_: self.changed())
        self.manager.manage_player(p)
        self.players[name.instance] = p
        if self.current is None:
            self.current = name.instance
        if notify:
            self.changed()

    def vanish(self, player):
        for inst, p in list(self.players.items()):
            if p == player:
                del self.players[inst]
                if self.current == inst:
                    self.current = None
        self.pick()
        self.changed()

    def pick(self):
        playing = [i for i, p in self.players.items()
                   if safe(lambda p=p: p.props.playback_status) == Playerctl.PlaybackStatus.PLAYING]
        if playing and (self.current not in self.players or self.current not in playing):
            self.current = playing[0]
        elif self.current not in self.players:
            self.current = next(iter(self.players), None)

    @property
    def player(self):
        return self.players.get(self.current)

    def changed(self):
        self.pick()
        for fn in list(self.listeners):
            fn()

    def select_next(self):
        keys = list(self.players)
        if len(keys) > 1:
            i = keys.index(self.current) if self.current in keys else -1
            self.current = keys[(i + 1) % len(keys)]
            for fn in list(self.listeners):
                fn()


PLAYERS = None


def players():
    global PLAYERS
    if PLAYERS is None:
        PLAYERS = Players()
    return PLAYERS


class MediaCard(Gtk.Box):
    """big=False — the compact row in the Control Center; big=True — the pop-up player."""

    def __init__(self, big=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10 if big else 8)
        self.add_css_class("media")
        self.big = big
        self.art_url = ""      # not None: otherwise the first set_art(None) wouldn't show the placeholder
        self.art_tex = None
        self.updating = False
        self.pl = players()
        size = 92 if big else 46
        self.art = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        self.art.set_size_request(size, size)
        self.art.add_css_class("art")
        self.art.set_overflow(Gtk.Overflow.HIDDEN)
        self.noart = icon(I["music"], "noart")
        self.noart.set_size_request(size, size)
        self.artstack = Gtk.Stack()
        self.artstack.add_named(self.art, "art")
        self.artstack.add_named(self.noart, "none")
        self.artstack.set_valign(Gtk.Align.CENTER)

        self.title = label("", "title", max_chars=26)
        self.artist = label("", "artist", max_chars=30)
        self.chips = box("h", 4)
        info = box("v", 2, None, self.chips, self.title, self.artist, valign=Gtk.Align.CENTER, hexpand=True)

        self.b_prev = C.button(icon(I["prev"]), "ctl", lambda: self.act("previous"))
        self.b_play = C.button(icon(I["play"]), "ctl big" if big else "ctl", lambda: self.act("play_pause"))
        self.b_next = C.button(icon(I["next"]), "ctl", lambda: self.act("next"))
        ctl = box("h", 2, None, self.b_prev, self.b_play, self.b_next, valign=Gtk.Align.CENTER)

        if big:
            self.append(box("h", 14, None, self.artstack, info))
            self.bar = SeekBar(lambda: self.pl.player)
            self.seek, self.pos, self.len = self.bar.scale, self.bar.pos, self.bar.len
            self.append(self.seek)
            self.append(box("h", 0, None, self.pos, Gtk.Box(hexpand=True), self.len))
            ctl.set_halign(Gtk.Align.CENTER)
            self.b_shuffle = C.button(icon(I["shuffle"]), "ctl", self.toggle_shuffle)
            self.b_loop = C.button(icon("\U000f0456"), "ctl", self.cycle_loop)
            ctl.prepend(self.b_shuffle)
            ctl.append(self.b_loop)
            self.append(ctl)
            self.empty = label(tr("Сейчас ничего не играет"), "muted", xalign=0.5)
            self.append(self.empty)
        else:
            self.append(box("h", 12, None, self.artstack, info, ctl))
        self.pl.listeners.append(self.refresh)
        self.timer = None
        self.refresh(force=True)

    def start_ticks(self):
        if self.big and self.timer is None:
            self.timer = GLib.timeout_add(500, self.tick)

    def stop_ticks(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None

    def act(self, method):
        p = self.pl.player
        if p:
            safe(lambda: getattr(p, method)())

    def toggle_shuffle(self):
        p = self.pl.player
        if p:
            safe(lambda: p.set_shuffle(not p.props.shuffle))

    def cycle_loop(self):
        p = self.pl.player
        if not p:
            return
        order = [Playerctl.LoopStatus.NONE, Playerctl.LoopStatus.PLAYLIST, Playerctl.LoopStatus.TRACK]
        cur = safe(lambda: p.props.loop_status, Playerctl.LoopStatus.NONE)
        safe(lambda: p.set_loop_status(order[(order.index(cur) + 1) % 3] if cur in order else order[0]))

    def refresh(self, force=False):
        if not force and not self.get_mapped():
            return            # the Control Center is hidden — it'll refresh when shown
        p = self.pl.player
        has = p is not None
        self.set_visible(has or self.big)
        for w in (self.b_prev, self.b_play, self.b_next):
            w.set_visible(has)
        if self.big:
            for w in (self.seek, self.pos, self.len, self.b_shuffle, self.b_loop):
                w.set_visible(has)
            self.empty.set_visible(not has)
        C.clear(self.chips)
        if len(self.pl.players) > 1:
            for inst, pp in self.pl.players.items():
                name = (safe(lambda pp=pp: pp.props.player_name, inst) or inst).capitalize()
                b = C.button(name, "chip on" if inst == self.pl.current else "chip",
                             lambda i=inst: self.choose(i))
                self.chips.append(b)
        self.chips.set_visible(len(self.pl.players) > 1)
        self.artstack.get_parent().set_visible(has or not self.big)
        if not has:
            self.title.set_text(tr("Музыка"))
            self.artist.set_text("")
            self.set_art(None)
            return
        self.title.set_text(safe(p.get_title) or safe(lambda: p.props.player_name, "") or "—")
        self.artist.set_text(safe(p.get_artist) or safe(p.get_album) or "")
        playing = safe(lambda: p.props.playback_status) == Playerctl.PlaybackStatus.PLAYING
        self.b_play.get_child().set_text(I["pause"] if playing else I["play"])
        self.b_prev.set_sensitive(bool(safe(lambda: p.props.can_go_previous, True)))
        self.b_next.set_sensitive(bool(safe(lambda: p.props.can_go_next, True)))
        if self.big:
            C.set_class(self.b_shuffle, "on", bool(safe(lambda: p.props.shuffle, False)))
            loop = safe(lambda: p.props.loop_status, Playerctl.LoopStatus.NONE)
            self.b_loop.get_child().set_text({Playerctl.LoopStatus.TRACK: "\U000f0458",
                                              Playerctl.LoopStatus.PLAYLIST: "\U000f0456"}.get(loop, "\U000f0457"))
            self.tick()
        self.set_art(safe(lambda: p.print_metadata_prop("mpris:artUrl")) or None)

    def choose(self, inst):
        self.pl.current = inst
        for fn in list(self.pl.listeners):
            fn()

    def tick(self):
        p = self.pl.player
        if not p or not self.big:
            return self.timer is not None
        self.bar.update(p)
        return True

    def set_art(self, url):
        if url == self.art_url:
            return
        self.art_url = url
        if not url:
            self.artstack.set_visible_child_name("none")
            return
        threading.Thread(target=self.load_art, args=(url,), daemon=True).start()

    def load_art(self, url):
        path = None
        try:
            if url.startswith("file://"):
                path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
            elif url.startswith(("http://", "https://")):
                d = C.CACHE / "art"
                d.mkdir(parents=True, exist_ok=True)
                path = str(d / hashlib.md5(url.encode()).hexdigest())
                if not os.path.exists(path):
                    req = urllib.request.Request(url, headers={"User-Agent": "nebula-shell"})
                    with urllib.request.urlopen(req, timeout=6) as r, open(path + ".tmp", "wb") as f:
                        f.write(r.read())
                    os.replace(path + ".tmp", path)
            size = 184 if self.big else 92
            tex = C.texture_scaled(path, size, size) if path else None
        except Exception:
            tex = None

        def apply():
            if url == self.art_url:
                if tex:
                    self.art.set_paintable(tex)
                    self.artstack.set_visible_child_name("art")
                else:
                    self.artstack.set_visible_child_name("none")
            return False
        GLib.idle_add(apply)


def palette(pb):
    """The 2–3 main colors of a cover (r, g, b in 0…1): the "heaviest" hues by saturation."""
    import colorsys
    small = pb.scale_simple(20, 20, GdkPixbuf.InterpType.BILINEAR)
    data, n, stride = small.get_pixels(), small.get_n_channels(), small.get_rowstride()
    buckets, total = {}, [0.0, 0.0, 0.0, 0]
    for y in range(20):
        for x in range(20):
            i = y * stride + x * n
            r, g, b = data[i] / 255, data[i + 1] / 255, data[i + 2] / 255
            total[0] += r
            total[1] += g
            total[2] += b
            total[3] += 1
            h, sat, v = colorsys.rgb_to_hsv(r, g, b)
            w = sat * v * v
            if w < 0.04:
                continue
            k = int(h * 12) % 12
            acc = buckets.setdefault(k, [0.0, 0.0, 0.0, 0.0])
            acc[0] += r * w
            acc[1] += g * w
            acc[2] += b * w
            acc[3] += w
    avg = tuple(c / max(1, total[3]) for c in total[:3])
    top = sorted(buckets.values(), key=lambda a: -a[3])[:2]
    cols = [tuple(c / a[3] for c in a[:3]) for a in top]
    while len(cols) < 2:
        cols.append(avg)
    # a bit brighter and more saturated, so the background glows instead of looking muddy
    out = []
    for r, g, b in cols + [avg]:
        h, sat, v = colorsys.rgb_to_hsv(r, g, b)
        out.append(colorsys.hsv_to_rgb(h, min(1.0, sat * 1.15), max(0.35, min(0.95, v * 1.1))))
    return out


def fetch_art(url, size, callback):
    """A cover (file:// or http) → callback(url, pixbuf|None, palette|None) on the main thread."""
    def work():
        path, tex, pal = None, None, None
        try:
            if url.startswith("file://"):
                path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
            elif url.startswith(("http://", "https://")):
                d = C.CACHE / "art"
                d.mkdir(parents=True, exist_ok=True)
                path = str(d / hashlib.md5(url.encode()).hexdigest())
                if not os.path.exists(path):
                    req = urllib.request.Request(url, headers={"User-Agent": "nebula-shell"})
                    with urllib.request.urlopen(req, timeout=6) as r, open(path + ".tmp", "wb") as f:
                        f.write(r.read())
                    os.replace(path + ".tmp", path)
            if path:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
                s = max(size / pb.get_width(), size / pb.get_height())
                if s > 1.01:
                    pb = pb.scale_simple(round(pb.get_width() * s), round(pb.get_height() * s),
                                         GdkPixbuf.InterpType.BILINEAR)
                pal = palette(pb)
                w, h = pb.get_width(), pb.get_height()
                side = min(w, h)
                tex = pb.new_subpixbuf((w - side) // 2, (h - side) // 2, side, side).copy()
        except Exception:
            tex, pal = None, None
        GLib.idle_add(lambda: callback(url, tex, pal) or False)
    threading.Thread(target=work, daemon=True).start()


def _luma(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


class Ambient(Gtk.DrawingArea):
    """The player background: soft blobs in the cover's colors. Only redrawn when the track changes
    (a smooth ~0.7 s transition); the rest of the time it costs nothing."""

    def __init__(self):
        super().__init__(hexpand=True, vexpand=True)
        self.old, self.new, self.t = None, None, 1.0
        self.anim = None
        self.set_draw_func(self.draw)
        self.set_can_target(False)

    def set_palette(self, pal):
        if pal == self.new:
            return
        self.old, self.new = self.new, pal
        if self.anim:
            self.anim.cancel()
        if not self.get_mapped():
            self.t = 1.0
            self.queue_draw()
            return

        def step(v):
            self.t = v
            self.queue_draw()
        self.anim = C.Tween(self, 0.7, step, C.ease_out_cubic)

    def draw(self, _da, cr, w, h):
        import cairo
        import math
        r = 18
        cr.new_sub_path()
        cr.arc(w - r, r, r, -math.pi / 2, 0)
        cr.arc(w - r, h - r, r, 0, math.pi / 2)
        cr.arc(r, h - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.clip()
        for pal, a in ((self.old, 1 - self.t), (self.new, self.t)):
            if not pal or a <= 0.01:
                continue
            c1, c2, avg = pal
            cr.set_source_rgba(*avg, 0.16 * a)
            cr.paint()
            for (cx, cy, rad, col, alpha) in ((w * 0.12, h * 0.10, max(w, h) * 0.85, c1, 0.42),
                                             (w * 0.95, h * 0.95, max(w, h) * 0.75, c2, 0.34)):
                g = cairo.RadialGradient(cx, cy, 0, cx, cy, rad)
                g.add_color_stop_rgba(0, *col, alpha * a)
                g.add_color_stop_rgba(1, *col, 0)
                cr.set_source(g)
                cr.paint()


class CoverArt(Gtk.DrawingArea):
    """A fixed-size rounded cover; a track change crossfades the old one into the new."""

    def __init__(self, size, radius=14):
        super().__init__(content_width=size, content_height=size, halign=Gtk.Align.START,
                         valign=Gtk.Align.START)
        self.size, self.radius = size, radius
        self.old, self.new, self.t, self.anim = None, None, 1.0, None
        self.set_draw_func(self.draw)

    def set_pixbuf(self, pb):
        self.old, self.new = self.new, pb
        if self.anim:
            self.anim.cancel()
        if not self.get_mapped() or self.old is None:
            self.t = 1.0
            self.queue_draw()
            return

        def step(v):
            self.t = v
            self.queue_draw()
        self.anim = C.Tween(self, 0.42, step, C.ease_out_cubic)

    def draw(self, _da, cr, w, h):
        import math
        r = self.radius
        cr.new_sub_path()
        cr.arc(w - r, r, r, -math.pi / 2, 0)
        cr.arc(w - r, h - r, r, 0, math.pi / 2)
        cr.arc(r, h - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.clip()
        for pb, a in ((self.old, 1 - self.t), (self.new, self.t)):
            if pb is None or a <= 0.01:
                continue
            cr.save()
            k = max(w / pb.get_width(), h / pb.get_height())
            cr.scale(k, k)
            Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
            cr.get_source().set_filter(1)   # GOOD
            cr.paint_with_alpha(a)
            cr.restore()


class BigPlayer(Gtk.Overlay):
    """The big player under the menu bar: cover, a background in its colors, seeking, player volume,
    a link to the track and an "open player" button. While hidden it doesn't compute a thing."""

    ART = 132

    def __init__(self):
        super().__init__()
        self.add_css_class("bigplayer")
        self.pl = players()
        self.art_url = ""
        self.updating = False
        self.timer = None
        self.dirty = True
        self.tint = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.tint,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        self.ambient = Ambient()
        self.set_child(self.ambient)
        body = box("v", 10, "media bp-body")
        self.add_overlay(body)
        self.set_measure_overlay(body, True)

        # cover: on a track change the old one crossfades into the new
        self.cover = CoverArt(self.ART)
        self.cover.add_css_class("bp-art")
        self.artstack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=300,
                                  valign=Gtk.Align.START, halign=Gtk.Align.START)
        self.artstack.add_named(self.cover, "art")
        self.noart = icon(I["music"], "noart bp-art")
        self.noart.set_size_request(self.ART, self.ART)
        self.artstack.add_named(self.noart, "none")

        self.chips = box("h", 4)
        self.source = label("", "bp-source")
        self.title = label("", "bp-title", max_chars=20, wrap=True)
        self.title.set_lines(2)
        self.title.set_ellipsize(3)
        self.artist = label("", "bp-artist", max_chars=26)
        self.album = label("", "bp-album", max_chars=28)
        self.b_link = C.button(icon("\U000f0337"), "ctl small", self.copy_link, tr("Скопировать ссылку на трек"))
        self.b_open = C.button(icon("\U000f03cc"), "ctl small", self.open_app, tr("Открыть плеер"))
        tools = box("h", 2, None, self.b_link, self.b_open, halign=Gtk.Align.START)
        info = box("v", 2, None, self.chips, self.source, self.title, self.artist, self.album, Gtk.Box(vexpand=True),
                   tools, hexpand=True)
        self.head = box("h", 16, None, self.artstack, info)
        body.append(self.head)

        self.bar = SeekBar(lambda: self.pl.player)
        self.seek, self.pos, self.len = self.bar.scale, self.bar.pos, self.bar.len
        self.seekbox = box("v", 0, None, self.seek, box("h", 0, None, self.pos, Gtk.Box(hexpand=True), self.len))
        body.append(self.seekbox)

        self.b_shuffle = C.button(icon(I["shuffle"]), "ctl", self.toggle_shuffle, tr("Перемешать"))
        self.b_prev = C.button(icon(I["prev"]), "ctl", lambda: self.act("previous"))
        self.b_play = C.button(icon(I["play"]), "ctl big", lambda: self.act("play_pause"))
        self.b_next = C.button(icon(I["next"]), "ctl", lambda: self.act("next"))
        self.b_loop = C.button(icon("\U000f0456"), "ctl", self.cycle_loop, tr("Повтор"))
        self.ctl = box("h", 8, None, self.b_shuffle, self.b_prev, self.b_play, self.b_next, self.b_loop,
                       halign=Gtk.Align.CENTER)
        body.append(self.ctl)

        self.vol = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, draw_value=False, hexpand=True)
        self.vol.add_css_class("thin")
        self.vol.set_range(0, 1)
        self.vol.connect("change-value", self.on_volume)
        self.volrow = box("h", 8, "bp-vol", icon(I["vol_low"], "muted"), self.vol, icon(I["vol"], "muted"))
        body.append(self.volrow)

        self.empty = label(tr("Сейчас ничего не играет"), "muted bp-empty", xalign=0.5)
        body.append(self.empty)
        self.pl.listeners.append(self.refresh)

    # ── controls ───────────────────────────────────────────────────────────
    def act(self, method):
        p = self.pl.player
        if p:
            safe(lambda: getattr(p, method)())

    def toggle_shuffle(self):
        p = self.pl.player
        if p:
            safe(lambda: p.set_shuffle(not p.props.shuffle))

    def cycle_loop(self):
        p = self.pl.player
        if not p:
            return
        order = [Playerctl.LoopStatus.NONE, Playerctl.LoopStatus.PLAYLIST, Playerctl.LoopStatus.TRACK]
        cur = safe(lambda: p.props.loop_status, Playerctl.LoopStatus.NONE)
        safe(lambda: p.set_loop_status(order[(order.index(cur) + 1) % 3] if cur in order else order[0]))

    def on_volume(self, _s, _scroll, value):
        # Same story as seeking: batch the drag into a few calls instead of a flood
        if self.updating:
            return False
        first = getattr(self, "vol_target", None) is None
        self.vol_target = max(0.0, min(1.0, value))
        if first:
            GLib.timeout_add(80, self.push_volume)
        return False

    def push_volume(self):
        p, v = self.pl.player, self.vol_target
        self.vol_target = None
        if p and v is not None:
            safe(lambda: p.set_volume(v))
        return False

    def meta(self, key):
        p = self.pl.player
        return (safe(lambda: p.print_metadata_prop(key)) or "") if p else ""

    def copy_link(self):
        url = self.meta("xesam:url")
        if url.startswith("http"):
            C.copy_text(url)
            self.b_link.set_tooltip_text(tr("Ссылка скопирована"))

    def open_app(self):
        """Bring up the player's window (Spotify and such): look for it among niri's windows."""
        p = self.pl.player
        name = (safe(lambda: p.props.player_name, "") or "").lower() if p else ""
        if not name:
            return

        def done(ok, out):
            import json
            try:
                wins = json.loads(out) if ok else []
            except ValueError:
                wins = []
            w = next((w for w in wins if name in (w.get("app_id") or "").lower()), None)
            if w:
                C.run_async(["niri", "msg", "action", "focus-window", "--id", str(w["id"])])
                if self.get_root() and hasattr(self.get_root(), "nb_hide"):
                    self.get_root().nb_hide()
        C.run_async(["niri", "msg", "-j", "windows"], done)

    # ── display ────────────────────────────────────────────────────────────
    def refresh(self, force=False):
        if not force and not self.get_mapped():
            self.dirty = True     # hidden — catch up when shown
            return
        self.dirty = False
        p = self.pl.player
        has = p is not None
        for w in (self.head, self.seekbox, self.ctl):
            w.set_visible(has)
        self.empty.set_visible(not has)
        C.clear(self.chips)
        if len(self.pl.players) > 1:
            for inst, pp in self.pl.players.items():
                name = (safe(lambda pp=pp: pp.props.player_name, inst) or inst).capitalize()
                self.chips.append(C.button(name, "chip on" if inst == self.pl.current else "chip",
                                           lambda i=inst: self.choose(i)))
        self.chips.set_visible(len(self.pl.players) > 1)
        if not has:
            self.volrow.set_visible(False)
            self.set_art(None)
            return
        name = safe(lambda: p.props.player_name, "") or ""
        self.source.set_text({"spotify": "SPOTIFY"}.get(name, name.upper()))
        self.title.set_text(safe(p.get_title) or name or "—")
        self.artist.set_text(safe(p.get_artist) or "")
        album = safe(p.get_album) or ""
        self.album.set_text(album)
        self.album.set_visible(bool(album))
        playing = safe(lambda: p.props.playback_status) == Playerctl.PlaybackStatus.PLAYING
        self.b_play.get_child().set_text(I["pause"] if playing else I["play"])
        C.set_class(self, "paused", not playing)
        self.b_prev.set_sensitive(bool(safe(lambda: p.props.can_go_previous, True)))
        self.b_next.set_sensitive(bool(safe(lambda: p.props.can_go_next, True)))
        C.set_class(self.b_shuffle, "on", bool(safe(lambda: p.props.shuffle, False)))
        loop = safe(lambda: p.props.loop_status, Playerctl.LoopStatus.NONE)
        self.b_loop.get_child().set_text({Playerctl.LoopStatus.TRACK: "\U000f0458",
                                          Playerctl.LoopStatus.PLAYLIST: "\U000f0456"}.get(loop, "\U000f0457"))
        C.set_class(self.b_loop, "on", loop in (Playerctl.LoopStatus.TRACK, Playerctl.LoopStatus.PLAYLIST))
        vol = safe(lambda: p.props.volume)
        self.volrow.set_visible(vol is not None and vol >= 0)
        if vol is not None and getattr(self, "vol_target", None) is None:
            self.updating = True
            self.vol.set_value(vol)
            self.updating = False
        self.b_link.set_visible(self.meta("xesam:url").startswith("http"))
        self.b_link.set_tooltip_text(tr("Скопировать ссылку на трек"))
        self.set_art(self.meta("mpris:artUrl") or None)
        self.tick()

    def choose(self, inst):
        self.pl.current = inst
        for fn in list(self.pl.listeners):
            fn()

    def set_art(self, url):
        if url == self.art_url:
            return
        self.art_url = url
        if not url:
            self.artstack.set_visible_child_name("none")
            self.apply_palette(None)
            return
        scale = self.get_scale_factor() or 1

        def done(u, pb, pal):
            if u != self.art_url:
                return
            if pb:
                self.cover.set_pixbuf(pb)
                self.artstack.set_visible_child_name("art")
            else:
                self.artstack.set_visible_child_name("none")
            self.apply_palette(pal)
        fetch_art(url, self.ART * 2 * scale, done)

    def apply_palette(self, pal):
        self.ambient.set_palette(pal)
        if not pal:
            self.tint.load_from_string("")
            return
        c1 = pal[0]
        hexc = "#" + "".join(f"{round(v * 255):02x}" for v in c1)
        on = "#101010" if _luma(c1) > 0.55 else "#ffffff"
        self.tint.load_from_string(f"""
.bigplayer .ctl.big {{ background: {hexc}; color: {on}; }}
.bigplayer .ctl.big:hover {{ background: alpha({hexc}, 0.85); }}
.bigplayer .ctl.on {{ color: {hexc}; }}
.bigplayer scale.thin highlight {{ background: {hexc}; }}
.bigplayer .bp-source {{ color: {hexc}; }}
""")

    # ── time ───────────────────────────────────────────────────────────────
    def start_ticks(self):
        if self.timer is None:
            self.timer = GLib.timeout_add(1000, self.tick)

    def stop_ticks(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None

    def tick(self):
        p = self.pl.player
        if not p:
            return self.timer is not None
        self.bar.update(p)
        return True


class MediaPopup:
    """The player under the bar, opened by clicking the music in waybar."""

    def __init__(self, shell):
        self.shell = shell
        self.visible = False
        self.anim = None
        win = Gtk.Window(application=shell)
        LS.init_for_window(win)
        LS.set_namespace(win, "nebula-media")
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(win, LS.KeyboardMode.EXCLUSIVE)
        LS.set_anchor(win, LS.Edge.TOP, True)
        self.win = win
        self.card = BigPlayer()
        self.root = box("v", 0, "mediapop", self.card)
        self.root.set_size_request(460, -1)
        win.nb_hide = self.hide
        self.sheet = C.Sheet("top", self.root, lambda: shell.colors)
        win.set_child(self.sheet)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)

    def on_key(self, _c, keyval, _code, _state):
        k = Gdk.keyval_name(keyval)
        p = self.card.pl.player
        acts = {
            "Escape": self.hide, "q": self.hide,
            "space": lambda: self.card.act("play_pause"), "n": lambda: self.card.act("next"),
            "p": lambda: self.card.act("previous"), "Tab": self.card.pl.select_next,
            "Right": lambda: p and safe(lambda: p.seek(5_000_000)),
            "Left": lambda: p and safe(lambda: p.seek(-5_000_000)),
        }
        if k in acts:
            acts[k]()
            return True
        return False

    def toggle(self):
        self.hide() if self.visible else self.show()

    def show(self):
        self.shell.close_others(self)
        self.visible = True
        self.sheet.refresh()
        self.sheet.set_progress(0)
        self.root.set_opacity(0)
        self.card.refresh(force=True)
        self.card.start_ticks()
        self.shell.backdrop_show(self)
        self.win.present()
        if self.anim:
            self.anim.cancel()

        def frame(v):
            self.sheet.set_progress(v)
            self.root.set_opacity(max(0.0, (v - 0.35) / 0.65))
        self.anim = C.Tween(self.win, 0.30, frame, C.ease_out_quint)

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        self.card.stop_ticks()
        self.shell.backdrop_hide(self)
        if self.anim:
            self.anim.cancel()

        def frame(v):
            self.sheet.set_progress(1 - v)
            self.root.set_opacity(max(0.0, 1 - v * 2.5))
        self.anim = C.Tween(self.win, 0.20, frame, C.ease_in_cubic,
                            done=lambda: (not self.visible) and self.win.set_visible(False))

    def on_theme(self):
        self.sheet.da.queue_draw()
