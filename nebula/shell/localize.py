#!/usr/bin/env python3
"""Switch the language of text inside config files: hotkey titles in niri,
tooltips in waybar, lock screen captions, Dolphin menu items.

    localize.py <ru|en> <file>...    rewrite the files in place
    localize.py <ru|en> -            filter stdin to stdout (for rendered templates)

It works both ways off the same i18n/en.tsv table, so switching back and forth
never needs the original files. A phrase is only swapped when it fills a whole
"slot" — between quotes, between tags, or after `=` up to the end of the line —
so a short word can't accidentally change inside a longer sentence.
"""
import re
import sys
from pathlib import Path

TSV = Path(__file__).resolve().parent.parent / "i18n" / "en.tsv"


def pairs(lang):
    out = []
    for line in TSV.read_text().splitlines():
        if "\t" not in line or line.startswith("#"):
            continue
        ru, en = line.split("\t", 1)
        if ru and en and ru != en:
            out.append((ru, en) if lang == "en" else (en, ru))
    # longest first, so "Claude: продолжить разговор" wins over "Claude"
    out.sort(key=lambda p: -len(p[0]))
    return out


def swap(text, table):
    for src, dst in table:
        if src not in text:
            continue
        pat = r'(?<=["\'>=])(\s*)' + re.escape(src) + r'(?=["\'<]|\s*$|\s*//)'
        text = re.sub(pat, lambda m: m.group(1) + dst, text, flags=re.M)
    return text


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("ru", "en"):
        print(__doc__.strip(), file=sys.stderr)
        return 1
    table = pairs(sys.argv[1])
    if sys.argv[2] == "-":
        sys.stdout.write(swap(sys.stdin.read(), table))
        return 0
    for name in sys.argv[2:]:
        p = Path(name)
        try:
            old = p.read_text()
        except OSError:
            continue
        new = swap(old, table)
        if new != old:
            p.write_text(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
