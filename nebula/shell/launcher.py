"""Nebula shell — the search: apps, actions and settings, calculator, commands,
paths, web search. Wallpaper, themes, clipboard and power live in the Control Center."""
import ast
import math
import operator
import os
import random
import re
import shlex
import urllib.parse
from pathlib import Path

from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell as LS

import common as C
from common import I, box, icon, label, tr

WIDTH = 680
POOL = 40


# ─── calculator ─────────────────────────────────────────────────────────────
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv,
        ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {k: getattr(math, k) for k in ("sqrt", "sin", "cos", "tan", "log", "log10", "log2", "exp",
                                         "floor", "ceil", "factorial", "radians", "degrees")}
_FUNCS.update(abs=abs, round=round)
_CONST = {"pi": math.pi, "e": math.e, "tau": math.tau}


def calc(expr):
    s = expr.strip().replace(",", ".").replace("^", "**").replace("×", "*").replace("÷", "/")
    if not s or not re.search(r"\d", s) or not re.search(r"[-+*/%()]|\b(" + "|".join(_FUNCS) + r")\b", s):
        return None
    if not re.fullmatch(r"[\d\s.+\-*/%()a-z_]*", s):
        return None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 1000:
                raise ValueError
            return _OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Name) and n.id in _CONST:
            return _CONST[n.id]
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS:
            return _FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise ValueError
    try:
        v = ev(ast.parse(s, mode="eval"))
    except Exception:
        return None
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        v = round(v, 10)
        if v == int(v) and abs(v) < 1e15:
            v = int(v)
    return f"{v:,}".replace(",", " ") if isinstance(v, int) else str(v)


# ─── little joys: coin, dice, 8-ball, kaomoji, timer ────────────────────────
BALL = [tr("Бесспорно"), tr("Предрешено"), tr("Никаких сомнений"), tr("Определённо да"), tr("Можешь быть уверен в этом"),
        tr("Мне кажется — да"), tr("Вероятнее всего"), tr("Хорошие перспективы"), tr("Знаки говорят — да"), tr("Да"),
        tr("Пока не ясно, попробуй снова"), tr("Спроси позже"), tr("Лучше не рассказывать"), tr("Сейчас нельзя предсказать"),
        tr("Сконцентрируйся и спроси опять"), tr("Даже не думай"), tr("Мой ответ — нет"), tr("По моим данным — нет"),
        tr("Перспективы не очень"), tr("Весьма сомнительно")]
KAOMOJI = [("¯\\_(ツ)_/¯", "shrug пожать плечами пофиг"), ("(╯°□°)╯︵ ┻━┻", "flip стол перевернуть ярость"),
           ("┬─┬ノ( º _ ºノ)", "unflip стол вернуть"), ("( ͡° ͜ʖ ͡°)", "lenny ленни"),
           ("(づ｡◕‿‿◕｡)づ", "hug обнять обнимашки"), ("ʕ•ᴥ•ʔ", "bear медведь мишка"),
           ("(=^･ω･^=)", "cat кот котик"), ("ಠ_ಠ", "look disapproval осуждение взгляд"),
           ("(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧", "magic yay ура магия"), ("♡(˘▽˘>ԅ( ˘⌣˘)", "love любовь сердце")]
_TIMER = re.compile(r"^(?:таймер|timer)\s+(\d+(?:[.,]\d+)?)\s*(?:(сек|с|s|мин|м|m|час|ч|h)\.?(?=\s|$))?\s*(.*)$", re.I)
_DICE = re.compile(r"^(\d{0,2})[dдк](\d{1,3})$", re.I)
_HEX = re.compile(r"^#?([0-9a-f]{6}|[0-9a-f]{3})$", re.I)
# a few words that deserve an answer
EGGS = {
    "42": "Ответ на главный вопрос жизни, вселенной и всего такого",
    "hello there": "General Kenobi!",
    "sudo make me a sandwich": "Okay. 🥪",
    "make me a sandwich": "What? Make it yourself.",
    "rm -rf /": "Не сегодня 🙂",
    "hello world": "Hello, Nebula! 👋",
    "привет": "Привет-привет 👋",
    "спасибо": "Всегда пожалуйста ✨",
    "thanks": "Always happy to help ✨",
}


def password(n=20):
    """A strong password without look-alike characters (no l/1/I/O/0)."""
    import secrets
    abc = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    sym = "-_.!@#%+=?"
    while True:
        pw = "".join(secrets.choice(abc + sym) for _ in range(n))
        if (any(c.isdigit() for c in pw) and any(c in sym for c in pw)
                and any(c.isupper() for c in pw) and any(c.islower() for c in pw)):
            return pw


def fun_items(qs):
    """Silly and small-but-handy things, triggered by keywords."""
    ql = qs.casefold()
    word = ql.split(" ", 1)[0] if ql else ""
    out = []
    if word in ("монетка", "монета", "coin", "орёл", "орел", "решка"):
        r = random.choice([tr("Орёл"), tr("Решка")])
        out.append(dict(kind="fun", glyph=I["dice"], title=r, subtitle=tr("Подбросить ещё — Enter"), hint="↵",
                        run=None, again=True))
    m = _DICE.match(ql) or (word in ("кубик", "кости", "dice", "roll") and _DICE.match("d6"))
    if m:
        n, sides = max(1, min(20, int(m.group(1) or 1))), max(2, int(m.group(2)))
        rolls = [random.randint(1, sides) for _ in range(n)]
        title = " + ".join(map(str, rolls)) + (f" = {sum(rolls)}" if n > 1 else "")
        out.append(dict(kind="fun", glyph=I["dice"], title=title, subtitle=tr("{0}d{1} · бросить ещё — Enter").format(n, sides),
                        hint="↵", run=None, again=True))
    if word in ("шар", "8ball", "предсказание") and len(ql.split()) > 1:
        out.append(dict(kind="fun", glyph=I["moon"], title=random.choice(BALL), subtitle=tr("Шар предсказаний"),
                        hint=tr("↵ ещё раз"), run=None, again=True))
    if len(ql) >= 3:
        for face, words in KAOMOJI:
            if any(w.startswith(ql) for w in words.split()):
                out.append(dict(kind="fun", glyph=I["clip"], title=face, subtitle=tr("Скопировать"),
                                hint="↵", run=lambda f=face: C.copy_text(f)))
    m = _TIMER.match(qs.strip())
    if m:
        v = float(m.group(1).replace(",", "."))
        unit = (m.group(2) or "м").lower()
        sec = int(v * (1 if unit in ("с", "сек", "s") else 3600 if unit in ("ч", "час", "h") else 60))
        what = m.group(3).strip() or tr("Время вышло")
        nice = f"{int(v) if v == int(v) else v} " + (tr("с") if sec < 60 and unit in ("с", "сек", "s") else
                                                    tr("ч") if unit in ("ч", "час", "h") else tr("мин"))
        snd = "/usr/share/sounds/freedesktop/stereo/complete.oga"
        cmd = (f"sleep {sec}; notify-send -a Nebula -u critical -i alarm-symbolic "
               f"{shlex.quote(tr('Таймер · {0}').format(nice))} "
               f"{shlex.quote(what)}; [ -f {snd} ] && pw-play {snd} 2>/dev/null")
        out.append(dict(kind="fun", glyph=I["clock"], title=tr("Таймер на {0}").format(nice), subtitle=what, hint=tr("↵ запустить"),
                        run=lambda c=cmd: C.spawn(["sh", "-c", c])))
    if word in ("удиви", "surprise", "пати", "party", "вечеринка"):
        out.append(dict(kind="fun", glyph=I["shuffle"], title=tr("Удиви меня"), subtitle=tr("Случайные обои и цветовая схема"),
                        hint="↵", run=surprise))
    if word in ("пароль", "password", "pass", "pwgen"):
        pw = password()
        out.append(dict(kind="fun", glyph=I["lock"], title=pw, subtitle=tr("Надёжный пароль · Enter — скопировать"),
                        hint=tr("↵ скопировать"), run=lambda p=pw: C.copy_text(p)))
    if word in ("помидор", "pomodoro", "фокус", "focus"):
        b = C.BIN
        # 25 minutes with Do Not Disturb on; a timer (critical, so it still gets through) ends it
        cmd = (f"'{b}/nb-shell' notify dnd:on; sleep 1500; '{b}/nb-shell' notify dnd:off; "
               f"notify-send -a Nebula -u critical -i alarm-symbolic {shlex.quote(tr('Помидор готов 🍅'))} "
               f"{shlex.quote(tr('25 минут фокуса позади — пора размяться'))}; "
               f"pw-play /usr/share/sounds/freedesktop/stereo/complete.oga 2>/dev/null")
        out.append(dict(kind="fun", glyph=I["clock"], title=tr("Фокус на 25 минут"),
                        subtitle=tr("Помидор: «Не беспокоить» включится, а потом сам выключится"), hint=tr("↵ запустить"),
                        run=lambda c=cmd: C.spawn(["sh", "-c", c])))
    if word in ("погода", "weather"):
        city = qs.split(" ", 1)[1].strip() if " " in qs.strip() else ""
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=%l:+%c+%t,+%w&lang={C.LANG}"
        cmd = (f"r=$(curl -fsm 8 {shlex.quote(url)}) && notify-send -a Nebula -i weather-few-clouds "
               f"{shlex.quote(tr('Погода'))} \"$r\" || notify-send -a Nebula -i dialog-warning "
               f"{shlex.quote(tr('Погода'))} {shlex.quote(tr('wttr.in не ответил'))}")
        out.append(dict(kind="fun", glyph=I["earth"], title=tr("Погода · {0}").format(city) if city else tr("Погода здесь"),
                        subtitle=tr("Ответ придёт уведомлением (wttr.in)"), hint=tr("↵ узнать"),
                        run=lambda c=cmd: C.spawn(["sh", "-c", c])))
    m = _HEX.match(qs.strip())
    if m:
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        r, g, b_ = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        import colorsys
        hh, ll, ss = colorsys.rgb_to_hls(r / 255, g / 255, b_ / 255)
        rgb = f"rgb({r}, {g}, {b_})"
        hsl = f"hsl({round(hh * 360)}, {round(ss * 100)}%, {round(ll * 100)}%)"
        out.append(dict(kind="fun", glyph=I["palette"], title=f"<span foreground='#{h}'>●</span>  #{h.lower()}",
                        markup=True, subtitle=f"{rgb} · {hsl}", hint=tr("↵ скопировать"),
                        run=lambda t=rgb: C.copy_text(t)))
    egg = EGGS.get(ql.strip())
    if egg:
        out.append(dict(kind="fun", glyph=I["star"], title=tr(egg), subtitle="Nebula", hint="", run=None,
                        again=True))
    return out


def surprise():
    scheme = random.choice(["scheme-tonal-spot", "scheme-vibrant", "scheme-expressive", "scheme-fidelity",
                            "scheme-content", "scheme-rainbow", "scheme-fruit-salad"])
    b = C.BIN
    # a wallpaper change recolors the "From wallpaper" theme; if a regular theme is on, switch to it first
    switch = "" if C.current_theme_id() == "matugen" else f"'{b}/nb-theme' apply matugen --quiet; "
    C.spawn(["sh", "-c", f"'{b}/nb-settings' set MATUGEN_SCHEME {scheme}; {switch}'{b}/nb-wall' random"])


# ─── a result row (reused) ──────────────────────────────────────────────────
class ResultRow(Gtk.ListBoxRow):
    def __init__(self):
        super().__init__()
        self.add_css_class("result")
        self.set_focusable(False)
        self.item = None
        self.img = Gtk.Image(pixel_size=32)
        self.glyph = icon("", "glyph")
        self.pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        self.pic.set_size_request(48, 32)
        self.pic.add_css_class("thumbimg")
        self.pic.set_overflow(Gtk.Overflow.HIDDEN)
        self.title = label("", "title")
        self.sub = label("", "subtitle")
        self.hint = label("", "hint", xalign=1.0, ellipsize=False)
        texts = box("v", 1, None, self.title, self.sub, valign=Gtk.Align.CENTER, hexpand=True)
        lead = Gtk.Stack()
        lead.set_size_request(48, 32)
        for name, w in (("img", self.img), ("glyph", self.glyph), ("pic", self.pic)):
            w.set_halign(Gtk.Align.CENTER)
            lead.add_named(w, name)
        self.lead = lead
        self.set_child(box("h", 10, None, lead, texts, self.hint))

    def set_item(self, it):
        self.item = it
        if it.get("markup"):
            self.title.set_markup(it.get("title", ""))
        else:
            self.title.set_text(it.get("title", ""))
        sub = it.get("subtitle", "")
        self.sub.set_text(sub)
        self.sub.set_visible(bool(sub))
        self.hint.set_text(it.get("hint", ""))
        C.set_class(self.title, "calc", it.get("kind") == "calc")
        if it.get("gicon") is not None:
            self.img.set_from_gicon(it["gicon"])
            self.lead.set_visible_child_name("img")
        elif it.get("icon_name"):
            self.img.set_from_icon_name(it["icon_name"])
            self.lead.set_visible_child_name("img")
        elif it.get("texture") is not None:
            self.pic.set_paintable(it["texture"])
            self.lead.set_visible_child_name("pic")
        else:
            self.glyph.set_text(it.get("glyph", I["search"]))
            self.lead.set_visible_child_name("glyph")


def scroll_into_view(scrolled, widget, ref):
    ok, rect = widget.compute_bounds(ref)
    if not ok:
        return
    adj = scrolled.get_vadjustment()
    top, bottom = rect.origin.y, rect.origin.y + rect.size.height
    if top < adj.get_value():
        adj.set_value(max(0, top - 6))
    elif bottom > adj.get_value() + adj.get_page_size():
        adj.set_value(bottom - adj.get_page_size() + 6)


# ─── Search ──────────────────────────────────────────────────────────────
class Launcher:
    def __init__(self, shell):
        self.shell = shell
        self.visible = False
        self.anim = None

        win = Gtk.Window(application=shell)
        LS.init_for_window(win)
        LS.set_namespace(win, "nebula-launcher")
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(win, LS.KeyboardMode.EXCLUSIVE)
        LS.set_anchor(win, LS.Edge.TOP, True)
        self.win = win

        root = box("v", 0, "launcher")
        root.set_size_request(WIDTH, -1)
        root.set_overflow(Gtk.Overflow.HIDDEN)
        self.root = root

        self.entry = Gtk.Entry(hexpand=True)
        self.entry.add_css_class("search")
        self.entry.connect("changed", lambda *_: self.search(self.entry.get_text()))
        self.entry.connect("activate", lambda *_: self.activate())
        root.append(box("h", 12, "searchrow", icon(I["search"], "searchicon"), self.entry))
        self.sep = Gtk.Separator()
        root.append(self.sep)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, activate_on_single_click=True)
        self.list.connect("row-activated", lambda _l, r: self.on_row(r))
        self.pool = [ResultRow() for _ in range(POOL)]
        for r in self.pool:
            self.list.append(r)
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                max_content_height=440)
        sc.set_child(self.list)
        self.list_scroll = sc
        self.empty = label(tr("Ничего не найдено"), "empty", xalign=0.5)
        self.body = box("v", 0, "body", sc, self.empty)
        root.append(self.body)
        self.footer = label("", "footer", ellipsize=True)
        self.footer.set_use_markup(True)
        root.append(self.footer)
        self.update_hints()

        self.sheet = C.Sheet("top", root, lambda: shell.colors)
        win.set_child(self.sheet)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)

    def update_hints(self):
        """Hints in the search field and the footer — "?Claude" only when the add-on is on."""
        claude = C.settings().get("CLAUDE") == "1"
        self.entry.set_placeholder_text(tr("Поиск приложений, настроек, 2+2, >команда") + (", ?Claude" if claude else ""))
        k = lambda s: f"<span font_family='Inter' weight='600'> {s} </span>"
        self.footer.set_markup(tr("{0} открыть   {1} в док   <b>&gt;</b> команда   ").format(k('↵'), k('Ctrl D'))
                               + ("<b>?</b> Claude   " if claude else "")
                               + tr("<b>2+2</b> калькулятор   <b>~/</b> путь"))

    # ── show / hide ────────────────────────────────────────────────────────
    def toggle(self, _tab=None):
        self.hide() if self.visible else self.show()

    def show(self, _tab=None):
        self.shell.close_others(self)
        first = not self.visible
        self.visible = True
        self.update_hints()
        self.entry.set_text("")
        self.search("")
        if first:
            # the sheet "grows" out of the menu bar, the content fades in right after
            self.sheet.refresh()
            self.sheet.set_progress(0)
            self.root.set_opacity(0)
            self.shell.backdrop_show(self)
            self.win.present()
            if self.anim:
                self.anim.cancel()

            def frame(v):
                self.sheet.set_progress(v)
                self.root.set_opacity(max(0.0, (v - 0.35) / 0.65))
            self.anim = C.Tween(self.win, 0.30, frame, C.ease_out_quint)
        self.entry.grab_focus()

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        self.shell.backdrop_hide(self)
        if self.anim:
            self.anim.cancel()

        def frame(v):
            self.sheet.set_progress(1 - v)
            self.root.set_opacity(max(0.0, 1 - v * 2.5))
        self.anim = C.Tween(self.win, 0.20, frame, C.ease_in_cubic,
                            done=lambda: (not self.visible) and self.win.set_visible(False))

    def fit(self):
        """A layer window never shrinks by itself — reset its size so it hugs the content."""
        def go():
            _m, nat, _b, _b2 = self.list.measure(Gtk.Orientation.VERTICAL, WIDTH - 16)
            self.list_scroll.set_min_content_height(min(nat, 440))
            self.win.set_default_size(1, 1)
            return False
        GLib.idle_add(go)

    # ── keyboard ───────────────────────────────────────────────────────────
    KONAMI = ["Up", "Up", "Down", "Down", "Left", "Right", "Left", "Right", "b", "a"]

    def on_key(self, _c, keyval, _code, state):
        name = Gdk.keyval_name(keyval) or ""
        self.konami = (getattr(self, "konami", []) + [name])[-len(self.KONAMI):]
        if self.konami == self.KONAMI and C.settings().get("FUN") == "1":
            self.konami = []
            self.hide()
            C.spawn(["notify-send", "-a", "Nebula", "-i", "face-cool", "↑↑↓↓←→←→BA", tr("Код принят. Вечеринка!")])
            surprise()
            return True
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        shift = state & Gdk.ModifierType.SHIFT_MASK
        if name == "Escape":
            if self.entry.get_text():
                self.entry.set_text("")
            else:
                self.hide()
            return True
        if name in ("Up", "Down"):
            self.move(-1 if name == "Up" else 1)
            return True
        if name in ("Page_Up", "Page_Down"):
            self.move(-5 if name == "Page_Up" else 5)
            return True
        if name in ("Tab", "ISO_Left_Tab") and not ctrl:
            self.move(-1 if (shift or name == "ISO_Left_Tab") else 1)
            return True
        if ctrl and name.lower() == "d":
            row = self.list.get_selected_row()
            it = getattr(row, "item", None)
            if it and it.get("kind") == "app":
                on = self.shell.dock.toggle_pin(it["app"].id)
                it["hint"] = tr("в доке") if on else ""
                row.hint.set_text(tr("закреплено в доке") if on else tr("убрано из дока"))
            return True
        return False

    def move(self, d):
        rows = [r for r in self.pool if r.get_visible()]
        if not rows:
            return
        cur = self.list.get_selected_row()
        i = rows.index(cur) if cur in rows else -1
        i = max(0, min(len(rows) - 1, i + d))
        self.list.select_row(rows[i])
        scroll_into_view(self.list_scroll, rows[i], self.list)

    def activate(self):
        row = self.list.get_selected_row()
        if row is None:
            self.move(1)
            row = self.list.get_selected_row()
        if row is not None:
            self.on_row(row)

    # ── search ─────────────────────────────────────────────────────────────
    def actions(self):
        b = str(C.BIN)
        sh = self.shell
        page = lambda p: (lambda: sh.panel.show(p))
        acts = [
            (tr("Заблокировать экран"), tr("Питание"), I["lock"], "lock блокировка заблокировать экран",
             lambda: C.spawn([f"{b}/nb-power", "lock"])),
            (tr("Сон"), tr("Питание"), I["sleep"], "sleep suspend сон спать", lambda: C.spawn([f"{b}/nb-power", "suspend"])),
            (tr("Выйти из сеанса"), tr("Питание"), I["logout"], "logout exit выход выйти",
             lambda: C.spawn([f"{b}/nb-power", "logout"])),
            (tr("Перезагрузка"), tr("Питание"), I["reboot"], "reboot restart перезагрузка перезагрузить",
             lambda: C.spawn([f"{b}/nb-power", "reboot"])),
            (tr("Выключение"), tr("Питание"), I["power"], "shutdown poweroff выключение выключить",
             lambda: C.spawn([f"{b}/nb-power", "shutdown"])),
            (tr("Случайные обои"), tr("Обои"), I["shuffle"], "random wallpaper случайные обои",
             lambda: C.spawn([f"{b}/nb-wall", "random"])),
            (tr("Обои"), tr("Пункт управления"), I["wall"], "wallpaper обои фон картинка", page("walls")),
            (tr("Темы и цвета"), tr("Пункт управления"), I["palette"], "theme темы цвета оформление", page("appearance")),
            (tr("История буфера"), tr("Пункт управления"), I["clip"], "clipboard буфер история копировать", page("clip")),
            (tr("Питание"), tr("Пункт управления"), I["power"], "power питание выключить меню", page("power")),
            (tr("Пункт управления"), tr("Wi-Fi, звук, яркость, настройки"), I["cog"],
             "control center settings настройки пункт управления панель", lambda: sh.panel.show()),
            (tr("Не беспокоить"), tr("Уведомления вкл/выкл"), I["moon"], "dnd do not disturb не беспокоить уведомления",
             lambda: C.spawn([f"{b}/nb-notif", "dnd"])),
            (tr("Скриншот области"), tr("С редактором"), I["camera"], "screenshot скриншот снимок экрана",
             lambda: C.spawn([f"{b}/nb-shot"])),
            ("Wi-Fi", tr("Пункт управления"), I["wifi"], "wifi wi-fi сеть интернет", page("wifi")),
            ("Bluetooth", tr("Пункт управления"), I["bt"], "bluetooth блютуз наушники", page("bluetooth")),
            (tr("Звук и устройства"), tr("Пункт управления"), I["vol"], "sound audio звук громкость наушники колонки",
             page("sound")),
            (tr("Масштаб экрана"), tr("Настройки"), I["monitor"], "scale масштаб экран монитор размер", page("display")),
            (tr("Дата и время"), tr("Настройки"), I["clock"], "time date clock language english russian время дата часы часовой пояс язык английский русский", page("time")),
            (tr("Профиль и аватар"), tr("Настройки"), I["account"], "avatar profile профиль аватар фото пользователь",
             page("profile")),
            (tr("Картинка fastfetch"), tr("Настройки"), I["fetch"], "fastfetch fetch картинка терминал", page("fetch")),
            (tr("Окна и анимации"), tr("Настройки"), I["window"],
             "windows animations окна анимации прозрачность экономия производительность", page("windows")),
            (tr("Строка меню"), tr("Настройки"), I["bar"], "bar waybar панель строка меню модули стиль плеер", page("bar")),
            (tr("Рабочий стол"), tr("Док, часы на обоях"), I["apps"],
             "desktop dock рабочий стол часы виджет циферблат шрифт", page("desktop")),
            (tr("Управление"), tr("Мышь, тачпад, горячий угол, жесты"), I["mouse"],
             "mouse touchpad мышь тачпад жесты горячий угол прокрутка фокус управление", page("input")),
            (tr("Первоначальная настройка"), tr("Мастер: тема, обои, строка меню, клавиатура"), I["star"],
             "welcome setup wizard мастер первоначальная настройка начало привет", lambda: sh.welcome.show()),
            (tr("Дополнения"), tr("Пункт управления"), I["puzzle"], "extras addons дополнения приколы пасхалки claude клод",
             page("extras")),
        ]
        st = C.settings()
        if st.get("FUN") == "1":
            acts.append((tr("Удиви меня"), tr("Случайные обои и цветовая схема"), I["shuffle"],
                         "surprise party удиви пати вечеринка", surprise))
        if st.get("CLAUDE") == "1":
            acts += [
                ("Claude Code", tr("В терминале"), I["claude"], "claude клод ai ии код code терминал",
                 lambda: C.spawn([f"{b}/nb-claude", "here"])),
                (tr("Claude: продолжить"), tr("Последний разговор"), I["claude"], "claude клод продолжить continue",
                 lambda: C.spawn([f"{b}/nb-claude", "continue"])),
                ("Claude Desktop", tr("Приложение"), I["claude"], "claude клод desktop приложение чат",
                 lambda: C.spawn([f"{b}/nb-claude", "desktop"])),
                (tr("Настройки Claude"), tr("Пункт управления"), I["claude"], "claude клод настройки установить desktop",
                 page("claude")),
            ]
        return acts

    def search(self, q):
        items = []
        qs = q.strip()
        st = C.settings()
        if st.get("CLAUDE") == "1" and qs[:1] in ("?", "？"):
            question = qs[1:].strip()
            b = str(C.BIN)
            if question:
                items.append(dict(kind="cmd", glyph=I["claude"], title=question, subtitle=tr("Спросить Claude"),
                                  hint="↵", run=lambda q=question: C.spawn([f"{b}/nb-claude", "ask", q])))
            else:
                items.append(dict(kind="cmd", glyph=I["claude"], title=tr("Спросить Claude…"),
                                  subtitle=tr("Напишите вопрос после «?»"), run=lambda: C.spawn([f"{b}/nb-claude", "here"])))
        elif qs.startswith(">"):
            cmd = qs[1:].strip()
            if cmd:
                term = C.settings().get("TERMINAL", "kitty")
                items.append(dict(kind="cmd", glyph=I["term"], title=cmd, subtitle=tr("Выполнить команду"), hint="↵",
                                  run=lambda c=cmd: C.spawn(["sh", "-c", c])))
                items.append(dict(kind="cmd", glyph=I["term"], title=cmd, subtitle=tr("Выполнить в терминале ({0})").format(term),
                                  run=lambda c=cmd: C.spawn([term, "--hold", "sh", "-c", c])))
        else:
            items += fun_items(qs) if qs and st.get("FUN") == "1" else []
            res = calc(qs) if qs else None
            if res is not None:
                items.append(dict(kind="calc", glyph=I["calc"], title=f"= {res}", subtitle=qs,
                                  hint=tr("↵ скопировать"), run=lambda r=res: C.copy_text(r.replace(" ", ""))))
            if qs[:1] in ("/", "~"):
                p = Path(os.path.expanduser(qs))
                if p.exists():
                    items.append(dict(kind="path", glyph=I["folder"] if p.is_dir() else I["image"],
                                      title=str(p).replace(str(C.HOME), "~"), subtitle=tr("Открыть"),
                                      run=lambda p=p: C.spawn(["xdg-open", str(p)])))
            apps = self.shell.apps.search(qs, limit=POOL)
            acts = []
            if qs:
                from apps import score_text
                ql = qs.casefold()
                for a in self.actions():
                    hay = a[0].casefold()
                    s = score_text(ql, hay, hay.split() + a[3].split())
                    if s:
                        acts.append((s, a))
                acts.sort(key=lambda x: -x[0])
            dock = self.shell.dock
            app_items = [dict(kind="app", gicon=a.gicon, title=a.name, subtitle=a.comment or a.generic, app=a,
                              hint=tr("в доке") if dock.is_pinned(a.id) else "") for a in apps]
            act_items = [dict(kind="action", glyph=a[2], title=a[0], subtitle=a[1], run=a[4]) for _, a in acts[:6]]
            # strong action matches (an exact prefix) go above apps
            strong = [x for (s, _), x in zip(acts, act_items) if s >= 600]
            weak = [x for x in act_items if x not in strong]
            items += strong + app_items[:max(0, POOL - len(items) - len(act_items) - 1)] + weak
            if qs:
                url = C.settings().get("SEARCH_URL", "https://www.google.com/search?q=")
                items.append(dict(kind="web", glyph=I["web"], title=tr("Искать «{0}» в интернете").format(qs),
                                  subtitle=url.split("/")[2] if "//" in url else url,
                                  run=lambda: C.spawn(["xdg-open", url + urllib.parse.quote(qs)])))
        for i, row in enumerate(self.pool):
            if i < len(items):
                row.set_item(items[i])
                row.set_visible(True)
            else:
                row.item = None
                row.set_visible(False)
        self.empty.set_visible(not items)
        self.fit()
        if items:
            self.list.select_row(self.pool[0])
            self.list_scroll.get_vadjustment().set_value(0)

    def on_row(self, row):
        it = getattr(row, "item", None)
        if not it:
            return
        if it.get("again"):   # coin, dice, 8-ball: Enter throws again and the window stays open
            self.search(self.entry.get_text())
            return
        self.hide()
        if it.get("kind") == "app":
            self.shell.apps.launch(it["app"])
        else:
            it["run"]()
