"""Nebula — interface language.

Strings in the code are written in Russian; the English versions live in
i18n/en.tsv as "russian<TAB>english" lines (\\n stands for a line break).
This module has no GTK dependency, so tiny helpers like the waybar pills can
use it too. The language is read once at startup: switching it restarts
whatever needs restarting.
"""
import os
import re
from pathlib import Path

NB_DIR = Path(__file__).resolve().parent.parent


def ui_lang():
    """'ru' or 'en'. UI_LANG="auto" (or nothing) follows the system locale."""
    val = "auto"
    try:
        for line in (NB_DIR / "settings.conf").read_text().splitlines():
            m = re.match(r'\s*UI_LANG=["\']?(\w+)', line)
            if m:
                val = m.group(1)
    except OSError:
        pass
    if val in ("ru", "en"):
        return val
    loc = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    return "ru" if loc.startswith(("ru", "uk", "be")) else "en"


LANG = ui_lang()
_TABLE = {}


def _load():
    try:
        for line in (NB_DIR / "i18n" / "en.tsv").read_text().splitlines():
            if "\t" in line and not line.startswith("#"):
                ru, en = line.split("\t", 1)
                # editors love to eat trailing spaces; keep the original's, they matter in "Folder: "
                en = en.rstrip() + ru[len(ru.rstrip()):]
                _TABLE[ru.replace("\\n", "\n")] = en.replace("\\n", "\n")
    except OSError:
        pass
    _TABLE.setdefault("", "")


def tr(text):
    """The string in the user's language (Russian is the source)."""
    if LANG == "ru" or not text:
        return text
    if not _TABLE:
        _load()
    return _TABLE.get(text, text)
