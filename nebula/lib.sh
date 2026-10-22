#!/usr/bin/env bash
# Nebula — shared paths and helpers for every script

NB_DIR="${NB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
NB_CONF="${NB_CONF:-${XDG_CONFIG_HOME:-$HOME/.config}}"   # where app configs get generated
NB_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/nebula"
NB_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/nebula"
NB_THUMBS="$NB_CACHE/thumbs-v3"
NB_RUNTIME="${XDG_RUNTIME_DIR:-/tmp}/nebula"

mkdir -p "$NB_STATE" "$NB_CACHE" "$NB_THUMBS" "$NB_RUNTIME"

# defaults first, then the user's settings on top
WALL_DIR="$HOME/Pictures/Wallpapers"
TERMINAL="kitty"
WALL_TRANSITION="grow"
WALL_TRANSITION_DURATION="1.2"
WALL_TRANSITION_FPS="60"
OVERVIEW_BLUR=1
MATUGEN_SCHEME="scheme-tonal-spot"
BRIGHTNESS_STEP=5
VOLUME_STEP=5
OSD_DURATION=1.6
# menu bar: style (frame | floating | classic | pills | islands | notch | minimal), height, modules
BAR_STYLE=""            # empty — use the old FRAME key: 1 → frame, 0 → floating
BAR_HEIGHT=34
BAR_LEFT="logo workspaces window"
BAR_CENTER="media"
BAR_RIGHT="tray volume brightness language network battery control clock"
BAR_MEDIA_COVER=1
BAR_MEDIA_LEN=40
# desktop: frame around the screen, Dock, desktop clock
FRAME=1
FRAME_SIZE=8
DOCK="autohide"
DOCK_APPS="auto"
DESKTOP_CLOCK=1
DESK_CLOCK_POS="top"
DESK_CLOCK_SIZE=100
DESK_CLOCK_FONT=""
DESK_CLOCK_WEIGHT="light"
DESK_CLOCK_COLOR="light"
DESK_CLOCK_DATE=1
NIGHT_TEMP=4000
# menu bar clock
CLOCK_24H=1
CLOCK_SECONDS=0
CLOCK_DATE=1
# windows and animations
WIN_OPACITY=0.9
WIN_BORDER=1
WIN_RADIUS=14
WIN_GAPS=10
WIN_MAXIMIZED=1
ANIM_ENABLED=1
ANIM_SPEED=1.0
ECO=0
# fastfetch
FETCH_DIR="$HOME/Pictures/Fastfetch"
FETCH_MODE="fixed"
FETCH_SIZE=16
# web search from Search
SEARCH_URL="https://www.google.com/search?q="
# mouse and touchpad, hot corner (off | top-left | top-right | bottom-left | bottom-right)
TP_TAP=1
TP_NATURAL=1
TP_SPEED=0.15
TP_SCROLL=0.7
MOUSE_SPEED=0
MOUSE_NATURAL=0
FOCUS_FOLLOWS=1
HOT_CORNER="top-left"
# keyboard: comma-separated layouts · switch (caps | alt_shift | ctrl_shift | ralt | none)
KB_LAYOUTS="us,ru"
KB_SWITCH="caps"
# fun stuff: Search easter eggs · greeting at login · a new wallpaper at every login
FUN=1
GREETING=1
WALL_ON_LOGIN=0
# interface language: ru | en | auto (follow the system locale)
UI_LANG="auto"
# notifications: drawn by nb-shell (0 — leave them to mako or another daemon) ·
# seconds on screen (0 — until clicked) · corner (top-right | top-left)
NOTIFY=1
NOTIF_TIMEOUT=5
NOTIF_SOUND=0
NOTIF_POS="top-right"
# the Claude add-on (off until ticked in the installer or the settings):
# what Super+Shift+C opens (terminal | desktop), the Claude Code permission mode,
# continuing the last conversation in a folder, the "Claude" item in Dolphin's menu
CLAUDE=0
CLAUDE_OPEN="terminal"
CLAUDE_MODE="default"
CLAUDE_CONTINUE=0
CLAUDE_DOLPHIN=1
# shellcheck source=/dev/null
[ -f "$NB_DIR/settings.conf" ] && . "$NB_DIR/settings.conf"
case "$BAR_STYLE" in   # empty, or a value from an older version — go by the FRAME key
    frame|floating|classic|pills|islands|notch|minimal) ;;
    *) if [ "${FRAME:-1}" = 1 ]; then BAR_STYLE=frame; else BAR_STYLE=floating; fi ;;
esac

has() { command -v "$1" >/dev/null 2>&1; }

# ── language ──
# The scripts speak Russian in the source; i18n/en.tsv holds "russian<TAB>english" pairs.
# t "строка" prints the string in the user's language. The table loads on the first call.
case "$UI_LANG" in
    ru|en) NB_LANG=$UI_LANG ;;
    *) case "${LC_ALL:-${LC_MESSAGES:-$LANG}}" in ru*|uk*|be*) NB_LANG=ru ;; *) NB_LANG=en ;; esac ;;
esac
declare -gA NB_TR=()
t() {
    if [ "$NB_LANG" = ru ]; then printf '%s' "$1"; return; fi
    if [ ${#NB_TR[@]} -eq 0 ] && [ -f "$NB_DIR/i18n/en.tsv" ]; then
        local ru en
        while IFS=$'\t' read -r ru en; do
            [ -n "$en" ] && [ "${ru:0:1}" != "#" ] && NB_TR["${ru//\\n/$'\n'}"]="${en//\\n/$'\n'}"
        done < "$NB_DIR/i18n/en.tsv"
        NB_TR[__loaded]=1
    fi
    printf '%s' "${NB_TR[$1]:-$1}"
}
# tf "Файл не найден: %s" "$f" — the same, printf-style for strings with values in them
tf() { local f; f=$(t "$1"); shift; printf -- "$f" "$@"; }

nb_notify() { # nb_notify <title> <text> [icon]
    has notify-send || return 0
    notify-send -a Nebula -h string:x-nebula:1 ${3:+-i "$3"} "$1" "$2"
}

nb_current_theme() { cat "$NB_STATE/theme" 2>/dev/null || echo "catppuccin-mocha"; }
nb_current_wall()  { cat "$NB_STATE/wallpaper" 2>/dev/null; }

# Every wallpaper (full paths), sorted by name
nb_list_walls() {
    [ -d "$WALL_DIR" ] || return 0
    find -L "$WALL_DIR" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \
        -o -iname '*.webp' -o -iname '*.gif' -o -iname '*.bmp' -o -iname '*.avif' \) 2>/dev/null | sort -V
}

# Wallpapers along with their thumbnail paths: "<thumbnail>\t<file>". md5 is computed in one go in
# a single process — across hundreds of files that's dozens of times faster than nb_thumb_path in a loop
nb_list_walls_thumbs() {
    nb_list_walls | python3 -c '
import sys, hashlib
d, out = sys.argv[1].encode(), sys.stdout.buffer
for line in sys.stdin.buffer:
    f = line.rstrip(b"\n")
    out.write(d + b"/" + hashlib.md5(f).hexdigest().encode() + b".png\t" + f + b"\n")
' "$NB_THUMBS"
}

# Thumbnail path for a wallpaper file
nb_thumb_path() {
    local key
    key=$(printf '%s' "$1" | md5sum | cut -c1-32)
    printf '%s/%s.png' "$NB_THUMBS" "$key"
}

# Makes a 16:10 thumbnail (center crop). The UI rounds the corners itself
nb_make_thumb() { # nb_make_thumb <src> <dst>
    local src="$1" dst="$2" tmp="$2.tmp.png"
    magick "${src}[0]" -auto-orient -thumbnail '320x200^' -gravity center -extent 320x200 \
        -strip "$tmp" 2>/dev/null && mv -f "$tmp" "$dst"
    rm -f "$tmp"
}

# Writes KEY="value" into settings.conf: the line is edited in place, everything else is left alone
nb_set() { # nb_set <KEY> <value>
    local conf="$NB_DIR/settings.conf" val
    case "$2" in
        "$HOME")   val='$HOME' ;;
        "$HOME"/*) val='$HOME/'$(printf '%s' "${2#"$HOME"/}" | sed 's/[\\"$`]/\\&/g') ;;
        *)         val=$(printf '%s' "$2" | sed 's/[\\"$`]/\\&/g') ;;
    esac
    touch "$conf"
    NB_KEY="$1" NB_LINE="$1=\"$val\"" awk '
        $0 ~ "^[[:space:]]*" ENVIRON["NB_KEY"] "=" { if (!done) print ENVIRON["NB_LINE"]; done = 1; next }
        { print }
        END { if (!done) print ENVIRON["NB_LINE"] }' "$conf" > "$conf.nbtmp" && mv -f "$conf.nbtmp" "$conf"
    printf -v "$1" '%s' "$2"
}
