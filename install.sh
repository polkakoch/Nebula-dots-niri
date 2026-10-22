#!/usr/bin/env bash
# ┌──────────────────────────────────────────────────────────────────────┐
# │  Nebula — installer (niri · waybar · nb-shell · hyprlock)            │
# │                                                                      │
# │  ./install.sh                  interactive: arrows, Space, Enter     │
# │  ./install.sh --auto           everything by default, no questions   │
# │  ./install.sh --custom         straight to picking components        │
# │                                                                      │
# │  --lang en|ru         interface language                             │
# │  --no-packages        leave packages alone (configs only)            │
# │  --theme <id>         theme: matugen (from wallpaper), nord, …       │
# │  --bar <style>        frame floating classic islands pills notch     │
# │                       minimal                                        │
# │  --layouts us,ru      keyboard layouts                               │
# │  --switch caps        layout switch: caps alt_shift ctrl_shift ralt  │
# │  --wall-dir <dir>     wallpaper folder                               │
# │  --claude             turn on the Claude add-on                      │
# │  --no-fun             no easter eggs or login greeting               │
# │  --no-welcome         don't show the setup wizard on first login     │
# │  --no-reload          don't restart the running session              │
# │  --version            print the version                              │
# └──────────────────────────────────────────────────────────────────────┘
set -uo pipefail

SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/nebula"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$CONF/nebula-backup/$STAMP"
VERSION="$(cat "$SRC/VERSION" 2>/dev/null || echo dev)"
OLD_SETTINGS="$CONF/nebula/settings.conf"

MODE=""; PKGS=1; RELOAD=1; LANG_OPT=""
THEME=""; BAR=""; LAYOUTS=""; SWITCH=""; WALL_DIR_OPT=""; CLAUDE_OPT=""; FUN_OPT=""; WELCOME=""
while [ $# -gt 0 ]; do
    case "$1" in
        --auto|-y|--yes) MODE=auto ;;
        --custom)      MODE=custom ;;
        --lang)        LANG_OPT="${2:-}"; shift ;;
        --no-packages) PKGS=0 ;;
        --theme)       THEME="${2:-}"; shift ;;
        --bar)         BAR="${2:-}"; shift ;;
        --layouts)     LAYOUTS="${2:-}"; shift ;;
        --switch)      SWITCH="${2:-}"; shift ;;
        --wall-dir)    WALL_DIR_OPT="${2:-}"; shift ;;
        --claude)      CLAUDE_OPT=1 ;;
        --no-fun)      FUN_OPT=0 ;;
        --no-welcome)  WELCOME=0 ;;
        --no-reload)   RELOAD=0 ;;
        --version)     echo "Nebula $VERSION"; exit 0 ;;
        -h|--help)     sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1 (see --help)"; exit 1 ;;
    esac
    shift
done
# No terminal (curl | bash, CI) means there's nobody to ask
[ -t 0 ] && [ -t 1 ] || MODE=auto

# A value from an existing install, so an upgrade keeps what the user already picked
old() { # <KEY> <default>
    local v
    v=$(grep -E "^[[:space:]]*$1=" "$OLD_SETTINGS" 2>/dev/null | tail -1 | cut -d= -f2- | sed 's/^"//; s/"[[:space:]]*\(#.*\)\{0,1\}$//')
    printf '%s' "${v:-$2}"
}
UPGRADE=0; [ -f "$OLD_SETTINGS" ] && UPGRADE=1

# ── language ───────────────────────────────────────────────────────
# Same table the installed scripts use: nebula/i18n/en.tsv, "russian<TAB>english".
# Versions before 1.1 only spoke Russian, so an upgrade without UI_LANG stays Russian.
case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in ru*|uk*|be*) SYS_LANG=ru ;; *) SYS_LANG=en ;; esac
if [ "$UPGRADE" = 1 ]; then NB_LANG=$(old UI_LANG ru); else NB_LANG=$SYS_LANG; fi
[ "$NB_LANG" = auto ] && NB_LANG=$SYS_LANG
[ -n "$LANG_OPT" ] && NB_LANG=$LANG_OPT
case "$NB_LANG" in ru|en) ;; *) NB_LANG=en ;; esac

declare -A NB_TR=()
t() {
    if [ "$NB_LANG" = ru ]; then printf '%s' "$1"; return; fi
    if [ ${#NB_TR[@]} -eq 0 ]; then
        local ru en
        while IFS=$'\t' read -r ru en; do
            [ -n "$en" ] && [ "${ru:0:1}" != "#" ] && NB_TR["${ru//\\n/$'\n'}"]="${en//\\n/$'\n'}"
        done < "$SRC/nebula/i18n/en.tsv"
        NB_TR[__loaded]=1
    fi
    printf '%s' "${NB_TR[$1]:-$1}"
}
tf() { local f; f=$(t "$1"); shift; printf -- "$f" "$@"; }

# ── output ─────────────────────────────────────────────────────────
if [ -t 1 ]; then
    B=$'\e[1m'; D=$'\e[2m'; R=$'\e[0m'; C=$'\e[38;5;141m'; G=$'\e[38;5;114m'; Y=$'\e[38;5;221m'; E=$'\e[38;5;203m'
else B=; D=; R=; C=; G=; Y=; E=; fi
step() { printf '\n%s◆%s %s%s%s\n' "$C" "$R" "$B" "$*" "$R"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$R" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$R" "$*"; }
die()  { printf '  %s✗ %s%s\n' "$E" "$*" "$R"; exit 1; }
ask()  { [ "$MODE" = auto ] && return 0; local a; read -r -p "  $1 [Y/n] " a; [[ -z "$a" || "$a" =~ ^[YyДд] ]]; }

# ── the picker: ↑↓ to move, Space to tick, Enter to go on ──────────
cursor_on()  { printf '\e[?25h'; }
cursor_off() { printf '\e[?25l'; }
trap 'cursor_on; stty echo 2>/dev/null' EXIT
trap 'cursor_on; echo; exit 130' INT

read_key() {
    local k rest
    IFS= read -rsn1 k || { KEY=enter; return; }
    if [ "$k" = $'\e' ]; then
        IFS= read -rsn2 -t 0.05 rest
        case "$rest" in '[A') KEY=up ;; '[B') KEY=down ;; '[C') KEY=right ;; '[D') KEY=left ;;
            '') KEY=esc ;; *) KEY=other ;; esac
    elif [ -z "$k" ]; then KEY=enter
    elif [ "$k" = " " ]; then KEY=space
    else KEY="$k"; fi
}

term_rows() { local r; r=$(stty size 2>/dev/null | cut -d' ' -f1); echo "${r:-24}"; }

screen() { # <step> <title> [hint]
    printf '\n  %s%s%s  %s%s%s\n' "$D" "$1" "$R" "$B" "$2" "$R"
    [ -n "${3:-}" ] && printf '  %s%s%s\n' "$D" "$3" "$R"
    echo
}

# Pick one. Items look like "title|description"; the answer's index lands in PICK.
choose() { # <default index> <items…>
    local sel="$1"; shift
    local items=("$@") n=$# h top=0 i drawn=0 title desc
    h=$(( $(term_rows) - 9 )); [ "$h" -lt 5 ] && h=5; [ "$h" -gt "$n" ] && h=$n
    cursor_off
    while :; do
        [ "$sel" -lt "$top" ] && top=$sel
        [ "$sel" -ge $((top + h)) ] && top=$((sel - h + 1))
        [ "$drawn" -gt 0 ] && printf '\e[%dA' "$drawn"
        drawn=0
        for ((i = top; i < top + h; i++)); do
            IFS='|' read -r title desc <<<"${items[$i]}"
            if [ "$i" -eq "$sel" ]; then
                printf '\e[2K  %s❯ %s%s%s' "$C" "$B" "$title" "$R"
            else
                printf '\e[2K    %s' "$title"
            fi
            [ -n "$desc" ] && printf '  %s%s%s' "$D" "$desc" "$R"
            printf '\n'; drawn=$((drawn + 1))
        done
        if [ "$n" -gt "$h" ]; then
            printf '\e[2K    %s%s%s\n' "$D" "$(tf "%d из %d · ↑↓ листать" $((sel + 1)) "$n")" "$R"; drawn=$((drawn + 1))
        fi
        read_key
        case "$KEY" in
            up|k)   sel=$(( (sel - 1 + n) % n )) ;;
            down|j) sel=$(( (sel + 1) % n )) ;;
            enter|right|l) break ;;
            [1-9])  [ "$KEY" -le "$n" ] && { sel=$((KEY - 1)); } ;;
        esac
    done
    cursor_on
    PICK=$sel
}

# Pick several. Items look like "id|0/1|title|description"; the answer is the CHECKED array (0/1).
checklist() {
    local items=("$@") n=$# sel=0 i drawn=0 id on title desc mark
    CHECKED=()
    for ((i = 0; i < n; i++)); do IFS='|' read -r _ on _ _ <<<"${items[$i]}"; CHECKED[$i]=$on; done
    cursor_off
    while :; do
        [ "$drawn" -gt 0 ] && printf '\e[%dA' "$drawn"
        drawn=0
        for ((i = 0; i < n; i++)); do
            IFS='|' read -r id on title desc <<<"${items[$i]}"
            if [ "${CHECKED[$i]}" = 1 ]; then mark="${G}◉${R}"; else mark="${D}○${R}"; fi
            if [ "$i" -eq "$sel" ]; then printf '\e[2K  %s❯%s %s %s%s%s' "$C" "$R" "$mark" "$B" "$title" "$R"
            else printf '\e[2K    %s %s' "$mark" "$title"; fi
            [ -n "$desc" ] && printf '  %s%s%s' "$D" "$desc" "$R"
            printf '\n'; drawn=$((drawn + 1))
        done
        printf '\e[2K    %s%s%s\n' "$D" "$(t "Пробел — отметить · a — всё · Enter — дальше")" "$R"; drawn=$((drawn + 1))
        read_key
        case "$KEY" in
            up|k)   sel=$(( (sel - 1 + n) % n )) ;;
            down|j) sel=$(( (sel + 1) % n )) ;;
            space|x) CHECKED[$sel]=$(( 1 - CHECKED[$sel] )) ;;
            a) local all=1; for ((i = 0; i < n; i++)); do [ "${CHECKED[$i]}" = 1 ] || all=0; done
               for ((i = 0; i < n; i++)); do CHECKED[$i]=$((1 - all)); done ;;
            enter) break ;;
        esac
    done
    cursor_on
}

# A theme's colors as little truecolor dots, so you can pick with your eyes
swatch() { # <theme file>
    local k v out=""
    for k in bg accent accent2 red green yellow blue; do
        v=$(grep -oE "(^|[[:space:]])$k=\"?#[0-9a-fA-F]{6}" "$1" | head -1 | grep -oE '#[0-9a-fA-F]{6}')
        [ -n "$v" ] || continue
        out+=$(printf '\e[38;2;%d;%d;%dm●' "0x${v:1:2}" "0x${v:3:2}" "0x${v:5:2}")
    done
    printf '%s\e[0m' "$out"
}

# ── banner ─────────────────────────────────────────────────────────
cat <<EOF
${C}
   ███╗   ██╗███████╗██████╗ ██╗   ██╗██╗      █████╗
   ████╗  ██║██╔════╝██╔══██╗██║   ██║██║     ██╔══██╗
   ██╔██╗ ██║█████╗  ██████╔╝██║   ██║██║     ███████║
   ██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║██║     ██╔══██║
   ██║ ╚████║███████╗██████╔╝╚██████╔╝███████╗██║  ██║
   ╚═╝  ╚═══╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝${R}
   ${D}v$VERSION · niri · waybar · nb-shell · awww · $(t "22 темы")${R}
EOF

[ "$(id -u)" -eq 0 ] && die "$(t "Запускайте от обычного пользователя, не от root (sudo спросится сам).")"
[ -d "$SRC/nebula" ] && [ -d "$SRC/config" ] || die "$(t "Не найдены папки nebula/ и config/ рядом с install.sh")"

# Language comes first, asked in both languages at once
if [ -z "$MODE" ] && [ -z "$LANG_OPT" ]; then
    screen "" "Language · Язык"
    choose "$([ "$NB_LANG" = ru ] && echo 1 || echo 0)" "English|" "Русский|"
    NB_LANG=$([ "$PICK" = 1 ] && echo ru || echo en)
fi

[ "$UPGRADE" = 1 ] && printf '\n   %s%s%s\n' "$D" "$(t "Nebula уже стоит — обновлю, ваши настройки сохранятся.")" "$R"

# ── components ─────────────────────────────────────────────────────
CORE_PKGS=(
    niri xwayland-satellite xdg-desktop-portal-gnome xdg-desktop-portal-gtk
    waybar awww wlsunset brightnessctl wireplumber pipewire-pulse libpulse playerctl pavucontrol
    power-profiles-daemon imagemagick matugen jq python python-gobject python-cairo gtk4 gtk4-layer-shell
    libnm xdg-utils polkit-gnome network-manager-applet ttf-jetbrains-mono-nerd inter-font papirus-icon-theme
)
# id|on by default|title|description|packages
COMPONENTS=(
    "notify|1|$(t "Уведомления")|$(t "свои, стеклянные (mako — запасной)")|mako libnotify"
    "lock|1|$(t "Блокировка и сон")|hyprlock + swayidle|hyprlock swayidle"
    "kitty|1|$(t "Терминал kitty")|$(t "цвета темы, блюр")|kitty"
    "fetch|1|$(t "fastfetch с картинкой")|$(t "при открытии терминала")|fastfetch"
    "clip|1|$(t "История буфера")|cliphist, Super+V|cliphist wl-clipboard"
    "shots|1|$(t "Скриншоты")|$(t "grim, slurp, редактор satty")|grim slurp satty wl-clipboard"
    "bt|1|Bluetooth|blueman|blueman bluez-utils"
    "qt|1|$(t "Цвета для Qt/KDE")|$(t "Dolphin и др. в цветах темы")|plasma-integration"
    "extras|1|btop|$(t "клик по CPU/памяти")|btop"
    "dolphin|1|$(t "Меню «Nebula» в Dolphin")|$(t "ПКМ по картинке → обои, аватар")|"
    "locale|$([ "$NB_LANG" = ru ] && echo 1 || echo 0)|$(t "Русская локаль")|$(t "даты по-русски, нужен sudo")|"
    "claude|0|$(t "Дополнение Claude")|Claude Code / Desktop, Super+Shift+C|"
)
declare -A ON
for c in "${COMPONENTS[@]}"; do IFS='|' read -r id def _ _ _ <<<"$c"; ON[$id]=$def; done
on() { [ "${ON[$1]:-0}" = 1 ]; }

# On an upgrade, start from what was already chosen
if [ "$UPGRADE" = 1 ]; then
    if grep -qE '^[[:space:]]*CLAUDE=' "$OLD_SETTINGS"; then ON[claude]=$(old CLAUDE 0)
    elif grep -qE '^[[:space:]]*CLAUDE_OPEN=' "$OLD_SETTINGS"; then ON[claude]=1   # set up before the switch existed
    fi
    ON[notify]=$(old NOTIFY 1)
fi
[ -n "$CLAUDE_OPT" ] && ON[claude]=1

THEMES_IDS=(); THEMES_ROWS=()
build_theme_list() {
    local f id name
    THEMES_IDS=(matugen); THEMES_ROWS=("$(t "Из обоев")|$(t "цвета подстраиваются под картинку")")
    for f in "$SRC/nebula/themes/"*.theme; do
        id=$(basename "$f" .theme)
        name=$(grep -m1 '^name=' "$f" | cut -d'"' -f2)
        THEMES_IDS+=("$id"); THEMES_ROWS+=("$(swatch "$f")  ${name:-$id}|$(grep -m1 '^mode=' "$f" | grep -q light && t "светлая")")
    done
}
BAR_IDS=(frame floating classic islands pills notch minimal)
BAR_ROWS=("$(t "Рамка")|$(t "панель переходит в рамку вокруг экрана")" "$(t "Плавающая")|$(t "стекло с блюром и отступами")"
          "$(t "Классика")|$(t "во всю ширину, полупрозрачная")" "$(t "Острова")|$(t "три группы: слева, центр, справа")"
          "$(t "Таблетки")|$(t "каждый модуль отдельно")" "$(t "Чёлка")|$(t "центр свисает из верхнего края")"
          "$(t "Минимал")|$(t "без фона")")
LAYOUT_IDS=(us,ru us,ru,ua us,ua us custom)
LAYOUT_ROWS=("English + Русский" "English + Русский + Українська" "English + Українська" "$(t "Только English")"
             "$(t "Свои…")|$(t "например us,de или us,ru,by")")
SWITCH_IDS=(caps alt_shift ctrl_shift ralt)
SWITCH_ROWS=("Caps Lock|$(t "Shift+Caps — настоящий Caps")" "Alt + Shift" "Ctrl + Shift" "$(t "Правый Alt")")

index_of() { local want="$1" i=0; shift; for x in "$@"; do [ "$x" = "$want" ] && { echo $i; return; }; i=$((i + 1)); done; echo 0; }
yesno() { [ "$1" = 1 ] && t "да" || t "нет"; }

# ── questions ──────────────────────────────────────────────────────
if [ -z "$MODE" ]; then
    screen "" "$(t "Как ставить?")" "$(t "↑↓ — выбрать, Enter — дальше")"
    choose 0 "$(t "Быстро")|$(t "всё по умолчанию, недостающие пакеты доустановятся сами")" \
             "$(t "Выборочно")|$(t "компоненты, тема, строка меню, клавиатура, приколы")" \
             "$(t "Только конфиги")|$(t "пакеты не трогать (уже всё стоит или не Arch)")"
    case "$PICK" in 0) MODE=auto ;; 1) MODE=custom ;; 2) MODE=custom; PKGS=0 ;; esac
fi

if [ "$MODE" = custom ]; then
    TOTAL=7
    rows=()
    for c in "${COMPONENTS[@]}"; do IFS='|' read -r id _ title desc _ <<<"$c"; rows+=("$id|${ON[$id]}|$title|$desc"); done
    screen "1/$TOTAL" "$(t "Компоненты")" "$(t "Ядро — niri, строка меню, поиск, пункт управления — ставится всегда")"
    checklist "${rows[@]}"
    i=0; for c in "${COMPONENTS[@]}"; do IFS='|' read -r id _ <<<"$c"; ON[$id]=${CHECKED[$i]}; i=$((i + 1)); done

    if [ -z "$THEME" ]; then
        build_theme_list
        screen "2/$TOTAL" "$(t "Тема")" "$(t "Потом меняется: Super+Shift+T")"
        choose "$(index_of "$(cat "$STATE_DIR/theme" 2>/dev/null || echo matugen)" "${THEMES_IDS[@]}")" "${THEMES_ROWS[@]}"
        THEME=${THEMES_IDS[$PICK]}
    fi
    if [ -z "$BAR" ]; then
        screen "3/$TOTAL" "$(t "Строка меню")" "$(t "Потом: пункт управления → Строка меню")"
        choose "$(index_of "$(old BAR_STYLE frame)" "${BAR_IDS[@]}")" "${BAR_ROWS[@]}"
        BAR=${BAR_IDS[$PICK]}
    fi
    if [ -z "$LAYOUTS" ]; then
        screen "4/$TOTAL" "$(t "Языки клавиатуры")"
        choose "$(index_of "$(old KB_LAYOUTS us,ru)" "${LAYOUT_IDS[@]}")" "${LAYOUT_ROWS[@]}"
        LAYOUTS=${LAYOUT_IDS[$PICK]}
        if [ "$LAYOUTS" = custom ]; then
            read -r -e -i "us,ru" -p "  $(t "Раскладки через запятую: ")" LAYOUTS
        fi
    fi
    if [ -z "$SWITCH" ] && [[ "$LAYOUTS" == *,* ]]; then
        screen "5/$TOTAL" "$(t "Смена языка")"
        choose "$(index_of "$(old KB_SWITCH caps)" "${SWITCH_IDS[@]}")" "${SWITCH_ROWS[@]}"
        SWITCH=${SWITCH_IDS[$PICK]}
    fi
    if [ -z "$WALL_DIR_OPT" ]; then
        screen "6/$TOTAL" "$(t "Папка с обоями")" "$(t "Если пусто — положу туда набор градиентных обоев")"
        def=$(old WALL_DIR '$HOME/Pictures/Wallpapers'); def=${def//\$HOME/$HOME}
        read -r -e -i "${def/#$HOME/\~}" -p "  $(t "Папка: ")" WALL_DIR_OPT
        WALL_DIR_OPT=${WALL_DIR_OPT/#\~/$HOME}
    fi
    if [ -z "$FUN_OPT" ]; then
        screen "7/$TOTAL" "$(t "Приколы")"
        checklist "fun|$(old FUN 1)|$(t "Пасхалки в поиске")|$(t "пароль, помидор, погода, монетка, кубик, таймер, Konami")" \
                  "greet|$(old GREETING 1)|$(t "Приветствие при входе")|$(t "«Доброе утро, …» и совет дня")" \
                  "wall|$(old WALL_ON_LOGIN 0)|$(t "Новые обои при каждом входе")|$(t "случайные из папки")"
        FUN_OPT=${CHECKED[0]}; GREET_OPT=${CHECKED[1]}; WALLLOGIN_OPT=${CHECKED[2]}
    fi
    if [ -z "$WELCOME" ]; then
        screen "" "$(t "Мастер настройки при первом входе?")" "$(t "Тема, обои, строка меню, клавиатура — по шагам, уже в niri")"
        choose $([ "$UPGRADE" = 1 ] && echo 1 || echo 0) "$(t "Показать")|$(t "рекомендую для новой установки")" "$(t "Не нужно")"
        WELCOME=$((1 - PICK))
    fi
fi

# Defaults for the quick install and anything that wasn't asked
[ -n "$WELCOME" ] || WELCOME=$((1 - UPGRADE))

echo
echo "  ${B}$(t "Будет сделано:")${R}"
[ "$PKGS" = 1 ] && echo "   • $(t "недостающие пакеты (pacman; из AUR — через yay/paru)")"
echo "   • $(t "копия текущих конфигов") → ${BACKUP/#$HOME/~}"
echo "   • niri, waybar, nb-shell$(on lock && echo ", hyprlock, swayidle")$(on fetch && echo ", fastfetch")$(on kitty && echo ", kitty ($(t "только цвета"))")"
echo "   • $(t "язык"): $([ "$NB_LANG" = ru ] && echo "Русский" || echo "English")"
[ -n "$THEME" ] && echo "   • $(t "тема"): $THEME"
[ -n "$BAR" ] && echo "   • $(t "строка меню"): $BAR"
[ -n "$LAYOUTS" ] && echo "   • $(t "раскладки"): $LAYOUTS${SWITCH:+ · $(t "переключение"): $SWITCH}"
on claude && echo "   • $(t "дополнение Claude")"
[ "$WELCOME" = 1 ] && echo "   • $(t "мастер настройки при первом входе")"
if [ "$MODE" != auto ]; then
    echo
    choose 0 "$(t "Установить")" "$(t "Отмена")"
    [ "$PICK" = 0 ] || exit 0
fi

# ── 1. packages ────────────────────────────────────────────────────
PACKAGES=("${CORE_PKGS[@]}")
for c in "${COMPONENTS[@]}"; do
    IFS='|' read -r id _ _ _ pk <<<"$c"
    on "$id" && [ -n "$pk" ] && read -ra extra <<<"$pk" && PACKAGES+=("${extra[@]}")
done
mapfile -t PACKAGES < <(printf '%s\n' "${PACKAGES[@]}" | awk '!seen[$0]++')

aur_helper() { for h in paru yay; do command -v "$h" >/dev/null && { echo "$h"; return; }; done; }

install_yay() {
    step "$(t "AUR-помощник yay")"
    sudo pacman -S --needed --noconfirm git base-devel || return 1
    local tmp; tmp=$(mktemp -d)
    git clone --depth 1 https://aur.archlinux.org/yay-bin.git "$tmp/yay-bin" >/dev/null 2>&1 &&
        (cd "$tmp/yay-bin" && makepkg -si --noconfirm >/dev/null 2>&1)
    local rc=$?
    rm -rf "$tmp"
    [ $rc -eq 0 ] && ok "$(t "yay установлен")" || warn "$(t "не удалось собрать yay")"
    return $rc
}

if [ "$PKGS" = 1 ]; then
    step "$(t "Пакеты")"
    if ! command -v pacman >/dev/null; then
        warn "$(t "это не Arch (нет pacman) — поставьте пакеты сами:")"
        echo "    ${PACKAGES[*]}"
    else
        missing=(); repo=(); aur=()
        for p in "${PACKAGES[@]}"; do pacman -Q "$p" >/dev/null 2>&1 || missing+=("$p"); done
        ok "$(tf "уже установлено: %d из %d" $(( ${#PACKAGES[@]} - ${#missing[@]} )) ${#PACKAGES[@]})"
        for p in "${missing[@]}"; do
            if pacman -Si "$p" >/dev/null 2>&1; then repo+=("$p"); else aur+=("$p"); fi
        done
        if [ ${#repo[@]} -gt 0 ]; then
            echo "  $(t "Из репозиториев:") ${repo[*]}"
            flags=(--needed); [ "$MODE" = auto ] && flags+=(--noconfirm)
            if sudo pacman -S "${flags[@]}" "${repo[@]}"; then ok "$(tf "установлено: %d" ${#repo[@]})"
            else warn "$(t "pacman завершился с ошибкой — продолжаю, но что-то может не работать")"; fi
        fi
        if [ ${#aur[@]} -gt 0 ]; then
            echo "  $(t "Из AUR:") ${aur[*]}"
            helper=$(aur_helper)
            if [ -z "$helper" ] && { [ "$MODE" = auto ] || ask "$(t "AUR-помощника нет. Поставить yay?")"; }; then
                install_yay && helper=yay
            fi
            if [ -n "$helper" ]; then
                flags=(--needed); [ "$MODE" = auto ] && flags+=(--noconfirm)
                "$helper" -S "${flags[@]}" "${aur[@]}" && ok "$(tf "из AUR: %d" ${#aur[@]})" || warn "$(tf "%s завершился с ошибкой" "$helper")"
            else
                warn "$(t "без AUR-помощника не поставить:") ${aur[*]}"
            fi
        fi
        [ ${#missing[@]} -eq 0 ] && ok "$(t "всё нужное уже есть")"
    fi

    # Russian locale, for dates in the bar and on the lock screen
    if on locale && ! locale -a 2>/dev/null | grep -qiE '^ru_RU\.utf-?8$'; then
        step "$(t "Локаль ru_RU.UTF-8 (даты на русском)")"
        if grep -qE '^#\s*ru_RU\.UTF-8 UTF-8' /etc/locale.gen 2>/dev/null; then
            sudo sed -i -E 's/^#\s*(ru_RU\.UTF-8 UTF-8)/\1/' /etc/locale.gen && sudo locale-gen >/dev/null \
                && ok "$(t "локаль сгенерирована")" || warn "$(t "не удалось сгенерировать локаль")"
        else
            warn "$(t "ru_RU.UTF-8 нет в /etc/locale.gen — пропускаю")"
        fi
    fi
fi

# ── 2. backup ──────────────────────────────────────────────────────
step "$(t "Резервная копия") → ${BACKUP/#$HOME/~}"
mkdir -p "$BACKUP"
for p in niri waybar mako swayosd swayidle hypr/hyprlock.conf kitty/kitty.conf kdeglobals fastfetch nebula; do
    if [ -e "$CONF/$p" ]; then
        mkdir -p "$BACKUP/$(dirname "$p")"
        cp -a "$CONF/$p" "$BACKUP/$p"
        ok "$p"
    fi
done
echo "$BACKUP" > "$CONF/nebula-backup/latest"

# ── 3. Nebula itself ───────────────────────────────────────────────
step "$(t "Скрипты и темы") → ~/.config/nebula"
mkdir -p "$CONF/nebula"
# never overwrite the user's own settings
keep_settings=""
[ -f "$CONF/nebula/settings.conf" ] && keep_settings=$(cat "$CONF/nebula/settings.conf")
cp -a "$SRC/nebula/." "$CONF/nebula/"
cp -a "$SRC/VERSION" "$CONF/nebula/VERSION" 2>/dev/null
rm -rf "$CONF/nebula/shell/__pycache__"
[ -n "$keep_settings" ] && printf '%s\n' "$keep_settings" > "$CONF/nebula/settings.conf" && ok "$(t "settings.conf сохранён")"
chmod +x "$CONF/nebula/bin/"*
mkdir -p "$HOME/.local/bin"
for f in "$CONF/nebula/bin/"nb-*; do ln -sfn "$f" "$HOME/.local/bin/$(basename "$f")"; done
ok "$(t "команды nb-* доступны в ~/.local/bin")"

# ── 4. app configs ─────────────────────────────────────────────────
step "$(t "Конфиги программ")"
install_dir() { # <folder in config/> — replaced wholesale (the old one is in the backup)
    rm -rf "${CONF:?}/$1"
    mkdir -p "$CONF/$1"
    cp -a "$SRC/config/$1/." "$CONF/$1/"
    ok "$1"
}

# niri: carry over the user's own user.kdl and monitor setup
old_user=""; [ -f "$CONF/niri/conf.d/user.kdl" ] && old_user=$(cat "$CONF/niri/conf.d/user.kdl")
old_outputs=""; [ -f "$CONF/niri/conf.d/outputs.kdl" ] && grep -q '^output' "$CONF/niri/conf.d/outputs.kdl" && old_outputs=$(cat "$CONF/niri/conf.d/outputs.kdl")
install_dir niri
[ -n "$old_user" ] && printf '%s\n' "$old_user" > "$CONF/niri/conf.d/user.kdl"
if [ -n "$old_outputs" ]; then
    printf '%s\n' "$old_outputs" > "$CONF/niri/conf.d/outputs.kdl"
elif command -v niri >/dev/null && niri msg -j outputs >/dev/null 2>&1; then
    {
        echo "// Monitors, copied from the running session by the installer. List them with: niri msg outputs"
        niri msg -j outputs | jq -r '
          def tf: {"Normal":"normal","_90":"90","_180":"180","_270":"270","Flipped":"flipped",
                   "Flipped90":"flipped-90","Flipped180":"flipped-180","Flipped270":"flipped-270"}[.] // "normal";
          to_entries[] | .value | select(.current_mode != null) |
          (.modes[.current_mode]) as $m |
          "output \"\(.name)\" {\n" +
          "    mode \"\($m.width)x\($m.height)@\($m.refresh_rate / 1000 | floor).\(("000" + ($m.refresh_rate % 1000 | tostring))[-3:])\"\n" +
          "    scale \(.logical.scale)\n" +
          (if (.logical.transform | tf) != "normal" then "    transform \"\(.logical.transform | tf)\"\n" else "" end) +
          "    position x=\(.logical.x) y=\(.logical.y)\n}"'
    } > "$CONF/niri/conf.d/outputs.kdl" && ok "$(t "мониторы перенесены из текущей сессии")"
fi

install_dir waybar
if on lock; then
    install_dir swayidle
    mkdir -p "$CONF/hypr"
    cp -a "$SRC/config/hypr/hyprlock.conf" "$CONF/hypr/hyprlock.conf"; ok "hypr/hyprlock.conf"
fi
# mako only steps in when nb-shell isn't drawing notifications; it still gets a themed config
mkdir -p "$CONF/mako"
[ -f "$CONF/mako/user.conf" ] || printf '# Your own mako settings (included at the end of the config)\n' > "$CONF/mako/user.conf"

# kitty: only hook up the color file, leave the rest of the user's config alone
if on kitty; then
    mkdir -p "$CONF/kitty"
    KC="$CONF/kitty/kitty.conf"
    if [ ! -f "$KC" ]; then
        printf 'font_family      JetBrainsMono Nerd Font\nfont_size        11.0\nwindow_padding_width 10\nconfirm_os_window_close 0\n' > "$KC"
    fi
    if ! grep -q '^include nebula-theme.conf' "$KC"; then
        printf '\n# Nebula: colors of the current theme (keep this as the last line)\ninclude nebula-theme.conf\n' >> "$KC"
    fi
    ok "$(t "kitty (подключены цвета темы)")"
fi

# fastfetch: nb-theme builds config.jsonc (colors + picture); fastfetch.sh wraps nb-fetch
# so that old calls from ~/.zshrc still show the chosen picture
if on fetch; then
    mkdir -p "$CONF/fastfetch"
    cat > "$CONF/fastfetch/fastfetch.sh" <<'FF'
#!/usr/bin/env bash
# Nebula: fastfetch with the chosen picture (nb-fetch). Change it: nb-fetch next, or Control Center → Fastfetch
exec "$HOME/.config/nebula/bin/nb-fetch" show
FF
    chmod +x "$CONF/fastfetch/fastfetch.sh"
    ok "$(t "fastfetch (картинки — в ~/Pictures/Fastfetch)")"
fi

# Dolphin: right-click a picture → Nebula → fastfetch / wallpaper / profile photo
SM="${XDG_DATA_HOME:-$HOME/.local/share}/kio/servicemenus"
if on dolphin; then
    mkdir -p "$SM"
    sed "s|@HOME@|$HOME|g" "$SRC/config/servicemenus/nebula.desktop" > "$SM/nebula.desktop"
    chmod +x "$SM/nebula.desktop"
    ok "$(t "меню Dolphin «Nebula» (ПКМ по картинке)")"
else
    rm -f "$SM/nebula.desktop"
fi

# ── 5. settings from the answers ───────────────────────────────────
step "$(t "Настройки")"
setk() { NB_NO_RELOAD=1 "$CONF/nebula/bin/nb-settings" set "$1" "$2" >/dev/null && ok "$3"; }
setk UI_LANG "$NB_LANG" "$(t "язык"): $([ "$NB_LANG" = ru ] && echo "Русский" || echo "English")"
[ -n "$WALL_DIR_OPT" ] && setk WALL_DIR "$WALL_DIR_OPT" "$(t "обои"): ${WALL_DIR_OPT/#$HOME/~}"
[ -n "$BAR" ]       && setk BAR_STYLE "$BAR" "$(t "строка меню"): $BAR"
[ -n "$LAYOUTS" ]   && setk KB_LAYOUTS "$LAYOUTS" "$(t "раскладки"): $LAYOUTS"
[ -n "$SWITCH" ]    && setk KB_SWITCH "$SWITCH" "$(t "смена языка"): $SWITCH"
[ -n "$FUN_OPT" ]   && setk FUN "$FUN_OPT" "$(t "пасхалки"): $(yesno "$FUN_OPT")"
[ -n "${GREET_OPT:-}" ] && setk GREETING "$GREET_OPT" "$(t "приветствие"): $(yesno "$GREET_OPT")"
[ "$FUN_OPT" = 0 ] && [ -z "${GREET_OPT:-}" ] && setk GREETING 0 "$(t "приветствие"): $(yesno 0)"
[ -n "${WALLLOGIN_OPT:-}" ] && setk WALL_ON_LOGIN "$WALLLOGIN_OPT" "$(t "новые обои при входе"): $(yesno "$WALLLOGIN_OPT")"
setk NOTIFY "$(on notify && echo 1 || echo 0)" "$(t "уведомления Nebula"): $(on notify && yesno 1 || yesno 0)"
setk CLAUDE "$(on claude && echo 1 || echo 0)" "$(t "дополнение Claude"): $(on claude && yesno 1 || yesno 0)"
NB_NO_RELOAD=1 "$CONF/nebula/bin/nb-settings" apply && ok "$(t "nebula-settings для niri и waybar")"
# hotkey titles, bar tooltips and the like in the chosen language
"$CONF/nebula/bin/nb-settings" localize >/dev/null && ok "$(t "подписи в конфигах — на выбранном языке")"
. "$CONF/nebula/lib.sh"
mkdir -p "$FETCH_DIR" 2>/dev/null

# The bar clock asks for ru_RU.UTF-8 in Russian; without that locale the module won't even start
if [ "$NB_LANG" = ru ] && ! locale -a 2>/dev/null | grep -qiE '^ru_RU\.utf-?8$'; then
    warn "$(t "русской локали нет — дата на панели будет на английском")"
fi

# ── 6. wallpaper ───────────────────────────────────────────────────
step "$(t "Обои")"
if [ -z "$(nb_list_walls | head -1)" ]; then
    warn "$(tf "в %s нет картинок — создаю набор градиентных обоев" "${WALL_DIR/#$HOME/~}")"
    mkdir -p "$WALL_DIR/nebula"
    i=0
    for pair in "#1e1e2e #cba6f7 #89b4fa" "#1a1b26 #7aa2f7 #bb9af7" "#191724 #eb6f92 #c4a7e7" \
                "#2d353b #a7c080 #7fbbb3" "#282828 #fe8019 #fabd2f" "#0f1020 #36f9f6 #ff7edb"; do
        set -- $pair; i=$((i + 1))
        magick -size 1920x1080 xc:"$1" \
            \( -size 1800x1800 radial-gradient:"$2"-none -channel A -evaluate multiply 0.6 +channel \) -geometry -500-700 -composite \
            \( -size 1600x1600 radial-gradient:"$3"-none -channel A -evaluate multiply 0.45 +channel \) -geometry +900+200 -composite \
            -attenuate 0.12 +noise Gaussian "$WALL_DIR/nebula/nebula-$i.png" 2>/dev/null
    done
    ok "$(tf "создано: %d в %s" "$i" "${WALL_DIR/#$HOME/~}/nebula")"
fi
if [ -z "$(nb_current_wall)" ] || [ ! -f "$(nb_current_wall)" ]; then
    cur=$(awww query 2>/dev/null | sed -n 's/.*currently displaying: image: //p' | head -1)
    [ -f "$cur" ] || cur=$(nb_list_walls | head -1)
    [ -n "$cur" ] && echo "$cur" > "$NB_STATE/wallpaper" && ln -sfn "$cur" "$NB_CACHE/wallpaper"
fi
ok "$(t "текущие обои:") $(basename "$(nb_current_wall)" 2>/dev/null)"
nice -n 19 "$CONF/nebula/bin/nb-thumbs" >/dev/null 2>&1 &
ok "$(t "превью для меню готовятся в фоне")"

# ── 7. theme ───────────────────────────────────────────────────────
step "$(t "Тема")"
[ -z "$THEME" ] && THEME=$(cat "$NB_STATE/theme" 2>/dev/null || echo matugen)
[ -f "$CONF/nebula/themes/$THEME.theme" ] || [ "$THEME" = matugen ] || THEME=catppuccin-mocha
in_niri=0; [ -n "${NIRI_SOCKET:-}" ] && niri msg version >/dev/null 2>&1 && in_niri=1
if [ "$in_niri" = 1 ] && [ "$RELOAD" = 1 ]; then
    "$CONF/nebula/bin/nb-theme" apply "$THEME" --quiet
else
    NB_NO_RELOAD=1 "$CONF/nebula/bin/nb-theme" apply "$THEME" --quiet
fi
if [ "$THEME" = matugen ]; then ok "$(t "Из обоев (цвета подстраиваются под картинку)")"
else ok "$(grep -m1 '^name=' "$CONF/nebula/themes/$THEME.theme" | cut -d'"' -f2)"; fi

if command -v niri >/dev/null; then
    if niri validate -c "$CONF/niri/config.kdl" >/dev/null 2>&1; then ok "$(t "конфиг niri валиден")"
    else warn "$(t "niri validate нашёл ошибку:")"; niri validate -c "$CONF/niri/config.kdl" 2>&1 | tail -15; fi
fi

# the first-run wizard shows up at login until the welcome-done mark exists
mkdir -p "$NB_STATE"
if [ "$WELCOME" = 1 ]; then rm -f "$NB_STATE/welcome-done"; else echo 1 > "$NB_STATE/welcome-done"; fi

# ── 8. restart the running session ─────────────────────────────────
if [ "$in_niri" = 1 ] && [ "$RELOAD" = 1 ]; then
    step "$(t "Применяю в текущей сессии")"
    # niri re-reads its own config
    pkill -x waybar; pkill -x swayosd-server; pkill -x rofi
    on notify && pkill -x mako                 # nb-shell takes notifications over
    on lock && pkill -x swayidle
    sleep 0.4
    "$CONF/nebula/bin/nb-shell" restart       # shows the wizard by itself when WELCOME=1
    setsid -f waybar >/dev/null 2>&1
    on notify || { command -v mako >/dev/null && setsid -f mako >/dev/null 2>&1; }
    on lock && command -v swayidle >/dev/null && setsid -f swayidle -w >/dev/null 2>&1
    setsid -f "$CONF/nebula/bin/nb-wall" restore >/dev/null 2>&1
    if on clip && command -v cliphist >/dev/null; then
        pgrep -f 'wl-paste --type text --watch cliphist' >/dev/null || setsid -f wl-paste --type text --watch cliphist store >/dev/null 2>&1
        pgrep -f 'wl-paste --type image --watch cliphist' >/dev/null || setsid -f wl-paste --type image --watch cliphist store >/dev/null 2>&1
    fi
    ok "$(t "строка меню, поиск, пункт управления, уведомления и обои перезапущены")"
    sleep 1.5
    notify-send -a Nebula -i preferences-desktop-theme "$(tf "Nebula %s установлена" "$VERSION")" \
        "$(t "Super+Пробел — поиск · Super+A — пункт управления")" 2>/dev/null
else
    warn "$(t "niri сейчас не запущен — всё подхватится при следующем входе в сессию niri")"
fi

key() { # printf pads by bytes, which breaks on Cyrillic; pad by characters instead
    printf '  %s%s%s%*s%s\n' "$B" "$1" "$R" $((20 - ${#1})) "" "$2"
}
echo
echo "${G}${B}  $(tf "Готово! Nebula %s" "$VERSION")${R}"
echo
key "Super + $(t "Пробел")" "$(t "Поиск: приложения, калькулятор, команды, настройки")"
key "Super + A"            "$(t "пункт управления: Wi-Fi, звук, яркость, темы, настройки")"
key "Super + Enter"        "$(t "терминал (kitty)")"
key "Super + F"            "$(t "окно на весь экран и обратно")"
key "Super + W"            "$(t "обои · Super + Shift + W — случайные")"
key "Super + Shift + T"    "$(t "темы")"
key "Super + V"            "$(t "история буфера")"
key "Super + Esc"          "$(t "питание")"
key "Super + Shift + /"    "$(t "все горячие клавиши")"
echo
echo "  ${D}$(t "Мастер настройки ещё раз: Поиск → «Первоначальная настройка» или nb-shell welcome")"
echo "  $(t "Настройки: пункт управления → Настройки (или ~/.config/nebula/settings.conf)")"
echo "  $(tf "Откат:     ./uninstall.sh  (вернёт %s)" "${BACKUP/#$HOME/~}")${R}"
echo
