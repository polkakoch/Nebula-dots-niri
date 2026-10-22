# Nebula

**English** · [Русский](README.ru.md)

**A soft, glassy desktop for [niri](https://github.com/YaLTeR/niri), with a frame around the screen.**
The menu bar flows into a thin frame around the screen, and the search, the Control Center, the
player and the Dock grow right out of it. Colors come from your wallpaper by default (Material You),
animations are soft, and everything is set up with the mouse from the Control Center —
no config editing required. The interface speaks English and Russian; pick one when installing and
switch any time.

## Install

Arch Linux or an Arch-based distro, niri 26 or newer.

**From git**:

```sh
git clone https://github.com/polkakoch/Nebula-dots-niri.git
cd Nebula-dots-niri
./install.sh
```

**From a release**: grab `nebula-<version>.zip` from the [Releases](https://github.com/polkakoch/Nebula-dots-niri/releases) page, then:

```sh
unzip nebula-*.zip && cd nebula-*/ && ./install.sh
```

The installer is interactive (arrows, `Space`, `Enter`):

1. **Language**: English or Russian.
2. **How to install**: quick (all defaults), custom, or configs only without touching packages.
3. **Components**: notifications, lock and sleep, kitty, fastfetch, clipboard history, screenshots,
   Bluetooth, Qt/KDE colors, btop, a Dolphin menu, the Russian locale, the Claude add-on (off by default).
4. **Theme** (with color swatches right in the terminal) and **menu bar style**.
5. **Keyboard**: layouts and the switch key (Caps Lock, Alt+Shift, Ctrl+Shift, right Alt).
6. **Wallpaper folder** (if it's empty, you get a set of gradient wallpapers) and **fun stuff**.
7. **Setup wizard on first login** — yes or no.

Missing packages come from pacman, and whatever isn't in the repos from the AUR (yay/paru; if there's
no helper, the installer builds yay). Your current configs are backed up to
`~/.config/nebula-backup/<date>` first, and `./uninstall.sh` puts everything back. Running the
installer again updates Nebula and keeps your settings.

The same without questions, via flags:

| Flag | |
|---|---|
| `--auto` / `-y` | no questions, all defaults |
| `--custom` | straight to picking components |
| `--lang en` | interface language: `en` or `ru` |
| `--no-packages` | leave packages alone, configs only |
| `--theme tokyo-night` | theme (default `matugen` — "From wallpaper") |
| `--bar pills` | menu bar: `frame`, `floating`, `classic`, `islands`, `pills`, `notch`, `minimal` |
| `--layouts us,de` | keyboard layouts |
| `--switch alt_shift` | layout switch: `caps`, `alt_shift`, `ctrl_shift`, `ralt` |
| `--wall-dir ~/Pictures/Walls` | wallpaper folder |
| `--claude` | turn on the Claude add-on |
| `--no-fun` | no easter eggs or greeting |
| `--no-welcome` | don't show the wizard on first login |
| `--no-reload` | don't restart the running session |

### First login

On your first niri login after installing, the **setup wizard** opens: language, theme, wallpaper,
menu bar and Dock, keyboard and touchpad, fun stuff — all applied as you go. "Skip" closes it for
good; to run it again, use Search → "First-time setup" or `nb-shell welcome`.

## What's inside

| | |
|---|---|
| **Menu bar** | Seven styles: **Frame** (the bar flows into a frame around the screen), **Floating** (blurred glass), **Classic** (full width, translucent), **Islands** (left, center, right groups), **Pills** (every module on its own), **Notch** (the center hangs from the top edge and disappears when empty), **Minimal** (no background). With the mouse: scroll the dots for workspaces, the title for neighbouring windows, double-click the title to maximize, middle-click to close; scroll the logo to flip wallpapers, middle-click it for a random one; click the language to switch layouts, right-click the battery for the power mode. Modules are dragged between zones right in the Control Center |
| **Notifications** | Our own: every notification is a separate glass card, blurred exactly to its shape. App icon and name, time, a picture (cover art, avatar), progress, action buttons. Hover and it waits for you and shows a close button; click for the default action, right-click to clear them all. History lives in the Control Center, along with how long they stay, which side they appear on, and an optional sound. Do Not Disturb only lets urgent ones through |
| **Player** | While music plays, the cover and "title · artist" appear in the middle of the bar. Click for the big player: background and buttons take on the cover's colors and blend smoothly on track changes. Seeking (without Spotify's stutter: the position is sent once, when you let go of the slider), player volume, shuffle and repeat, a link to the track |
| **Dock** | At the bottom, with auto-hide: it slides up when you move the mouse to the bottom edge or the desktop is empty. Drag to reorder; drag a pinned icon out to unpin it, drag a running one among the pinned to pin it. Right-click for a menu, middle-click for a new window |
| **Search** (`Super+Space`) | Apps (ranked by how often you launch them), actions and settings, a calculator, `>command`, `~/path`, web search. `Ctrl+D` pins an app to the Dock |
| **Fun stuff** | In Search: `password` (a strong one, copied), `pomodoro` (25 minutes of focus with Do Not Disturb), `weather London`, `#ff8800` (the color in rgb/hsl), `timer 10 tea`, `coin`, `2d6`, `8ball <question>`, `shrug` / `flip` / `cat` (kaomoji), `surprise me` (random wallpaper and color scheme), a few answers to eternal questions, and the Konami code. Plus a greeting at login and a fresh wallpaper every login. All of it can be switched off in Extras |
| **Control Center** (`Super+A`) | Wi-Fi and Bluetooth with device lists, Do Not Disturb, night light, keep awake, power profile, brightness and sound with device choice, music, notifications. Pages for **wallpaper** (`Super+W`), **clipboard** (`Super+V`), **power** (`Super+Esc`) and **settings**: appearance, menu bar, desktop, windows and animations, input, extras, display, language, date and time, fastfetch, profile |
| **Pills** | Volume and brightness in the menu bar smoothly widen when they change and show a level bar |
| **Windows** | No loud focus ring: inactive windows are slightly translucent with a thin outline. `Super+F` goes fullscreen over the bar |
| **Animations** | Windows float up when they open (a custom shader) and shrink away when they close; springs without bounce. Speed is adjustable |
| **Desktop clock** | A big clock and date on an empty desktop: position, size, font, weight, color |
| **Themes** | "From wallpaper" (matugen) plus 21 ready-made ones. They recolor everything at once: bar, shell, notifications, window borders, terminal, fastfetch, lock screen, Qt apps |
| **fastfetch** | Your own picture: the `~/Pictures/Fastfetch` folder, Control Center → Fastfetch, `Super+Shift+A`, or right-click a picture in Dolphin |
| **Profile** | Your photo in the Control Center, on the lock and login screens; crop it right in the panel |
| **Language** | English and Russian: Settings → Date and time → Interface language, or the wizard's first page. The shell, bar, notifications, hotkey titles, lock screen and Dolphin menus all switch |

## Keys

| Keys | Action |
|---|---|
| `Super+Space` | Search |
| `Super+A` | Control Center |
| `Super+Enter`, `Super+T` | terminal |
| `Super+F` | fullscreen over the bar / back |
| `Super+Shift+F` · `Super+M` | maximize column · to the edges without gaps |
| `Super+W` / `Super+Shift+W` | wallpaper / random wallpaper |
| `Super+Shift+T` | themes |
| `Super+V` | clipboard history |
| `Super+Shift+A` | next fastfetch picture |
| `Super+N` · `Super+Shift+N` · `Super+Ctrl+N` | clear notifications · Do Not Disturb · bring back the last one |
| `Super+Esc` | power |
| `Super+Shift+L` | lock the screen |
| `Print` · `Ctrl+Print` · `Alt+Print` | screenshot of an area · the screen · a window |
| `Super+Shift+S` | area screenshot with the editor (satty) |
| `Super+Q` | close window |
| `Super+Tab`, `Super+O` | overview |
| `Super+1…9` / `Super+Ctrl+1…9` | go to workspace / move the window there |
| `Caps Lock` | switch layout |
| `Super+Shift+/` | every shortcut, with titles |

In the big player: `Space` — pause, `←/→` — seek, `N`/`P` — track, `Tab` — another player.

## Settings

Almost everything changes in the Control Center (`Super+A` → Settings) and applies right away.
It's stored in `~/.config/nebula/settings.conf` (with a comment for every key). After editing it
by hand, run `nb-settings apply`.

Your own tweaks that survive a reinstall:

- niri → `~/.config/niri/conf.d/user.kdl`, monitors → `conf.d/outputs.kdl`
- mako (the fallback notification daemon) → `~/.config/mako/user.conf`
- kitty: your `kitty.conf` is left alone, apart from one `include nebula-theme.conf` line at the end

### Your own theme

Copy any file from `~/.config/nebula/themes/` and change the colors — the theme shows up in
the search and the Control Center straight away.

```sh
name="My theme"
mode=dark            # or light
bg=#1e1e2e  bg_alt=… surface=… overlay=…   # backgrounds, dark to light
fg=…  fg_dim=…  muted=…                     # text
accent=…  accent2=…                         # accents
red=… green=… yellow=… blue=… magenta=… cyan=… orange=…
```

### Translations

Strings in the code are written in Russian; the English versions live in `nebula/i18n/en.tsv`
("russian string<TAB>english string"). Spotted an awkward translation? Fix the line there.

## Commands

```
nb-shell launcher · nb-shell panel [walls|clip|power|appearance|…] · nb-shell media
nb-shell restart                        restart the shell
nb-settings set <KEY> <value>           same as the switches in the Control Center
nb-settings set UI_LANG en|ru           change the language
nb-settings bar-layout "<left>" "<center>" "<right>"   menu bar modules
nb-notif dnd | dismiss | clear | restore | test
nb-fetch next | prev | random | set <file> | add <files…> | none
nb-avatar set <picture> | remove
nb-wall set <file> | random | next | prev | restore
nb-theme apply <id> | list | current
nb-osd brightness up|down|set N · nb-osd volume up|down|mute|set N
nb-power lock|suspend|logout|reboot|shutdown|profile
nb-greet --now                          the login greeting
nb-shell welcome                        the first-time setup wizard
```

## The Claude add-on (optional)

Off until you tick it in the installer (`--claude`) or in Settings → Extras. Without it there are
no Claude keys or menu items anywhere.

- `Super+Shift+C` — Claude Code in a terminal or Claude Desktop, `Super+Ctrl+Shift+C` — continue the
  last conversation; `?question` in Search opens Claude with that question.
- In Dolphin, right-click a folder → **Claude**: open here, continue, "explain what's in this folder";
  on a file — "ask Claude about this file".
- Claude Desktop officially ships only as a .deb package. Settings → Claude can import it (the official
  .deb is unpacked into your home folder, no root) or install the `claude-desktop` AUR package.

## Releases

`tools/make-release.sh [version]` builds `dist/nebula-<version>/` and `dist/nebula-<version>.zip`
(+ `.sha256`) — project files only, no `.git` or caches. Before packing, everything is checked for
personal data: your username, home folder, hostname, email, keys and tokens. If anything turns up,
the build stops.

## How it fits together

```
nebula/                 → ~/.config/nebula
  shell/                nb-shell: notifications, frame, Dock, desktop clock, Search, Control Center,
                        player, first-run wizard (Python + GTK4 + gtk4-layer-shell, one process)
  bin/                  scripts; nb-shell is the client, it writes commands into the shell's FIFO
  i18n/en.tsv           the English translation
  themes/*.theme        palettes
  templates/            color templates for apps + targets (where they go)
  settings.conf         default settings
config/                 → ~/.config
  niri/  waybar/  swayidle/  hypr/hyprlock.conf  servicemenus/ (Dolphin)
```

- Notifications are drawn by nb-shell (an `org.freedesktop.Notifications` server): each card is its
  own layer window, exactly its size, so niri's blur and shadow fit it precisely. If the shell isn't
  running, D-Bus starts mako instead.
- `nb-theme apply` fills the templates with the palette and gently reloads apps.
- `nb-settings` turns settings.conf into `niri/nebula-settings.kdl` and `waybar/nebula-settings.{jsonc,css}`.
- Everything is event-driven, no polling: at rest the shell, waybar and the pills barely touch the CPU.

## License

[MIT](LICENSE). Themes are based on the color schemes of the same names by their authors.
