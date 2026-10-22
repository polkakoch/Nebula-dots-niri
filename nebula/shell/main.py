#!/usr/bin/env python3
"""Nebula shell — the resident process (GTK4 + layer-shell): Search, Control Center, player, notifications.

Windows are created once at startup and after that only shown and hidden — that's why they open instantly.
Commands arrive through a FIFO ($XDG_RUNTIME_DIR/nebula/shell.fifo), written by nb-shell:
  launcher (search only)   panel [page]   media
  (the old "launcher walls|themes|clip|power" opens the matching Control Center page)
  welcome (first-time setup)   theme (re-read the theme)   notify <cmd>   notify-changed   hide   quit
"""
import ctypes
import os
import signal
import sys

# gtk4-layer-shell has to load before libwayland-client (that is, before GTK)
ctypes.CDLL("libgtk4-layer-shell.so")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

try:
    from gi.repository import GLibUnix as UNIX  # noqa: E402
except ImportError:   # older PyGObject
    class UNIX:
        fd_add_full = staticmethod(GLib.unix_fd_add_full)
        signal_add = staticmethod(GLib.unix_signal_add)

import common as C  # noqa: E402
from style import build_css  # noqa: E402

FIFO = C.RUNTIME / "shell.fifo"
PIDFILE = C.RUNTIME / "shell.pid"


class Shell(Gtk.Application):
    def __init__(self, initial):
        super().__init__(application_id="org.nebula.Shell", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.initial = initial
        self.provider = None
        self.backdrop_owner = None
        self.surfaces = []

    def do_activate(self):
        self.hold()
        self.load_theme()
        from apps import AppIndex
        from dock import Dock
        from frame import DesktopClock, Frame
        from launcher import Launcher
        from media import MediaPopup
        from notifications import Notifications
        from panel import Panel
        from welcome import Welcome, first_run
        self.notifs = Notifications(self)    # first, so nothing else grabs the notification bus name
        self.apps = AppIndex()
        # order matters: the frame is created first so the Dock draws on top of it
        self.desktop = DesktopClock(self)
        self.frame = Frame(self)
        self.dock = Dock(self)
        self.backdrop = C.Backdrop(self, self.hide_all)
        self.launcher = Launcher(self)
        self.panel = Panel(self)
        self.media = MediaPopup(self)
        self.welcome = Welcome(self)
        self.surfaces = [self.launcher, self.panel, self.media, self.welcome]
        self.open_fifo()
        if first_run() and not self.initial:
            GLib.timeout_add(1800, self.welcome.show)
        if self.initial:
            GLib.idle_add(lambda: self.command(self.initial) and False)

    # ── theme ──────────────────────────────────────────────────────────────
    def load_theme(self):
        self.colors = C.load_theme()
        disp = Gdk.Display.get_default()
        st = Gtk.Settings.get_default()
        light = self.colors.get("mode") == "light"
        if hasattr(Gtk, "InterfaceColorScheme"):
            st.set_property("gtk-interface-color-scheme",
                            Gtk.InterfaceColorScheme.LIGHT if light else Gtk.InterfaceColorScheme.DARK)
        else:
            st.set_property("gtk-application-prefer-dark-theme", not light)
        st.set_property("gtk-icon-theme-name", "Papirus-Light" if light else "Papirus-Dark")
        st.set_property("gtk-enable-animations", True)
        prov = Gtk.CssProvider()
        prov.load_from_string(build_css(self.colors))
        if self.provider:
            Gtk.StyleContext.remove_provider_for_display(disp, self.provider)
        Gtk.StyleContext.add_provider_for_display(disp, prov, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.provider = prov

    def reload_theme(self):
        self.load_theme()
        for s in self.surfaces + [self.frame, self.dock, self.desktop]:
            if hasattr(s, "on_theme"):
                s.on_theme()

    # ── commands ───────────────────────────────────────────────────────────
    def open_fifo(self):
        try:
            if FIFO.exists() and not FIFO.is_fifo():
                FIFO.unlink()
            if not FIFO.exists():
                os.mkfifo(FIFO)
        except OSError:
            pass
        fd = os.open(FIFO, os.O_RDWR | os.O_NONBLOCK)
        self.fifo_buf = b""
        UNIX.fd_add_full(GLib.PRIORITY_DEFAULT, fd, GLib.IOCondition.IN, self.on_fifo, fd)

    def on_fifo(self, fd, _cond, *_):
        try:
            self.fifo_buf += os.read(fd, 4096)
        except BlockingIOError:
            return True
        *lines, self.fifo_buf = self.fifo_buf.split(b"\n")
        for line in lines:
            self.command(line.decode(errors="replace").strip())
        return True

    def command(self, line):
        parts = line.split()
        if not parts:
            return
        cmd, arg = parts[0], (parts[1] if len(parts) > 1 else None)
        if cmd == "launcher":
            page = {"walls": "walls", "themes": "appearance", "clip": "clip", "power": "power"}.get(arg)
            self.panel.toggle(page) if page else self.launcher.toggle()
        elif cmd == "panel":
            self.panel.toggle(arg)
        elif cmd == "media":
            self.media.toggle()
        elif cmd == "welcome":   # welcome [step number] — open the wizard (straight at a step — handy for testing)
            self.welcome.show()
            if arg and arg.isdigit():
                self.welcome.go(int(arg), animate=False)
        elif cmd == "theme":
            self.reload_theme()
        elif cmd == "settings":   # nb-settings has written settings.conf
            self.frame.apply()
            self.desktop.apply()
            self.dock.apply()
            self.notifs.apply_settings()
        elif cmd == "notify":   # notify dismiss | clear | restore | dnd[:on|off] | test
            self.notifs.command(arg)
        elif cmd == "notify-changed":
            self.panel.on_notify_changed()
        elif cmd == "query":   # for testing: put some text into the search field
            self.launcher.entry.set_text(line.split(" ", 1)[1] if " " in line else "")
        elif cmd == "dock-menu":   # for testing: the menu of the Nth Dock icon (0 — "Apps")
            ch = list(self.dock.iter_row())[int(arg or 0)]
            self.dock.place(True, animate=False)
            self.dock.open_menu(ch, ch.app, [w for w in self.dock.niri.windows.values()
                                             if ch.app and self.dock.app_for_window(w) is ch.app], ch.zone)
        elif cmd == "hide":
            self.hide_all()
        elif cmd == "quit":
            self.quit()

    # ── shared ─────────────────────────────────────────────────────────────
    def close_others(self, keep):
        for s in self.surfaces:
            if s is not keep and s.visible:
                s.hide()

    def hide_all(self):
        self.dock.close_menu()
        for s in self.surfaces:
            if s.visible:
                s.hide()

    def backdrop_show(self, owner):
        self.backdrop_owner = owner
        self.backdrop.present()

    def backdrop_hide(self, owner):
        if self.backdrop_owner is owner:
            self.backdrop_owner = None
            self.backdrop.set_visible(False)


def main():
    initial = ""
    if len(sys.argv) > 2 and sys.argv[1] == "--cmd":
        initial = " ".join(sys.argv[2:])
    # one instance only: if one is already running, hand it the command and leave
    try:
        pid = int(PIDFILE.read_text())
        if pid != os.getpid() and b"nebula" in open(f"/proc/{pid}/cmdline", "rb").read():
            if initial:
                fd = os.open(FIFO, os.O_RDWR | os.O_NONBLOCK)
                os.write(fd, (initial + "\n").encode())
                os.close(fd)
            return 0
    except (OSError, ValueError):
        pass
    PIDFILE.write_text(str(os.getpid()))
    GLib.set_prgname("nebula-shell")
    app = Shell(initial)
    UNIX.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: app.quit() or False)
    UNIX.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: app.reload_theme() or True)
    try:
        return app.run([])
    finally:
        try:
            if PIDFILE.read_text().strip() == str(os.getpid()):
                PIDFILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
