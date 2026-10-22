"""Nebula shell — the first-time setup wizard: it shows up at the first login after installing.

Steps: hello → theme → wallpaper → menu bar and desktop → keyboard and mouse → fun stuff and
extras → cheat sheet. Every choice is written right away (nb-settings / nb-theme / nb-wall), so you
see the changes as you go. "Skip" and "Done" leave a welcome-done mark and the wizard won't come back
by itself (to run it again: Search → "First-time setup", or nb-shell welcome).
"""
import os

from gi.repository import Gdk, Gio, GLib, Gtk, Gtk4LayerShell as LS

import common as C
import gallery
from common import I, box, icon, label, tr

DONE = C.STATE / "welcome-done"
W, H = 780, 600


def first_run():
    return not DONE.exists()


def switch(on_toggle):
    sw = Gtk.Switch(valign=Gtk.Align.CENTER)
    sw._guard = False
    sw.connect("notify::active", lambda s, _p: None if s._guard else on_toggle(s.get_active()))

    def setv(v):
        sw._guard = True
        sw.set_active(bool(v))
        sw._guard = False
    sw.setv = setv
    return sw


class Welcome:
    def __init__(self, shell):
        self.shell = shell
        self.visible = False
        self.anim = None
        self.idx = 0
        self.refreshers = []

        win = Gtk.Window(application=shell)
        LS.init_for_window(win)
        LS.set_namespace(win, "nebula-welcome")
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(win, LS.KeyboardMode.EXCLUSIVE)
        LS.set_exclusive_zone(win, -1)
        for e in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(win, e, True)
        self.win = win

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
                               transition_duration=320, vexpand=True, hhomogeneous=True, vhomogeneous=True)
        self.pages = [
            ("hello", None, self.page_hello),
            ("theme", tr("Тема"), self.page_theme),
            ("walls", tr("Обои"), self.page_walls),
            ("desk", tr("Строка меню"), self.page_desk),
            ("input", tr("Клавиатура"), self.page_input),
            ("extras", tr("Приколы"), self.page_extras),
            ("done", None, self.page_done),
        ]
        for name, _title, build in self.pages:
            self.stack.add_named(build(), name)

        self.dots = box("h", 6, "wdots", valign=Gtk.Align.CENTER)
        self.dot_w = []
        for _ in self.pages:
            d = Gtk.Box(valign=Gtk.Align.CENTER)
            d.add_css_class("wdot")
            self.dots.append(d)
            self.dot_w.append(d)
        self.step_lbl = label("", "wstep", hexpand=True)
        skip = C.button(tr("Пропустить"), "linkbtn", self.finish, tr("Закрыть мастер — всё можно поменять позже (Super+A)"))
        head = box("h", 12, "whead", self.step_lbl, self.dots, skip)

        self.back = C.button(tr("Назад"), "ghostbtn wnav", lambda: self.go(self.idx - 1))
        self.next = C.button(tr("Далее"), "accentbtn wnav", lambda: self.go(self.idx + 1))
        self.hint = label(tr("Enter — дальше · Esc — пропустить"), "tiny muted", hexpand=True)
        foot = box("h", 8, "wfoot", self.back, self.hint, self.next)

        self.card = box("v", 0, "welcome", head, self.stack, foot,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.card.set_size_request(W, H)
        self.root = box("v", 0, "welcome-dim", self.card)
        self.root.set_hexpand(True)
        self.root.set_vexpand(True)
        win.set_child(self.root)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)

    # ── showing ────────────────────────────────────────────────────────────
    def show(self, *_):
        self.shell.close_others(self)
        if self.visible:
            return False
        self.visible = True
        self.go(0, animate=False)
        self.win.present()
        if self.anim:
            self.anim.cancel()
        self.root.set_opacity(0)

        def frame(v):
            self.root.set_opacity(v)
            self.card.set_margin_top(int(36 * (1 - v)))
        self.anim = C.Tween(self.win, 0.45, frame, C.ease_out_quint)
        return False

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        if self.anim:
            self.anim.cancel()

        def frame(v):
            self.root.set_opacity(1 - v)
            self.card.set_margin_top(int(-24 * v))
        self.anim = C.Tween(self.win, 0.25, frame, C.ease_in_cubic,
                            done=lambda: (not self.visible) and self.win.set_visible(False))

    def finish(self):
        try:
            DONE.write_text("1\n")
        except OSError:
            pass
        self.hide()

    def on_theme(self):
        for d in getattr(self, "bar_previews", {}).values():
            d.queue_draw()
        for t in getattr(self, "theme_tiles", []):
            t.da.queue_draw()

    def on_key(self, _c, keyval, _code, state):
        name = Gdk.keyval_name(keyval) or ""
        if name == "Escape":
            self.finish()
        elif name in ("Return", "KP_Enter"):
            self.go(self.idx + 1) if self.idx < len(self.pages) - 1 else self.finish()
        elif name == "Left" and state & Gdk.ModifierType.ALT_MASK:
            self.go(self.idx - 1)
        else:
            return False
        return True

    # ── navigation ─────────────────────────────────────────────────────────
    def go(self, i, animate=True):
        if i >= len(self.pages):
            self.finish()
            return
        i = max(0, i)
        fwd = i >= self.idx
        self.idx = i
        name, title, _b = self.pages[i]
        for r in self.refreshers:
            r()
        self.stack.set_transition_type(
            Gtk.StackTransitionType.NONE if not animate else
            Gtk.StackTransitionType.SLIDE_LEFT if fwd else Gtk.StackTransitionType.SLIDE_RIGHT)
        self.stack.set_visible_child_name(name)
        for k, d in enumerate(self.dot_w):
            C.set_class(d, "on", k == i)
            C.set_class(d, "past", k < i)
        steps = [p for p in self.pages if p[1]]
        self.step_lbl.set_text(tr("Шаг {0} из {1} · {2}").format(steps.index(self.pages[i]) + 1, len(steps), title) if title
                               else "Nebula")
        self.back.set_visible(0 < i < len(self.pages) - 1)
        self.next.set_label({0: tr("Начать"), len(self.pages) - 1: tr("Поехали")}.get(i, tr("Далее")))
        self.hint.set_text(tr("Enter — дальше · Esc — пропустить") if i < len(self.pages) - 1 else "")

    # ── pages ──────────────────────────────────────────────────────────────
    def page(self, title, sub, *children):
        head = box("v", 4, None, label(title, "wtitle"), label(sub, "wsub", wrap=True) if sub else None)
        content = box("v", 14, "wpage", head, *children)
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sc.set_child(content)
        return sc

    def row(self, title, sub, widget):
        texts = box("v", 1, None, label(title, "t"), label(sub, "s", wrap=True) if sub else None,
                    hexpand=True, valign=Gtk.Align.CENTER)
        return box("h", 14, "opt", texts, widget)

    def page_hello(self):
        real, _login = C.user_name()
        hero = icon(I["rocket"], "whero")
        hero.set_halign(Gtk.Align.CENTER)
        title = label(tr("Привет, {0}!").format(real), "wbig", xalign=0.5)
        sub = label(tr("Это Nebula — рабочий стол на niri. Пара минут, и он станет вашим: тема, обои, "
                    "строка меню и клавиатура. Всё применяется сразу, а потом меняется в пункте управления "
                    "(Super+A)."), "wsub", xalign=0.5, wrap=True, justify=Gtk.Justification.CENTER)
        sub.set_max_width_chars(60)
        from panel import segmented
        lang = segmented([("en", "English"), ("ru", "Русский")], C.LANG,
                         lambda v: C.set_setting("UI_LANG", v) if v != C.LANG else None)
        lang.set_halign(Gtk.Align.CENTER)
        lang.set_size_request(260, -1)
        facts = box("h", 10, None, halign=Gtk.Align.CENTER)
        for glyph, t in ((I["search"], tr("Super+Пробел — поиск")), (I["cog"], tr("Super+A — настройки")),
                         (I["keyboard"], tr("Super+Shift+/ — все клавиши"))):
            facts.append(box("h", 6, "wchip", icon(glyph), label(t, None, ellipsize=False)))
        return box("v", 18, "wpage", hero, title, sub, facts, lang, valign=Gtk.Align.CENTER, vexpand=True)

    def page_theme(self):
        from gallery import draw_swatch
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=5,
                           max_children_per_line=5, column_spacing=6, row_spacing=6)
        self.theme_tiles = []
        for tid, name, colors in C.list_themes():
            da = Gtk.DrawingArea()
            da.set_size_request(124, 70)
            da.set_draw_func(draw_swatch, (colors, tid == "matugen"))
            tile = box("v", 0, "tile", da, label(name, "caption", xalign=0.5))
            b = C.button(tile, None, lambda t=tid: apply(t))
            b.tid, b.tile, b.da = tid, tile, da
            grid.append(b)
            self.theme_tiles.append(b)

        def apply(tid):
            for t in self.theme_tiles:
                C.set_class(t.tile, "current", t.tid == tid)
            C.run_async([str(C.BIN / "nb-theme"), "apply", tid, "--quiet"])

        def refresh():
            cur = C.current_theme_id()
            for t in self.theme_tiles:
                C.set_class(t.tile, "current", t.tid == cur)
        self.refreshers.append(refresh)
        return self.page(tr("Выберите тему"),
                         tr("Цвета сразу меняются везде: строка меню, окна, уведомления, терминал, экран блокировки. "
                         "«Из обоев» подстраивается под картинку на рабочем столе."), grid)

    def page_walls(self):
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=4,
                           max_children_per_line=4, column_spacing=6, row_spacing=6)
        folder = label("", "small muted", hexpand=True)
        state = {"dir": None, "tiles": []}

        def mark():
            cur = gallery.current_wall()
            for t in state["tiles"]:
                C.set_class(t.tile, "current", t.path == cur)

        def set_wall(path):
            C.run_async([str(C.BIN / "nb-wall"), "set", path, "--quiet"], lambda *_: mark())

        def refresh():
            d = C.settings().get("WALL_DIR")
            folder.set_text(tr("Папка: ") + d.replace(str(C.HOME), "~"))
            if d == state["dir"]:
                mark()
                return
            state["dir"] = d
            C.clear(grid)
            state["tiles"] = []
            files = gallery.list_walls(d) if os.path.isdir(d) else []
            cur = gallery.current_wall()
            files = ([cur] if cur in files else []) + [f for f in files if f != cur]
            for f in files[:16]:
                pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
                pic.set_size_request(168, 104)
                pic.add_css_class("thumb")
                pic.set_overflow(Gtk.Overflow.HIDDEN)
                tile = box("v", 0, "tile", pic)
                b = C.button(tile, None, lambda p=f: set_wall(p), os.path.basename(f))
                b.path, b.tile, b.pic = f, tile, pic
                grid.append(b)
                state["tiles"].append(b)
            empty.set_visible(not files)
            scale = max(1, self.win.get_scale_factor())
            jobs = []
            for t in state["tiles"]:
                tp = gallery.thumb_path(t.path)
                jobs.append((t, tp if tp.exists() else t.path))
            gallery.load_textures(jobs, 168 * scale, 104 * scale,
                                  lambda batch: [t.pic.set_paintable(tex) for t, tex in batch])
            mark()
        self.refreshers.append(refresh)

        def pick_folder():
            # the file dialog is a normal window: hide the wizard while it's open, or it would cover it
            dlg = Gtk.FileDialog(title=tr("Папка с обоями"), modal=True)
            pics = C.HOME / "Pictures"
            if pics.is_dir():
                dlg.set_initial_folder(Gio.File.new_for_path(str(pics)))

            def fin(d, res):
                try:
                    f = d.select_folder_finish(res)
                except GLib.Error:
                    f = None
                self.win.set_visible(True)
                LS.set_keyboard_mode(self.win, LS.KeyboardMode.EXCLUSIVE)
                if f and f.get_path():
                    C.set_setting("WALL_DIR", f.get_path(), lambda *_: refresh())
            LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)
            self.win.set_visible(False)
            dlg.select_folder(None, None, fin)

        empty = label(tr("В папке пока нет картинок — выберите другую или положите туда свои обои."),
                      "small muted", xalign=0.5, wrap=True)
        actions = box("h", 6, None, folder,
                      C.button(box("h", 4, None, icon(I["shuffle"]), Gtk.Label(label=tr("Случайные"))), "ghostbtn",
                               lambda: C.run_async([str(C.BIN / "nb-wall"), "random", "--quiet"],
                                                   lambda *_: mark())),
                      C.button(tr("Другая папка…"), "ghostbtn", pick_folder))
        return self.page(tr("Обои"), tr("Клик — поставить. Потом: Super+W — все обои, Super+Shift+W — случайные, "
                                 "колесо на логотипе в строке меню — листать."), actions, empty, grid)

    def page_desk(self):
        from panel import BAR_STYLES, draw_bar_preview
        st = {"style": C.bar_style()}
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        self.bar_previews = {}

        def pick(sid):
            st["style"] = sid
            for d in self.bar_previews.values():
                d.queue_draw()
            C.set_setting("BAR_STYLE", sid)
        for i, (sid, title, sub) in enumerate(BAR_STYLES):
            da = Gtk.DrawingArea(content_height=70, hexpand=True)
            da.set_draw_func(lambda _d, cr, w, h, sid=sid: draw_bar_preview(
                cr, w, h, sid, self.shell.colors, st["style"] == sid))
            self.bar_previews[sid] = da
            b = C.button(box("v", 4, None, da, label(title, "t", xalign=0.5), label(sub, "s muted", xalign=0.5)),
                         "stylecard", lambda sid=sid: pick(sid))
            grid.attach(b, i % 4, i // 4, 1, 1)
        from panel import segmented
        dock = segmented([("autohide", tr("Прячется")), ("always", tr("Всегда виден")), ("off", tr("Без дока"))], "autohide",
                         lambda v: C.set_setting("DOCK", v))
        clock = switch(lambda on: C.set_setting("DESKTOP_CLOCK", int(on)))

        def refresh():
            s = C.settings()
            st["style"] = C.bar_style()
            for d in self.bar_previews.values():
                d.queue_draw()
            dock.setv(s["DOCK"])
            clock.setv(s["DESKTOP_CLOCK"] == "1")
        self.refreshers.append(refresh)
        return self.page(tr("Строка меню и рабочий стол"), tr("Стиль строки меню, док внизу экрана и большие часы на обоях."),
                         grid, self.row(tr("Док"), tr("Приложения внизу экрана"), None), dock,
                         self.row(tr("Часы на рабочем столе"), tr("Крупно, поверх обоев"), clock))

    def page_input(self):
        from panel import KB_LAYOUTS, KB_SWITCHES, segmented
        layouts = segmented(KB_LAYOUTS, "us,ru", lambda v: C.set_setting("KB_LAYOUTS", v))
        sw = segmented(KB_SWITCHES, "caps", lambda v: C.set_setting("KB_SWITCH", v))
        tap = switch(lambda on: C.set_setting("TP_TAP", int(on)))
        nat = switch(lambda on: C.set_setting("TP_NATURAL", int(on)))

        def refresh():
            s = C.settings()
            layouts.setv(s["KB_LAYOUTS"].replace(" ", ""))
            sw.setv(s["KB_SWITCH"])
            tap.setv(s["TP_TAP"] == "1")
            nat.setv(s["TP_NATURAL"] == "1")
        self.refreshers.append(refresh)
        return self.page(tr("Клавиатура и мышь"), tr("Языки и как их переключать. С Caps Lock настоящий Caps — Shift+Caps."),
                         self.row(tr("Языки"), None, None), layouts,
                         self.row(tr("Смена языка"), None, None), sw,
                         self.row(tr("Касание тачпада — клик"), tr("Два пальца — правый клик"), tap),
                         self.row(tr("Естественная прокрутка"), tr("Контент едет за пальцами"), nat))

    def page_extras(self):
        fun = switch(lambda on: C.set_setting("FUN", int(on)))
        greet = switch(lambda on: C.set_setting("GREETING", int(on)))
        wall = switch(lambda on: C.set_setting("WALL_ON_LOGIN", int(on)))
        claude = switch(lambda on: C.set_setting("CLAUDE", int(on)))

        def refresh():
            s = C.settings()
            fun.setv(s["FUN"] == "1")
            greet.setv(s["GREETING"] == "1")
            wall.setv(s["WALL_ON_LOGIN"] == "1")
            claude.setv(s["CLAUDE"] == "1")
        self.refreshers.append(refresh)
        return self.page(tr("Приколы и дополнения"), tr("Необязательное — включайте, что нравится."),
                         self.row(tr("Пасхалки в поиске"), tr("«пароль», «помидор», «погода», «#ff8800», «монетка», «2d6», «шар …», «таймер 5 мин», "
                                  "каомодзи, «удиви меня» и один код из девяностых"), fun),
                         self.row(tr("Приветствие при входе"), tr("«Доброе утро, …», день недели и совет"), greet),
                         self.row(tr("Новые обои при каждом входе"), tr("Случайные из папки обоев"), wall),
                         self.row("Claude", tr("Claude Code и Claude Desktop: Super+Shift+C, «?вопрос» в поиске, "
                                  "меню в Dolphin. Выключено — следов Claude в системе нет"), claude))

    def page_done(self):
        hero = icon(I["check"], "whero")
        hero.set_halign(Gtk.Align.CENTER)
        keys = [(tr("Super+Пробел"), tr("поиск и калькулятор")), ("Super+A", tr("пункт управления")),
                ("Super+Enter", tr("терминал")), ("Super+W", tr("обои")), ("Super+Shift+T", tr("темы")),
                ("Super+V", tr("история буфера")), ("Super+F", tr("окно на весь экран")), ("Super+Q", tr("закрыть окно")),
                ("Super+O / Tab", tr("обзор всех окон")), ("Super+1…9", tr("рабочие столы")),
                ("Caps Lock", tr("сменить язык")), ("Super+Shift+/", tr("все сочетания"))]
        g = Gtk.Grid(column_spacing=14, row_spacing=7, halign=Gtk.Align.CENTER)
        for i, (k, v) in enumerate(keys):
            col = (i % 2) * 2
            g.attach(label(k, "kbd", ellipsize=False, halign=Gtk.Align.END), col, i // 2, 1, 1)
            g.attach(label(v, "small dim", ellipsize=False), col + 1, i // 2, 1, 1)
        panel = C.button(tr("Открыть пункт управления"), "ghostbtn",
                         lambda: (self.finish(), GLib.timeout_add(300, lambda: self.shell.panel.show() or False)))
        panel.set_halign(Gtk.Align.CENTER)
        return box("v", 16, "wpage", hero, label(tr("Всё готово"), "wbig", xalign=0.5),
                   label(tr("Главное под рукой. Остальное — в пункте управления."), "wsub", xalign=0.5),
                   g, panel, valign=Gtk.Align.CENTER, vexpand=True)
