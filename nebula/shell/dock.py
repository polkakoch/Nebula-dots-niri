"""Nebula shell — the Dock at the bottom: pinned and running apps, auto-hide.

Windows come from niri's event stream (niri msg -j event-stream), no polling.
When hidden, the Dock slides down until only a strip as tall as the bottom frame (and the same
color) is left on screen — that strip is also the hot zone: move the mouse to the bottom and the Dock comes up.

Pinned apps (DOCK_APPS in settings.conf) live in memory and are saved in the background:
  right-click — a menu (windows, new window, pin/unpin, close),
  drag — reorder; a pinned icon dragged out of the Dock gets unpinned;
  a running icon dragged over to the pinned ones gets pinned.
"""
import json
import time

from gi.repository import Gdk, Gio, GLib, Gtk, Gtk4LayerShell as LS

import common as C
from common import box, label, tr

ICON = 44


class NiriState:
    """niri's windows and workspaces, kept up to date from events."""

    def __init__(self):
        self.windows, self.workspaces, self.focused = {}, {}, None
        self.listeners = []
        self.start()

    def start(self):
        try:
            self.proc = Gio.Subprocess.new(["niri", "msg", "-j", "event-stream"],
                                           Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            return
        self.stream = Gio.DataInputStream.new(self.proc.get_stdout_pipe())
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.on_line)

    def on_line(self, stream, res):
        try:
            line, _len = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:   # niri restarted — reconnect
            GLib.timeout_add_seconds(2, lambda: self.start() or False)
            return
        try:
            self.handle(json.loads(line))
        except (ValueError, KeyError, TypeError):
            pass
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.on_line)

    def handle(self, ev):
        changed = True
        if "WindowsChanged" in ev:
            self.windows = {w["id"]: w for w in ev["WindowsChanged"]["windows"]}
        elif "WindowOpenedOrChanged" in ev:
            w = ev["WindowOpenedOrChanged"]["window"]
            self.windows[w["id"]] = w
            if w.get("is_focused"):
                self.focused = w["id"]
        elif "WindowClosed" in ev:
            self.windows.pop(ev["WindowClosed"]["id"], None)
        elif "WindowFocusChanged" in ev:
            self.focused = ev["WindowFocusChanged"]["id"]
        elif "WorkspacesChanged" in ev:
            self.workspaces = {w["id"]: w for w in ev["WorkspacesChanged"]["workspaces"]}
        elif "WorkspaceActivated" in ev:
            wid = ev["WorkspaceActivated"]["id"]
            out = self.workspaces.get(wid, {}).get("output")
            for w in self.workspaces.values():
                if w.get("output") == out:
                    w["is_active"] = w["id"] == wid
                if ev["WorkspaceActivated"].get("focused"):
                    w["is_focused"] = w["id"] == wid
        else:
            changed = False
        if changed:
            for fn in list(self.listeners):
                fn()

    def focused_workspace_empty(self):
        ws = next((w for w in self.workspaces.values() if w.get("is_focused")), None)
        if not ws:
            return False
        return not any(w.get("workspace_id") == ws["id"] for w in self.windows.values())


GENERIC_EXE = {"env", "sh", "bash", "flatpak", "snap", "python", "python3", "java", "electron", "gtk-launch",
               "wine", "apprun", "run", "start"}
DEFAULT_PINS = ("org.kde.dolphin.desktop", "kitty.desktop", "firefox.desktop")
MIME = "application/x-nebula-dock"   # our own type, so a dragged icon can't be dropped as text into another app
LAUNCH_TIMEOUT = 8                    # how many seconds an icon bounces if the window never shows up


class Dock:
    def __init__(self, shell):
        self.shell = shell
        self.visible = False   # for close_others: the Dock isn't a "modal" window
        self.shown = False
        self.hovered = False
        self.anim = None
        self.hide_timer = None
        self.mode = "autohide"
        self.pins = []
        self.pin_listeners = []    # the Control Center and Search hear about changes
        self.saving = 0
        self.launching = {}        # app.id → (time, window count at launch)
        self.menu = None
        self.drag = None
        self.deferred = False      # rebuilding waits while a menu is open or a drag is going on
        self.niri = NiriState()
        self.niri.listeners.append(self.on_niri)

        win = Gtk.Window(application=shell)
        LS.init_for_window(win)
        LS.set_namespace(win, "nebula-dock")
        LS.set_layer(win, LS.Layer.TOP)
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        LS.set_exclusive_zone(win, -1)
        LS.set_anchor(win, LS.Edge.BOTTOM, True)
        win.add_css_class("backdrop")
        self.row = box("h", 4, "dockrow")
        self.body = box("v", 0, "dock", self.row)
        self.sheet = C.Sheet("bottom", self.body, lambda: shell.colors)
        win.set_child(self.sheet)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self.on_hover(True))
        motion.connect("leave", lambda *_: self.on_hover(False))
        win.add_controller(motion)
        drop = Gtk.DropTargetAsync.new(Gdk.ContentFormats.new([MIME]), Gdk.DragAction.MOVE)
        drop.connect("accept", lambda _t, _d: self.drag is not None)
        drop.connect("drag-enter", self.on_drag_enter)
        drop.connect("drag-motion", self.on_drag_motion)
        drop.connect("drag-leave", self.on_drag_leave)
        drop.connect("drop", self.on_drop)
        self.sheet.add_controller(drop)   # the whole Dock sheet, ears included
        self.win = win
        self.rebuild_pending = None
        self.apply()

    # ── mode and position ──────────────────────────────────────────────────
    def apply(self):
        self.mode = C.settings().get("DOCK", "autohide")
        if not self.saving:   # until our own save reaches the file, memory has the fresher copy
            self.load_pins()
        self.sheet.refresh()
        if self.mode == "off":
            self.win.set_visible(False)
            return
        self.refresh()
        self.win.present()
        GLib.idle_add(lambda: self.place(self.mode == "always" or self.should_show(), animate=False) or False)

    def height(self):
        _m, nat, _b, _b2 = self.sheet.measure(Gtk.Orientation.VERTICAL, -1)
        return nat

    def hidden_margin(self):
        return -(self.height() - max(2, C.frame_size()))

    def place(self, show, animate=True):
        self.shown = show
        target = 0 if show else self.hidden_margin()
        if self.anim:
            self.anim.cancel()
        if not animate:
            LS.set_margin(self.win, LS.Edge.BOTTOM, target)
            return
        start = LS.get_margin(self.win, LS.Edge.BOTTOM)
        self.anim = C.Tween(self.win, 0.32 if show else 0.24,
                            lambda v: LS.set_margin(self.win, LS.Edge.BOTTOM, int(start + (target - start) * v)),
                            C.ease_out_quint if show else C.ease_in_cubic)

    def should_show(self):
        return bool(self.hovered or self.menu or self.drag or self.niri.focused_workspace_empty())

    def on_hover(self, inside):
        self.hovered = inside
        if self.mode != "autohide":
            return
        if inside:
            self.cancel_hide()
            if not self.shown:
                self.place(True)
        else:
            self.schedule_hide()

    def cancel_hide(self):
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
            self.hide_timer = None

    def schedule_hide(self, delay=450):
        self.cancel_hide()

        def later():
            self.hide_timer = None
            if self.mode == "autohide" and self.shown and not self.should_show():
                self.place(False)
            return False
        self.hide_timer = GLib.timeout_add(delay, later)

    def on_niri(self):
        if self.rebuild_pending:
            return

        def go():
            self.rebuild_pending = None
            self.rebuild()
            if self.mode == "autohide" and not self.hovered:
                want = self.should_show()
                if want != self.shown:
                    self.place(want)
            return False
        self.rebuild_pending = GLib.timeout_add(120, go)

    # ── pinned apps ────────────────────────────────────────────────────────
    def load_pins(self):
        raw = C.settings().get("DOCK_APPS", "").strip()
        if raw in ("", "auto"):   # first run: pick by launch frequency and save right away,
            self.pins = self.auto_pins()   # so the icons don't shuffle around on their own later
            self.save_pins()
        elif raw == "none":
            self.pins = []
        else:
            self.pins = list(dict.fromkeys(raw.split()))

    def auto_pins(self):
        idx = self.shell.apps
        known = {a.id for a in idx.apps}
        top = sorted(idx.usage.items(), key=lambda kv: -kv[1])
        ids = [k for k, _ in top if k in known][:5]
        for fallback in DEFAULT_PINS:
            if len(ids) >= 3:
                break
            if fallback not in ids and fallback in known:
                ids.append(fallback)
        return ids

    def save_pins(self):
        self.saving += 1

        def done(*_):
            self.saving -= 1
        C.set_setting("DOCK_APPS", " ".join(self.pins) or "none", done)

    def set_pins(self, pins):
        pins = list(dict.fromkeys(pins))
        if pins == self.pins:
            return
        self.pins = pins
        self.save_pins()
        self.refresh()
        for fn in list(self.pin_listeners):
            fn()

    def is_pinned(self, app_id):
        return app_id in self.pins

    def pin(self, app_id, index=None):
        pins = [p for p in self.pins if p != app_id]
        pins.insert(len(pins) if index is None else index, app_id)
        self.set_pins(pins)

    def unpin(self, app_id):
        self.set_pins([p for p in self.pins if p != app_id])

    def toggle_pin(self, app_id):
        """→ True if it's pinned now."""
        if self.is_pinned(app_id):
            self.unpin(app_id)
            return False
        self.pin(app_id)
        return True

    def move_pin(self, app_id, delta):
        pins = list(self.pins)
        if app_id not in pins:
            return
        i = pins.index(app_id)
        j = max(0, min(len(pins) - 1, i + delta))
        pins.insert(j, pins.pop(i))
        self.set_pins(pins)

    def reset_pins(self):
        self.set_pins(self.auto_pins())

    # ── windows → apps ─────────────────────────────────────────────────────
    def wm_map(self):
        idx = self.shell.apps
        if getattr(self, "_map_src", None) is not idx.apps:
            m = {}
            for a in idx.apps:
                base = a.id[:-8] if a.id.endswith(".desktop") else a.id
                keys = [a.info.get_startup_wm_class() or "", base]
                if a.exe and a.exe.lower() not in GENERIC_EXE:   # "env LD_PRELOAD=… spotify" is not "env"
                    keys.append(a.exe)
                for k in keys:
                    k = k.lower()
                    for kk in dict.fromkeys((k, k.split(".")[-1])):
                        if kk:
                            m.setdefault(kk, []).append(a)
            self._map, self._map_src = m, idx.apps
        return self._map

    def app_for_window(self, w):
        aid = (w.get("app_id") or "").lower()
        if not aid:
            return None
        m = self.wm_map()
        cands = m.get(aid) or m.get(aid.split(".")[-1]) or []
        # several .desktop files for one window (say, a client and its fork) — prefer the pinned one
        return next((a for a in cands if a.id in self.pins), cands[0] if cands else None)

    # ── icons ──────────────────────────────────────────────────────────────
    def refresh(self):
        self._sig = None
        self.rebuild()

    def rebuild(self):
        if self.menu or self.drag:   # don't yank an icon out from under a menu or a finger
            self.deferred = True
            return
        self.deferred = False
        idx = self.shell.apps
        by_id = {a.id: a for a in idx.apps}
        running = {}   # app.id → [windows]
        orphans = []   # windows without a .desktop file
        for w in sorted(self.niri.windows.values(), key=lambda w: w["id"]):
            a = self.app_for_window(w)
            if a:
                running.setdefault(a.id, []).append(w)
            else:
                orphans.append(w)
        now = time.monotonic()
        for aid, (t, n) in list(self.launching.items()):
            if len(running.get(aid, [])) > n or now - t > LAUNCH_TIMEOUT:
                del self.launching[aid]
        pinned = [p for p in self.pins if p in by_id]
        sig = (tuple(pinned), tuple((k, len(v)) for k, v in sorted(running.items())),
               self.niri.focused, tuple(o["app_id"] for o in orphans), tuple(sorted(self.launching)))
        if getattr(self, "_sig", None) == sig:
            return
        self._sig = sig
        C.clear(self.row)
        self.row.append(self.item(None, I_LAUNCH, tr("Приложения"), [], "launcher"))
        for pid in pinned:
            self.row.append(self.item(by_id[pid], None, by_id[pid].name, running.get(pid, []), "pinned"))
        extra = [aid for aid in running if aid not in pinned]
        if extra or orphans:
            sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
            sep.add_css_class("docksep")
            sep.zone = "sep"
            self.row.append(sep)
        for aid in extra:
            self.row.append(self.item(by_id[aid], None, by_id[aid].name, running[aid], "running"))
        for w in orphans:
            self.row.append(self.item(None, "application-x-executable", w.get("title") or w.get("app_id"), [w],
                                      "orphan"))
        if not self.shown:
            GLib.idle_add(lambda: (not self.shown) and LS.set_margin(self.win, LS.Edge.BOTTOM, self.hidden_margin()) and False)

    def item(self, app, icon_name, title, wins, zone):
        img = Gtk.Image(pixel_size=ICON)
        img.add_css_class("dockicon")
        if app is not None and app.gicon is not None:
            img.set_from_gicon(app.gicon)
        else:
            img.set_from_icon_name(icon_name or "application-x-executable")
        dot = Gtk.Box(halign=Gtk.Align.CENTER)
        dot.add_css_class("dockdot")
        focused = any(w["id"] == self.niri.focused for w in wins)
        C.set_class(dot, "on", bool(wins))
        C.set_class(dot, "focused", focused)
        b = Gtk.Button()
        b.set_child(box("v", 3, None, img, dot))
        b.add_css_class("dockitem")
        C.set_class(b, "launching", app is not None and app.id in self.launching)
        b.set_can_focus(False)
        b.set_tooltip_text(title)
        b.zone, b.app, b.app_id = zone, app, app.id if app else None
        b.connect("clicked", lambda *_: self.activate(app, wins, zone))
        g = Gtk.GestureClick(button=3)
        g.connect("pressed", lambda *_: self.open_menu(b, app, wins, zone))
        b.add_controller(g)
        m = Gtk.GestureClick(button=2)
        m.connect("pressed", lambda *_: app and self.launch(app, len(wins)))
        b.add_controller(m)
        if app is not None and zone in ("pinned", "running"):
            self.add_drag(b, img)
        return b

    def activate(self, app, wins, zone):
        if zone == "launcher":
            self.shell.launcher.toggle("apps")
            return
        if wins:
            ids = [w["id"] for w in wins]
            if self.niri.focused in ids and len(ids) > 1:
                nxt = ids[(ids.index(self.niri.focused) + 1) % len(ids)]
            else:
                nxt = ids[0]
            self.focus(nxt)
        elif app is not None:
            self.launch(app, 0)

    def launch(self, app, nwins):
        """Launch with a bouncing icon; extra clicks before the window appears don't spawn copies."""
        t = self.launching.get(app.id)
        if t and time.monotonic() - t[0] < LAUNCH_TIMEOUT:
            return
        self.launching[app.id] = (time.monotonic(), nwins)
        self.shell.apps.launch(app)
        self.refresh()
        GLib.timeout_add_seconds(LAUNCH_TIMEOUT + 1, lambda: self.rebuild() or False)   # the window never showed up

    @staticmethod
    def focus(wid):
        C.run_async(["niri", "msg", "action", "focus-window", "--id", str(wid)])

    @staticmethod
    def close_windows(wins):
        for w in wins:
            C.run_async(["niri", "msg", "action", "close-window", "--id", str(w["id"])])

    # ── right-click menu ───────────────────────────────────────────────────
    def open_menu(self, anchor, app, wins, zone):
        self.close_menu()
        items = box("v", 0, "dockmenu")

        def add(text, cb, cls=None, mark=False):
            row = box("h", 7, None, Gtk.Box(css_classes=["menumark"] + (["on"] if mark else []),
                                            valign=Gtk.Align.CENTER), label(text, max_chars=38))
            b = Gtk.Button(child=row, css_classes=["menuitem"] + ([cls] if cls else []), can_focus=False)
            b.connect("clicked", lambda *_: (self.close_menu(), cb()))
            items.append(b)

        def sep():
            s = Gtk.Separator()
            s.add_css_class("menusep")
            items.append(s)

        if zone == "launcher":
            items.append(label(tr("Док"), "menutitle"))
            add(tr("Все приложения"), lambda: self.shell.launcher.toggle("apps"))
            hide = self.mode == "autohide"
            add(tr("Не скрывать Док") if hide else tr("Скрывать Док автоматически"),
                lambda: C.set_setting("DOCK", "always" if hide else "autohide"))
            sep()
            add(tr("Настройки Дока…"), lambda: self.shell.panel.show("desktop"))
        else:
            items.append(label(app.name if app else (wins[0].get("app_id") or tr("Окно")), "menutitle"))
            if len(wins) > 1 or (wins and zone == "orphan"):
                for w in wins:
                    add(w.get("title") or w.get("app_id") or tr("Окно"), lambda w=w: self.focus(w["id"]),
                        mark=w["id"] == self.niri.focused)
                sep()
            if app is not None:
                add(tr("Новое окно") if wins else tr("Открыть"), lambda: self.launch(app, len(wins)))
                pinned = self.is_pinned(app.id)
                add(tr("Убрать из Дока") if pinned else tr("Оставить в Доке"), lambda: self.toggle_pin(app.id))
            if wins:
                sep()
                add(tr("Закрыть окно") if len(wins) == 1 else tr("Закрыть все окна ({0})").format(len(wins)),
                    lambda: self.close_windows(wins), "danger")

        pop = Gtk.Popover(has_arrow=False, position=Gtk.PositionType.TOP)
        pop.add_css_class("dockpop")
        pop.set_offset(0, -6)
        pop.set_child(items)
        pop.set_parent(anchor)
        pop.connect("closed", self.on_menu_closed)
        self.menu = pop
        self.cancel_hide()
        # the keyboard is only needed while the menu is open — so Esc and clicking outside close it
        LS.set_keyboard_mode(self.win, LS.KeyboardMode.ON_DEMAND)
        pop.popup()

    def close_menu(self):
        if self.menu:
            self.menu.popdown()

    def on_menu_closed(self, pop):
        LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)

        def later():
            pop.unparent()
            if self.menu is pop:
                self.menu = None
                if self.deferred:
                    self.refresh()
                if not self.hovered:
                    self.schedule_hide()
            return False
        GLib.idle_add(later)

    # ── dragging ───────────────────────────────────────────────────────────
    def add_drag(self, b, img):
        src = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        src.connect("prepare", lambda _s, _x, _y: self.drag_prepare(b))
        src.connect("drag-begin", lambda s, _d: self.drag_begin(s, b, img))
        src.connect("drag-cancel", lambda _s, _d, reason: self.drag_cancel(reason))
        src.connect("drag-end", lambda *_: self.drag_end())
        b.add_controller(src)

    def drag_prepare(self, b):
        if self.menu:
            return None
        self.drag = {"w": b, "zone": b.zone, "home": b.get_prev_sibling(), "to_pins": False}
        return Gdk.ContentProvider.new_for_bytes(MIME, GLib.Bytes.new(b.app_id.encode()))

    def drag_begin(self, src, b, img):
        if b.app.gicon is not None:
            theme = Gtk.IconTheme.get_for_display(b.get_display())
            paint = theme.lookup_by_gicon(b.app.gicon, ICON, b.get_scale_factor(), Gtk.TextDirection.NONE, 0)
            src.set_icon(paint, ICON // 2, ICON // 2)
        b.add_css_class("dragging")
        self.cancel_hide()

    def pinned_widgets(self, exclude=None):
        out, ch = [], self.row.get_first_child()
        while ch:
            if getattr(ch, "zone", None) == "pinned" and ch is not exclude:
                out.append(ch)
            ch = ch.get_next_sibling()
        return out

    def center_x(self, w):
        ok, r = w.compute_bounds(self.sheet)
        return r.get_x() + r.get_width() / 2 if ok else 0

    def on_drag_enter(self, _t, _drop, x, _y):
        if self.drag:
            self.drag["w"].set_visible(True)
            self.on_drag_motion(None, None, x, _y)
        return Gdk.DragAction.MOVE

    def on_drag_motion(self, _t, _drop, x, _y):
        d = self.drag
        if not d:
            return 0
        w = d["w"]
        sep = next((c for c in self.iter_row() if getattr(c, "zone", None) == "sep"), None)
        if d["zone"] == "running" and sep is not None and x > self.center_x(sep):
            # running but not pinned — while it's right of the divider, it stays where it is
            d["to_pins"] = False
            if w.get_prev_sibling() is not d["home"]:
                self.row.reorder_child_after(w, d["home"])
            return Gdk.DragAction.MOVE
        others = self.pinned_widgets(exclude=w)
        k = sum(1 for o in others if self.center_x(o) < x)
        after = others[k - 1] if k > 0 else self.row.get_first_child()   # the first one is the "Apps" button
        if after is not w and w.get_prev_sibling() is not after:
            self.row.reorder_child_after(w, after)
        d["to_pins"] = True
        d["order"] = [c.app_id for c in self.iter_row() if getattr(c, "zone", None) == "pinned" or c is w]
        return Gdk.DragAction.MOVE

    def on_drag_leave(self, _t, _drop):
        d = self.drag
        if not d:
            return
        # GTK sends leave right before the drop too — so the decision (to_pins/order) isn't touched here
        if d["zone"] == "pinned":
            d["w"].set_visible(False)   # the icons close the gap — let go here and it leaves the Dock
        elif d["w"].get_prev_sibling() is not d["home"]:
            self.row.reorder_child_after(d["w"], d["home"])

    def on_drop(self, _t, drop, _x, _y):
        d = self.drag
        if not d:
            drop.finish(0)
            return False
        if d["to_pins"] and d.get("order"):
            hidden = [p for p in self.pins if p not in d["order"]]   # pins that aren't installed right now go last
            d["new_pins"] = d["order"] + hidden
        drop.finish(Gdk.DragAction.MOVE)
        return True

    def drag_cancel(self, reason):
        # dropped outside the Dock (over the Dock our DropTarget takes it). On Wayland GDK reports such
        # a drop as ERROR rather than NO_TARGET; Esc (USER_CANCELLED) changes nothing
        d = self.drag
        if d and d["zone"] == "pinned" and reason != Gdk.DragCancelReason.USER_CANCELLED:
            d["new_pins"] = [p for p in self.pins if p != d["w"].app_id]
            return True   # no "fly back" animation — the icon simply leaves the Dock
        return False

    def drag_end(self):
        d, self.drag = self.drag, None
        if d:
            d["w"].remove_css_class("dragging")
            d["w"].set_visible(True)
        if d and "new_pins" in d and d["new_pins"] != self.pins:
            self.set_pins(d["new_pins"])
        else:
            self.refresh()
        if not self.hovered:
            self.schedule_hide()

    def iter_row(self):
        ch = self.row.get_first_child()
        while ch:
            yield ch
            ch = ch.get_next_sibling()

    def on_theme(self):
        self.sheet.da.queue_draw()


I_LAUNCH = "view-app-grid-symbolic"
