#!/usr/bin/env bash
# Nebula — undo: puts your configs back from the latest backup (or the one you name)
#   ./uninstall.sh                     the latest backup
#   ./uninstall.sh ~/.config/nebula-backup/20261017-120000
set -uo pipefail
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
BACKUP="${1:-$(cat "$CONF/nebula-backup/latest" 2>/dev/null)}"

# Speak whatever language Nebula was set to (only a handful of lines, so no table needed)
lang=$(grep -oE '^UI_LANG="?(ru|en)' "$CONF/nebula/settings.conf" 2>/dev/null | grep -oE 'ru|en')
[ -n "$lang" ] || case "${LANG:-}" in ru*) lang=ru ;; *) lang=en ;; esac
say() { if [ "$lang" = ru ]; then printf '%s\n' "$1"; else printf '%s\n' "$2"; fi; }

[ -n "$BACKUP" ] && [ -d "$BACKUP" ] || { say "Резервная копия не найдена: ${BACKUP:-—}" "No backup found: ${BACKUP:-—}"; exit 1; }

say "Вернуть конфиги из ${BACKUP/#$HOME/~}?" "Restore configs from ${BACKUP/#$HOME/~}?"
read -r -p "[y/N] " a; [[ "$a" =~ ^[YyДд] ]] || exit 0

# stop the shell (Search, Control Center, notifications) first
"$CONF/nebula/bin/nb-shell" quit 2>/dev/null
for p in niri waybar mako swayosd swayidle fastfetch; do
    rm -rf "${CONF:?}/$p"
    [ -e "$BACKUP/$p" ] && cp -a "$BACKUP/$p" "$CONF/$p" && echo "  ✓ $p"
done
for f in hypr/hyprlock.conf kitty/kitty.conf; do
    if [ -e "$BACKUP/$f" ]; then cp -a "$BACKUP/$f" "$CONF/$f" && echo "  ✓ $f"
    else rm -f "$CONF/$f"; fi
done
# kdeglobals is shared by every KDE app, so we only put it back if the backup has one
[ -e "$BACKUP/kdeglobals" ] && cp -a "$BACKUP/kdeglobals" "$CONF/kdeglobals" && echo "  ✓ kdeglobals"
rm -f "$CONF/hypr/nebula-colors.conf" "$CONF/kitty/nebula-theme.conf"
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/kio/servicemenus/"nebula{,-claude,-claude-files}.desktop
# Claude Desktop imported from a .deb (~/.local/share/nebula/apps) stays: it's an app of its own
for f in "$HOME/.local/bin/"nb-*; do [ -L "$f" ] && rm -f "$f"; done
rm -rf "$CONF/nebula"
[ -e "$BACKUP/nebula" ] && cp -a "$BACKUP/nebula" "$CONF/nebula"

if [ -n "${NIRI_SOCKET:-}" ]; then
    pkill -x waybar; pkill -x mako; pkill -x swayosd-server; sleep 0.4
    setsid -f waybar >/dev/null 2>&1; setsid -f mako >/dev/null 2>&1
    command -v swayosd-server >/dev/null && setsid -f swayosd-server >/dev/null 2>&1
fi
say "Готово. Кэш превью можно удалить: rm -rf ~/.cache/nebula" "Done. You can also drop the preview cache: rm -rf ~/.cache/nebula"
