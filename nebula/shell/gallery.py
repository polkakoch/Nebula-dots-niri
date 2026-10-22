"""Nebula shell — wallpapers and themes: file lists, previews, little theme swatches (for the Control Center)."""
import hashlib
import math
import os
import re
import threading
import urllib.parse

import cairo
from gi.repository import Gdk, GdkPixbuf, GLib

import common as C

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}


def list_walls(d):
    out = []
    for root, _dirs, files in os.walk(d, followlinks=True):
        for f in files:
            if os.path.splitext(f)[1].lower() in IMG_EXT:
                out.append(os.path.join(root, f))

    def natkey(s):
        return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", s)]
    out.sort(key=natkey)
    return out


def thumb_path(f):
    return C.CACHE / "thumbs-v3" / (hashlib.md5(f.encode()).hexdigest() + ".png")


def current_wall():
    try:
        return (C.STATE / "wallpaper").read_text().strip()
    except OSError:
        return ""


def parse_dir(text):
    p = text.strip().strip("\"'")
    if p.startswith("file://"):
        p = urllib.parse.unquote(urllib.parse.urlparse(p).path)
    p = os.path.expanduser(p.replace("$HOME", str(C.HOME)))
    if os.path.isfile(p):
        p = os.path.dirname(p)
    return os.path.realpath(p) if p and os.path.isdir(p) else None


def load_textures(jobs, w, h, apply, alive=lambda: True):
    """jobs: [(key, path)] → apply([(key, texture)]) in batches on the main thread; reading happens in the background."""
    def work():
        batch = []
        for key, path in jobs:
            if not alive():
                return
            tex = C.texture_scaled(path, w, h)
            if tex:
                batch.append((key, tex))
            if len(batch) >= 12:
                GLib.idle_add(lambda b=batch: apply(b) or False)
                batch = []
        if batch:
            GLib.idle_add(lambda b=batch: apply(b) or False)
    threading.Thread(target=work, daemon=True).start()


def draw_swatch(_da, cr, w, h, data):
    """A tiny theme preview: background, a "window" and accent dots."""
    colors, dynamic = data
    r = 11

    def rrect(x, y, ww, hh, rad):
        cr.new_sub_path()
        cr.arc(x + ww - rad, y + rad, rad, -math.pi / 2, 0)
        cr.arc(x + ww - rad, y + hh - rad, rad, 0, math.pi / 2)
        cr.arc(x + rad, y + hh - rad, rad, math.pi / 2, math.pi)
        cr.arc(x + rad, y + rad, rad, math.pi, 3 * math.pi / 2)
        cr.close_path()
    if not colors:
        # "From wallpaper": preview the current wallpaper
        rrect(0, 0, w, h, r)
        cr.clip()
        try:
            wall = (C.STATE / "wallpaper").read_text().strip()
            tp = C.CACHE / "thumbs-v3" / (hashlib.md5(wall.encode()).hexdigest() + ".png")
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(tp), w * 2, h * 2, True)
            s = max(w / pb.get_width(), h / pb.get_height())
            cr.scale(s, s)
            Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
            cr.paint()
        except Exception:
            cr.set_source_rgb(0.3, 0.3, 0.35)
            cr.paint()
        return
    cr.set_source_rgb(*C.hex_to_rgb(colors["bg"]))
    rrect(0, 0, w, h, r)
    cr.fill()
    cr.set_source_rgb(*C.hex_to_rgb(colors["surface"]))
    rrect(12, 12, w - 24, 26, 7)
    cr.fill()
    g = cairo.LinearGradient(12, 0, w - 12, 0)
    g.add_color_stop_rgb(0, *C.hex_to_rgb(colors["accent"]))
    g.add_color_stop_rgb(1, *C.hex_to_rgb(colors["accent2"]))
    cr.set_source(g)
    rrect(18, 20, (w - 36) * 0.55, 10, 5)
    cr.fill()
    for i, k in enumerate(("accent", "accent2", "red", "green", "yellow")):
        cr.set_source_rgb(*C.hex_to_rgb(colors.get(k, "#888888")))
        cr.arc(22 + i * 22, h - 22, 8, 0, 2 * math.pi)
        cr.fill()
    cr.set_source_rgba(*C.hex_to_rgb(colors["fg"]), 0.12)
    rrect(0.5, 0.5, w - 1, h - 1, r)
    cr.set_line_width(1)
    cr.stroke()
