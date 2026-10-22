#!/usr/bin/env bash
# Nebula — builds a GitHub release: dist/nebula-<version>/ and dist/nebula-<version>.zip (+ .sha256)
#   tools/make-release.sh            version from the VERSION file
#   tools/make-release.sh 1.1.0      bump VERSION first, then build
#
# Only project files go in (no .git, caches, tools/ or dist/). Before packing, everything is
# combed for personal data: your username, home folder, hostname, email, keys and tokens.
# If anything turns up, the build stops — better a failed build than a leaked key.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$ROOT"
[ -n "${1:-}" ] && echo "$1" > VERSION
V="$(cat VERSION)"
NAME="nebula-$V"
OUT="$ROOT/dist/$NAME"
B=$'\e[1m'; R=$'\e[0m'; G=$'\e[38;5;114m'; E=$'\e[38;5;203m'

rm -rf "$OUT" "$ROOT/dist/$NAME.zip" "$ROOT/dist/$NAME.zip.sha256"
mkdir -p "$OUT"
for p in install.sh uninstall.sh README.md README.ru.md LICENSE VERSION .gitignore config nebula; do cp -a "$p" "$OUT/"; done
find "$OUT" \( -name __pycache__ -o -name '*.pyc' -o -name '*.nbtmp' -o -name '*.tmp' -o -name '*.tmp.png' \
    -o -name '.DS_Store' -o -name '*~' -o -name '*.swp' \) -prune -exec rm -rf {} +
# permissions: plain 755 dirs and 644 files, only the scripts are executable
find "$OUT" -type d -exec chmod 755 {} +
find "$OUT" -type f -exec chmod 644 {} +
chmod 755 "$OUT/install.sh" "$OUT/uninstall.sh" "$OUT"/nebula/bin/*

# ── personal data check ───────────────────────────────────────────────
user="$(id -un)"
real="$(getent passwd "$user" | cut -d: -f5 | cut -d, -f1)"
host="$(cat /proc/sys/kernel/hostname 2>/dev/null || true)"
mail="$(git config user.email 2>/dev/null || true)"
pats=("$HOME" "/home/$user" "\\b$user\\b")
[ -n "$real" ] && [ "$real" != "$user" ] && pats+=("$real")
case "$host" in ""|localhost|archlinux|arch|linux|computer) ;; *) pats+=("\\b$host\\b") ;; esac   # stock hostnames say nothing about you
[ -n "$mail" ] && pats+=("$mail")
pats+=(
    '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}'      # any email address
    'sk-ant-[A-Za-z0-9_-]{10,}' 'sk-[A-Za-z0-9]{32,}'   # API keys
    'gh[pousr]_[A-Za-z0-9]{20,}' 'github_pat_[A-Za-z0-9_]{20,}'
    'AKIA[0-9A-Z]{16}' 'AIza[0-9A-Za-z_-]{30,}' 'xox[abprs]-[A-Za-z0-9-]{10,}'
    '-----BEGIN [A-Z ]*PRIVATE KEY-----'
)
bad=0
for p in "${pats[@]}"; do
    if hits=$(grep -rInE -- "$p" "$OUT" 2>/dev/null); then
        printf '%s✗ found by pattern %s:%s\n%s\n' "$E" "$p" "$R" "$(printf '%s\n' "$hits" | sed "s|$OUT/|  |" | head -5)"
        bad=1
    fi
done
# hidden files and symlinks have no business in a release
while IFS= read -r f; do printf '%s✗ hidden file: %s%s\n' "$E" "${f#"$OUT"/}" "$R"; bad=1
done < <(find "$OUT" -name '.*' ! -name .gitignore ! -path "$OUT")
while IFS= read -r f; do printf '%s✗ symlink: %s%s\n' "$E" "${f#"$OUT"/}" "$R"; bad=1
done < <(find "$OUT" -type l)
[ "$bad" = 0 ] || { echo "${E}Build stopped: remove the personal data above and run it again.${R}"; exit 1; }
echo "${G}✓${R} no personal data, keys or tokens found"

# ── does it still work ────────────────────────────────────────────────
for f in "$OUT/install.sh" "$OUT/uninstall.sh" "$OUT"/nebula/bin/* "$OUT/nebula/lib.sh"; do
    head -1 "$f" | grep -q bash && { bash -n "$f" || { echo "${E}✗ syntax error: $f${R}"; exit 1; }; }
done
py=("$OUT"/nebula/shell/*.py)
for f in "$OUT"/nebula/bin/*; do head -1 "$f" | grep -q python && py+=("$f"); done
python3 -I -c 'import ast, sys
for f in sys.argv[1:]:
    ast.parse(open(f).read(), f)' "${py[@]}" || { echo "${E}✗ Python syntax error${R}"; exit 1; }
echo "${G}✓${R} scripts parse fine"

# ── the zip: no uid/gid or extra attributes, same timestamp on every file ──
python3 -I - "$ROOT/dist" "$NAME" <<'PY'
import os, sys, time, zipfile
dist, name = sys.argv[1], sys.argv[2]
stamp = time.localtime(time.time())[:3] + (0, 0, 0)
with zipfile.ZipFile(os.path.join(dist, name + ".zip"), "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for root, dirs, files in os.walk(os.path.join(dist, name)):
        dirs.sort()
        for f in sorted(files):
            full = os.path.join(root, f)
            arc = os.path.relpath(full, dist)
            info = zipfile.ZipInfo(arc, stamp)
            info.external_attr = (0o100755 if os.access(full, os.X_OK) else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(full, "rb") as fh:
                z.writestr(info, fh.read())
PY
(cd "$ROOT/dist" && sha256sum "$NAME.zip" > "$NAME.zip.sha256")
size=$(du -h "$ROOT/dist/$NAME.zip" | cut -f1)
files=$(find "$OUT" -type f | wc -l)
echo "${G}✓${R} ${B}dist/$NAME.zip${R} · $size · $files files"
echo "  sha256: $(cut -d' ' -f1 "$ROOT/dist/$NAME.zip.sha256")"
