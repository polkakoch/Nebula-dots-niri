"""Nebula shell — CSS, built from the current theme's palette."""
from common import rgba


def build_css(c):
    light = c.get("mode") == "light"
    bg, fg, acc, acc2 = c["bg"], c["fg"], c["accent"], c["accent2"]
    on_acc = c.get("on_accent", bg)
    glass = rgba(bg, 0.80 if light else 0.70)       # frosted glass (niri blurs underneath)
    card = rgba(fg, 0.07 if light else 0.065)        # "tiles" inside the glass
    card_hi = rgba(fg, 0.11)
    line = rgba(fg, 0.10)
    hair = rgba(fg, 0.07)
    dim, muted = c["fg_dim"], c["muted"]
    shadow = "rgba(0,0,0,0.18)" if light else "rgba(0,0,0,0.35)"
    return f"""
* {{
    font-family: "Inter", sans-serif;
    font-feature-settings: "cv11", "ss01";
    -gtk-icon-style: regular;
}}
window, window.background {{ background: transparent; color: {fg}; }}
window.backdrop {{ background: transparent; }}
.icon {{ font-family: "JetBrainsMono Nerd Font"; font-weight: normal; }}
label {{ color: inherit; }}
tooltip {{ background: {rgba(bg, 0.96)}; border-radius: 8px; border: 1px solid {line}; }}
tooltip label {{ color: {fg}; }}

/* ── buttons: a soft highlight and a little "press" ─────────── */
button {{
    background: none; border: none; box-shadow: none; outline: none;
    color: {fg}; padding: 0; min-height: 0; min-width: 0;
    transition: background 160ms ease, transform 140ms ease, color 160ms ease, opacity 160ms ease;
}}
button:hover {{ background: {card_hi}; }}
button:active {{ transform: scale(0.95); }}
button:disabled {{ opacity: 0.4; }}

/* ── borderless input fields ────────────────────────────────── */
entry, text {{ background: none; border: none; box-shadow: none; outline: none; color: {fg}; caret-color: {acc}; }}
entry {{ min-height: 0; padding: 0; }}
entry > text > placeholder, text > placeholder {{ color: {muted}; }}
entry selection, text selection {{ background: {rgba(acc, 0.35)}; color: {fg}; }}
entry.field {{
    background: {card}; border-radius: 9px; padding: 7px 11px; border: 1px solid {hair};
}}
entry.field:focus-within {{ border-color: {rgba(acc, 0.7)}; box-shadow: 0 0 0 3px {rgba(acc, 0.22)}; }}

scrolledwindow, viewport, list, listview, flowbox, gridview {{ background: none; }}
scrollbar {{ background: none; border: none; }}
scrollbar slider {{ background: {rgba(fg, 0.22)}; border-radius: 99px; min-width: 4px; min-height: 30px; border: none; }}
scrollbar.vertical slider {{ min-width: 5px; }}
undershoot, overshoot {{ background: none; }}
separator {{ background: {hair}; min-height: 1px; min-width: 1px; }}

/* ═════════════════════ Search ═════════════════════ */
.launcher {{ background: none; color: {fg}; }}
.launcher .searchrow {{ padding: 14px 18px 12px 18px; }}
.launcher .searchicon {{ font-size: 24px; color: {dim}; }}
.launcher .search {{ font-size: 22px; font-weight: 400; }}
.launcher .search > text {{ padding: 0; }}
.launcher .body {{ padding: 6px 8px 8px 8px; }}
.launcher .section {{ font-size: 11.5px; font-weight: 600; color: {muted}; padding: 6px 12px 4px 12px; }}

row.result {{
    border-radius: 9px; padding: 6px 10px; background: none;
    transition: background 120ms ease;
}}
row.result:hover {{ background: {card}; }}
row.result:selected {{ background: {acc}; }}
row.result .title {{ font-size: 14px; font-weight: 500; }}
row.result .subtitle {{ font-size: 11.5px; color: {muted}; }}
row.result .hint {{ font-size: 11px; color: {muted}; font-weight: 500; }}
row.result .glyph {{ font-size: 20px; color: {acc}; min-width: 32px; }}
row.result:selected .title, row.result:selected .subtitle, row.result:selected .hint,
row.result:selected .glyph {{ color: {on_acc}; }}
row.result .calc {{ font-size: 22px; font-weight: 600; }}
row.result .thumbimg {{ border-radius: 6px; }}

/* grids (wallpapers, themes, power) */
flowboxchild {{ padding: 0; border-radius: 14px; background: none; outline: none; }}
flowboxchild:focus {{ outline: none; }}
.tile {{
    padding: 5px; border-radius: 14px; border: 2px solid transparent;
    transition: background 140ms ease, border-color 140ms ease;
}}
flowboxchild:hover .tile {{ background: {card}; }}
flowboxchild:selected .tile {{ border-color: {acc}; background: {rgba(acc, 0.14)}; }}
.tile.current {{ border-color: {rgba(acc2, 0.55)}; }}
.tile .caption {{ font-size: 11.5px; font-weight: 500; color: {dim}; margin-top: 5px; }}
flowboxchild:selected .tile .caption {{ color: {fg}; }}
.thumb {{ border-radius: 10px; background: {card}; }}
.powerbtn {{ padding: 16px 8px 12px 8px; }}
.powerbtn .circle {{
    min-width: 58px; min-height: 58px; border-radius: 99px; background: {card_hi};
    font-size: 26px; color: {fg};
}}
.powerbtn .caption {{ font-size: 12.5px; margin-top: 10px; }}
button:hover .powerbtn .circle {{ background: {acc}; color: {on_acc}; }}
button:hover .powerbtn.danger .circle {{ background: {c.get('red', acc)}; color: {bg}; }}
button:hover .tile {{ background: {card}; }}
/* clipboard in the Control Center */
row.cliprow {{ border-radius: 10px; padding: 6px 8px; background: none; transition: background 120ms ease; }}
row.cliprow:hover {{ background: {card}; }}
row.cliprow .t {{ font-size: 12.5px; }}
row.cliprow .glyph {{ font-size: 18px; color: {acc}; min-width: 40px; }}
row.cliprow .pinbtn {{ opacity: 0; transition: opacity 120ms ease; }}
row.cliprow:hover .pinbtn {{ opacity: 1; }}
searchentry.pagesearch {{ background: {card}; border-radius: 10px; padding: 6px 10px; min-height: 0; }}
searchentry.pagesearch > text {{ padding: 0; }}
/* profile photo crop */
.cropper {{ border-radius: 16px; }}
/* clock position picker: a 3×3 grid */
.posgrid button {{ min-height: 30px; border-radius: 8px; background: {card}; }}
.posgrid button .dot {{ min-width: 8px; min-height: 8px; border-radius: 99px; background: {rgba(fg, 0.35)}; }}
.posgrid button.on {{ background: {rgba(acc, 0.28)}; }}
.posgrid button.on .dot {{ background: {acc}; min-width: 14px; }}
flowboxchild:selected .powerbtn .circle {{ background: {acc}; color: {on_acc}; }}
.footer {{ font-size: 11px; color: {muted}; padding: 4px 16px 10px 16px; }}
.footer .key {{ background: {card}; border-radius: 5px; padding: 1px 6px; color: {dim}; font-weight: 600; }}
.empty {{ font-size: 13px; color: {muted}; padding: 26px; }}

/* ═════════════════ First-time setup wizard ═════════════════ */
.welcome-dim {{ background: {rgba('#000000', 0.26)}; }}
.welcome {{
    background: {rgba(bg, 0.93)}; color: {fg}; border-radius: 26px; border: 1px solid {line};
    box-shadow: 0 24px 70px rgba(0,0,0,0.45); padding: 18px 22px;
}}
.whead {{ padding: 0 2px 6px 2px; }}
.wstep {{ font-size: 11px; font-weight: 700; letter-spacing: 1.2px; color: {acc}; }}
.wdot {{ min-width: 7px; min-height: 7px; border-radius: 99px; background: {rgba(fg, 0.18)};
    transition: min-width 280ms cubic-bezier(0.22, 1, 0.36, 1), background 280ms ease; }}
.wdot.past {{ background: {rgba(acc, 0.55)}; }}
.wdot.on {{ min-width: 22px; background: linear-gradient(90deg, {acc}, {acc2}); }}
.wpage {{ padding: 8px 6px; }}
.wtitle {{ font-size: 22px; font-weight: 700; letter-spacing: -0.3px; }}
.wbig {{ font-size: 30px; font-weight: 750; letter-spacing: -0.6px; }}
.wsub {{ font-size: 13px; color: {dim}; }}
.whero {{ font-size: 64px; color: {acc}; }}
.wchip {{ background: {card}; border: 1px solid {hair}; border-radius: 99px; padding: 6px 12px;
    font-size: 12px; font-weight: 600; color: {dim}; }}
.wchip .icon {{ color: {acc}; font-size: 14px; }}
.wfoot {{ padding-top: 12px; border-top: 1px solid {hair}; }}
.wnav {{ padding: 8px 20px; font-size: 13px; }}
.welcome .opt {{ padding: 6px 2px; }}

/* ═════════════════ Control Center ═════════════════ */
.panel {{ background: none; color: {fg}; }}
.page {{ padding: 14px; }}
.card {{
    background: {card}; border-radius: 14px; padding: 10px 12px; color: {fg}; box-shadow: none;
    border: 1px solid {hair};
}}
.card.flat {{ padding: 0; }}
.card-title {{ font-size: 12.5px; font-weight: 600; color: {fg}; margin-bottom: 6px; }}
.dim {{ color: {dim}; }}
.muted {{ color: {muted}; }}
.small {{ font-size: 11.5px; }}
.tiny {{ font-size: 10.5px; }}
.bold {{ font-weight: 650; }}

/* profile */
.avatar {{ border-radius: 99px; }}
.avatar-fallback {{
    border-radius: 99px; background: linear-gradient(135deg, {acc}, {acc2});
    color: {on_acc}; font-weight: 700;
}}
.who .name {{ font-size: 15px; font-weight: 650; }}
.who .sub {{ font-size: 11.5px; color: {muted}; }}
.roundbtn {{
    min-width: 34px; min-height: 34px; border-radius: 99px; background: {card}; font-size: 16px;
}}
.roundbtn:hover {{ background: {card_hi}; }}
.roundbtn.danger:hover {{ background: {rgba(c['red'], 0.85)}; color: {bg}; }}

/* round toggles */
.toggle-row {{ padding: 6px 4px; border-radius: 10px; }}
.toggle-row:hover {{ background: {rgba(fg, 0.04)}; }}
.toggle-row .t {{ font-size: 13px; font-weight: 600; }}
.toggle-row .s {{ font-size: 11px; color: {muted}; }}
.circle {{
    min-width: 30px; min-height: 30px; border-radius: 99px; background: {rgba(fg, 0.12)};
    font-size: 15px; color: {fg};
}}
.circle.on {{ background: {acc}; color: {on_acc}; }}
.minitile {{ padding: 10px 12px; }}
.minitile .t {{ font-size: 12.5px; font-weight: 600; }}
.minitile .s {{ font-size: 10.5px; color: {muted}; }}
.minitile:hover {{ background: {card_hi}; }}

/* sliders: thick, white fill, an icon inside */
scale {{ padding: 0; margin: 0; min-height: 26px; }}
scale trough {{
    min-height: 24px; border-radius: 99px; background: {rgba(fg, 0.13)}; border: none; outline: none;
}}
scale highlight {{
    min-height: 24px; border-radius: 99px; border: none;
    background: {fg};
}}
scale slider {{
    min-width: 24px; min-height: 24px; margin: 0; border-radius: 99px;
    background: {fg}; border: none; box-shadow: 0 0 0 1px {rgba('#000000', 0.08)}, 0 1px 4px {shadow};
    transition: transform 140ms ease;
}}
scale slider:hover {{ transform: scale(1.06); }}
scale.thin trough, scale.thin highlight {{ min-height: 6px; }}
scale.thin slider {{ min-width: 16px; min-height: 16px; margin: -5px; }}
scale.thin highlight {{ background: {acc}; }}
.slider-icon {{ font-size: 14px; color: {muted}; margin-left: 6px; }}
.slider-icon.off {{ color: {muted}; }}

/* media */
.media .title {{ font-size: 13px; font-weight: 650; }}
.media .artist {{ font-size: 11.5px; color: {muted}; }}
.media .ctl {{ min-width: 32px; min-height: 32px; border-radius: 99px; font-size: 18px; }}
.media .ctl.big {{ min-width: 40px; min-height: 40px; font-size: 22px; }}
.media .art {{ border-radius: 9px; }}
.media .noart {{ border-radius: 9px; background: linear-gradient(135deg, {rgba(acc, 0.55)}, {rgba(acc2, 0.55)});
    color: {on_acc}; font-size: 22px; }}
.mediapop .noart {{ font-size: 40px; border-radius: 14px; }}
.media .time {{ font-size: 10.5px; color: {muted}; font-family: "JetBrainsMono Nerd Font"; }}
.media .chip {{ font-size: 10.5px; padding: 2px 8px; border-radius: 99px; background: {card}; color: {dim}; }}
.media .chip.on {{ background: {rgba(acc, 0.25)}; color: {fg}; }}
.mediapop {{ background: none; color: {fg}; padding: 6px 6px 8px 6px; }}
/* the big player */
.bigplayer .art {{ border-radius: 14px; }}
.bigplayer .noart {{ font-size: 44px; }}
.bp-source {{ font-size: 10px; font-weight: 700; letter-spacing: 1.4px; color: {acc}; }}
.bp-title {{ font-size: 17px; font-weight: 700; }}
.bp-artist {{ font-size: 13px; font-weight: 500; color: {dim}; }}
.bp-album {{ font-size: 11.5px; color: {muted}; }}
.media .ctl.small {{ min-width: 28px; min-height: 28px; font-size: 15px; color: {dim}; }}
.media .ctl.small:hover {{ color: {fg}; }}
.media .ctl.on {{ color: {acc}; }}
.media .ctl.big {{ background: {fg}; color: {bg}; }}
.media .ctl.big:hover {{ background: {rgba(fg, 0.85)}; }}
.bp-vol {{ margin: 0 4px; }}
.bp-body {{ padding: 14px 16px 16px 16px; }}
.bp-art {{ border-radius: 14px; box-shadow: 0 10px 26px rgba(0,0,0,0.38);
    transition: transform 380ms cubic-bezier(0.22, 1, 0.36, 1), opacity 380ms ease; }}
.bigplayer.paused .bp-art {{ transform: scale(0.93); opacity: 0.82; }}
.bp-empty {{ padding: 26px 0; }}

/* Dock */
.dock {{ padding: 9px 10px 7px 10px; }}
.dockitem {{
    padding: 4px; border-radius: 13px; background: none;
    transition: transform 220ms cubic-bezier(0.22, 1, 0.36, 1), background 160ms ease;
}}
.dockitem:hover {{ background: {rgba(fg, 0.08)}; transform: scale(1.12) translateY(-3px); }}
.dockitem:active {{ transform: scale(0.94); }}
.dockdot {{ min-width: 4px; min-height: 4px; border-radius: 99px; background: transparent;
    transition: min-width 220ms ease, background 220ms ease; }}
.dockdot.on {{ background: {rgba(fg, 0.55)}; }}
.dockdot.focused {{ background: {acc}; min-width: 14px; }}
.docksep {{ background: {rgba(fg, 0.14)}; min-width: 1px; margin: 10px 5px 14px 5px; }}
.dockitem.dragging {{ opacity: 0; }}
@keyframes dockbounce {{
    0% {{ transform: translateY(0); }}
    35% {{ transform: translateY(-12px); }}
    70% {{ transform: translateY(0); }}
    100% {{ transform: translateY(0); }}
}}
.dockitem.launching .dockicon {{ animation: dockbounce 760ms cubic-bezier(0.33, 0, 0.3, 1) infinite; }}
/* the Dock menu */
popover.dockpop > contents {{ padding: 5px; border-radius: 11px; background: {rgba(bg, 0.97)};
    border: 1px solid {rgba(fg, 0.10)}; box-shadow: 0 10px 28px rgba(0,0,0,0.32); min-width: 190px; }}
.dockmenu .menutitle {{ font-size: 11px; font-weight: 600; color: {muted}; padding: 3px 10px 4px 10px; }}
.dockmenu .menuitem {{ padding: 4px 10px 4px 6px; border-radius: 6px; background: none; color: {fg};
    font-size: 13px; font-weight: 400; min-height: 0; box-shadow: none; }}
.dockmenu .menuitem:hover {{ background: {acc}; color: {on_acc}; }}
.dockmenu .menuitem.danger:not(:hover) {{ color: {c.get('red', fg)}; }}
.dockmenu .menumark {{ min-width: 6px; min-height: 6px; border-radius: 99px; }}
.dockmenu .menumark.on {{ background: {acc}; }}
.dockmenu .menuitem:hover .menumark.on {{ background: {on_acc}; }}
.dockmenu .menusep {{ background: {rgba(fg, 0.10)}; min-height: 1px; margin: 4px 8px; }}

/* desktop clock */
.desk {{ padding: 10px 40px; }}
.desk-date {{ font-size: 20px; font-weight: 500; color: {rgba(fg, 0.85)};
    text-shadow: 0 1px 8px rgba(0,0,0,0.45); }}
.desk-time {{ font-family: "Inter Display", "Inter", sans-serif; font-size: 112px; font-weight: 600;
    letter-spacing: -3px; color: {fg}; text-shadow: 0 2px 18px rgba(0,0,0,0.40); }}

/* notification cards: the window is exactly this box, niri blurs behind it with the same 16px corners */
.toast {{
    background: {rgba(bg, 0.86 if light else 0.78)}; border-radius: 16px; border: 1px solid {line};
    padding: 10px 12px 12px 12px; color: {fg};
}}
.toast.critical {{ border: 1px solid {rgba(c.get("red", "#e06c75"), 0.75)};
    background-color: {rgba(bg, 0.86 if light else 0.80)};
    background-image: linear-gradient({rgba(c.get("red", "#e06c75"), 0.12)}, {rgba(c.get("red", "#e06c75"), 0.12)}); }}
.toast .thead {{ margin-bottom: 6px; min-height: 20px; }}
.toast .tapp {{ font-size: 11px; font-weight: 600; color: {muted}; letter-spacing: 0.2px; }}
.toast .twhen {{ font-size: 11px; color: {muted}; }}
.toast .tclose {{ min-width: 20px; min-height: 20px; border-radius: 99px; background: {card_hi}; }}
.toast .tclose .icon {{ font-size: 11px; color: {dim}; }}
.toast .tclose:hover {{ background: {rgba(fg, 0.2)}; }}
.toast .ttitle {{ font-size: 13.5px; font-weight: 600; }}
.toast .tbody {{ font-size: 12.5px; color: {dim}; }}
.toast .tbody link {{ color: {acc}; }}
.toast .nimg {{ border-radius: 10px; }}
.toast .tprogress {{ margin-top: 6px; }}
.toast .tprogress trough {{ min-height: 4px; border-radius: 99px; background: {line}; }}
.toast .tprogress progress {{ min-height: 4px; border-radius: 99px; background: {acc}; }}
.toast .tactions {{ margin-top: 10px; }}
.toast .taction {{ padding: 6px 10px; border-radius: 9px; background: {card}; font-size: 12.5px; font-weight: 500; }}
.toast .taction:hover {{ background: {card_hi}; }}

/* notification history in the control center */
.notif {{ padding: 9px 11px; }}
.notif .app {{ font-size: 10.5px; color: {muted}; font-weight: 600; }}
.notif .nforget {{ min-width: 18px; min-height: 18px; border-radius: 99px; opacity: 0; }}
.notif:hover .nforget {{ opacity: 1; }}
.notif .nforget .icon {{ font-size: 10px; color: {muted}; }}
.notif .sum {{ font-size: 12.5px; font-weight: 600; }}
.notif .body {{ font-size: 11.5px; color: {dim}; }}
/* menu bar: styles and the module editor */
.stylecard {{ padding: 6px; border-radius: 14px; background: none; }}
.stylecard:hover {{ background: {card}; }}
.stylecard .t {{ font-size: 12.5px; font-weight: 600; }}
.stylecard .s {{ font-size: 10.5px; }}
.zonetitle {{ font-size: 11px; font-weight: 600; color: {muted}; margin-top: 2px; }}
.modzone {{ padding: 6px; border-radius: 12px; background: {rgba(fg, 0.045)};
    border: 1px dashed transparent; min-height: 30px; transition: background 160ms ease, border-color 160ms ease; }}
.modzone.hidden {{ background: none; border-color: {rgba(fg, 0.10)}; }}
.modzone.drop {{ background: {rgba(acc, 0.16)}; border-color: {rgba(acc, 0.55)}; }}
.modzone flowboxchild {{ padding: 0; background: none; }}
.modchip {{ padding: 4px 10px 4px 8px; border-radius: 99px; background: {card_hi}; color: {fg};
    font-size: 12px; font-weight: 500; min-height: 0; }}
.modchip:hover {{ background: {rgba(acc, 0.28)}; }}
.modzone.hidden .modchip {{ background: none; color: {dim}; border: 1px solid {rgba(fg, 0.10)}; }}
.modchip.dragging {{ opacity: 0.35; }}
.modchip .modglyph {{ font-size: 13px; color: {acc}; }}
.pinrow {{ padding: 4px 2px; }}
.pinrow .t {{ font-size: 13px; }}
.pinbtn {{ min-width: 26px; min-height: 26px; padding: 0; border-radius: 99px; background: none; color: {dim}; }}
.pinbtn:hover {{ background: {card_hi}; color: {fg}; }}
.pinbtn.danger:hover {{ background: {rgba(c['red'], 0.85)}; color: {bg}; }}
.pinbtn:disabled {{ opacity: 0.3; }}
.linkbtn {{ font-size: 11.5px; color: {acc}; padding: 2px 6px; border-radius: 6px; font-weight: 600; }}

/* the settings list (like System Preferences) */
.settings {{ padding: 4px; }}
.setrow {{ padding: 7px 8px; border-radius: 10px; }}
.setrow:hover {{ background: {card_hi}; }}
.setrow .t {{ font-size: 13px; font-weight: 500; }}
.setrow .v {{ font-size: 12px; color: {muted}; }}
.setrow .chev {{ font-size: 14px; color: {muted}; }}
.badge {{ min-width: 26px; min-height: 26px; border-radius: 7px; font-size: 15px; color: white; }}
.badge.c1 {{ background: linear-gradient(160deg, #ff7eb3, #ff4f7b); }}
.badge.c2 {{ background: linear-gradient(160deg, #6ec6ff, #2f80ed); }}
.badge.c3 {{ background: linear-gradient(160deg, #8f9bff, #5e5ce6); }}
.badge.c4 {{ background: linear-gradient(160deg, #ffb35c, #ff8a00); }}
.badge.c5 {{ background: linear-gradient(160deg, #6be08a, #30b65a); }}
.badge.c6 {{ background: linear-gradient(160deg, #a0a7b4, #6c7480); }}
.badge.c7 {{ background: linear-gradient(160deg, #d68cff, #a550f0); }}

/* subpage header */
.pagehead {{ padding: 2px 0 10px 0; }}
.pagehead .back {{ font-size: 13px; color: {acc}; font-weight: 600; padding: 4px 8px 4px 2px; border-radius: 8px; }}
.pagehead .back .icon {{ font-size: 18px; }}
.pagehead .ptitle {{ font-size: 16px; font-weight: 700; }}
.opt {{ padding: 9px 4px; }}
.opt .t {{ font-size: 13px; }}
.opt .s {{ font-size: 11px; color: {muted}; }}

/* segmented buttons (scale, speed, bar style) */
.segmented {{ background: {rgba(fg, 0.08)}; border-radius: 9px; padding: 2px; }}
.segmented button {{ border-radius: 7px; padding: 5px 0; font-size: 12px; font-weight: 600; color: {dim}; }}
.segmented button.on {{ background: {rgba(fg, 0.92) if not light else bg}; color: {bg if not light else fg};
    box-shadow: 0 1px 3px {shadow}; }}

/* GTK switch */
switch {{
    min-width: 40px; min-height: 22px; border-radius: 99px; padding: 2px;
    background: {rgba(fg, 0.18)}; border: none; outline: none;
    transition: background 200ms ease;
}}
switch:checked {{ background: {acc}; }}
switch slider {{
    min-width: 20px; min-height: 20px; border-radius: 99px; background: white; border: none;
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}}
switch image {{ opacity: 0; }}

/* grids inside the panel */
.swatch {{ border-radius: 12px; }}
.netrow {{ padding: 7px 8px; border-radius: 9px; }}
.netrow:hover {{ background: {card_hi}; }}
.netrow.active .t {{ color: {acc}; }}
.netrow .t {{ font-size: 13px; font-weight: 500; }}
.netrow .s {{ font-size: 11px; color: {muted}; }}
.accentbtn {{
    background: {acc}; color: {on_acc}; border-radius: 8px; padding: 6px 14px; font-weight: 600; font-size: 12.5px;
}}
.accentbtn:hover {{ background: {acc2}; }}
.ghostbtn {{
    background: {card}; border-radius: 8px; padding: 6px 12px; font-weight: 600; font-size: 12.5px;
}}
.kbd {{
    font-size: 11px; font-weight: 600; background: {card}; border: 1px solid {hair}; border-radius: 6px;
    padding: 1px 7px;
}}
.bigclock {{ font-size: 44px; font-weight: 300; letter-spacing: -1px; }}
.spinner {{ color: {acc}; }}
dropdown > button {{ background: {card}; border-radius: 8px; padding: 5px 10px; border: 1px solid {hair}; }}
popover > contents {{ background: {rgba(bg, 0.98)}; border-radius: 12px; border: 1px solid {line}; padding: 6px; }}
popover listview row {{ border-radius: 6px; padding: 4px 8px; }}
popover listview row:selected {{ background: {acc}; color: {on_acc}; }}
"""
