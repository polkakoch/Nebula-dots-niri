"""Nebula shell — apps (.desktop files via Gio), how often they're launched, and fuzzy search."""
import json
import os
import shlex

from gi.repository import Gio, GLib

from common import STATE, settings, spawn

USAGE = STATE / "app-usage.json"
FIELD_CODES = {"%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N", "%v", "%m", "%k"}


class App:
    __slots__ = ("id", "name", "generic", "comment", "keywords", "exe", "gicon", "info", "hay", "words")

    def __init__(self, info):
        self.info = info
        self.id = info.get_id() or ""
        self.name = info.get_display_name() or info.get_name() or self.id
        self.generic = info.get_generic_name() or ""
        self.comment = info.get_description() or ""
        self.keywords = " ".join(info.get_keywords() or [])
        exe = info.get_executable() or ""
        self.exe = os.path.basename(exe)
        self.gicon = info.get_icon()
        self.hay = self.name.casefold()
        self.words = [w for w in self.hay.replace("-", " ").replace(".", " ").split() if w]


def score_text(q, hay, words):
    """Higher is better. 0 means no match."""
    if not q:
        return 1
    if hay == q:
        return 1000
    if hay.startswith(q):
        return 800 - len(hay)
    for w in words:
        if w.startswith(q):
            return 600 - len(hay)
    i = hay.find(q)
    if i >= 0:
        return 400 - i
    # a subsequence: "ffx" → firefox
    pos, gaps = 0, 0
    for ch in q:
        j = hay.find(ch, pos)
        if j < 0:
            return 0
        gaps += j - pos
        pos = j + 1
    return max(1, 200 - gaps * 4)


class AppIndex:
    def __init__(self):
        self.apps = []
        self.usage = self.load_usage()
        self.monitor = Gio.AppInfoMonitor.get()
        self.monitor.connect("changed", lambda *_: self.reload())
        self.reload()

    def reload(self):
        out = []
        for info in Gio.AppInfo.get_all():
            try:
                if not info.should_show():
                    continue
            except Exception:
                continue
            out.append(App(info))
        out.sort(key=lambda a: a.hay)
        self.apps = out

    @staticmethod
    def load_usage():
        try:
            return json.loads(USAGE.read_text())
        except Exception:
            return {}

    def search(self, q, limit=60):
        q = q.strip().casefold()
        res = []
        for a in self.apps:
            s = score_text(q, a.hay, a.words)
            if not s and q:
                # keywords, description and the program name count for less than the name
                extra = f"{a.generic} {a.keywords} {a.exe}".casefold()
                if q in extra:
                    s = 120
                elif len(q) > 3 and q in a.comment.casefold():
                    s = 60
            if s:
                # launch frequency lifts a result, but never above an exact match
                s += min(self.usage.get(a.id, 0), 50) * (6 if q else 100)
                res.append((s, a))
        res.sort(key=lambda x: (-x[0], x[1].hay))
        return [a for _, a in res[:limit]]

    def launch(self, app):
        args = []
        try:
            cmd = app.info.get_commandline() or ""
            for tok in shlex.split(cmd):
                if tok in FIELD_CODES:
                    continue
                if tok == "%i":
                    continue
                args.append(tok.replace("%c", app.name).replace("%%", "%"))
        except ValueError:
            args = []
        if not args:
            try:
                app.info.launch([], None)
            except GLib.Error:
                return
        else:
            if app.info.get_boolean("Terminal") if hasattr(app.info, "get_boolean") else False:
                args = [settings().get("TERMINAL", "kitty"), "-e", *args]
            spawn(args)
        self.usage[app.id] = self.usage.get(app.id, 0) + 1
        try:
            USAGE.write_text(json.dumps(self.usage, ensure_ascii=False, indent=0))
        except OSError:
            pass
