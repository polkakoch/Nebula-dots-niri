"""Nebula shell — system services for the Control Center.

Anything that could be slow runs asynchronously (Gio.Subprocess) or through D-Bus libraries.
"""
import json
import os
import re
from pathlib import Path

from gi.repository import GLib

import common as C
from common import BIN, run_async, run_sync, tr


# ─── brightness ─────────────────────────────────────────────────────────────
def backlight():
    base = Path("/sys/class/backlight")
    if not base.is_dir():
        return None
    devs = sorted(base.iterdir(), key=lambda p: ("intel" not in p.name and "amdgpu" not in p.name, p.name))
    return devs[0] if devs else None


def brightness_get():
    d = backlight()
    if not d:
        return None
    try:
        return round(int((d / "brightness").read_text()) * 100 / max(1, int((d / "max_brightness").read_text())))
    except (OSError, ValueError):
        return None


def brightness_set(pct):
    run_async([str(BIN / "nb-osd"), "brightness", "set", str(int(max(1, pct)))])


# ─── sound ──────────────────────────────────────────────────────────────────
def volume_get(target="@DEFAULT_AUDIO_SINK@"):
    out = run_sync(["wpctl", "get-volume", target])
    m = re.search(r"([\d.]+)", out)
    if not m:
        return None
    return round(float(m.group(1)) * 100), "MUTED" in out


def volume_get_async(done, target="@DEFAULT_AUDIO_SINK@"):
    def got(_ok, out):
        m = re.search(r"([\d.]+)", out)
        done((round(float(m.group(1)) * 100), "MUTED" in out) if m else None)
    run_async(["wpctl", "get-volume", target], got)


def volume_set(pct, target="@DEFAULT_AUDIO_SINK@"):
    run_async(["wpctl", "set-volume", "-l", "1.0", target, f"{int(pct)}%"])


def mute_toggle(target="@DEFAULT_AUDIO_SINK@"):
    run_async(["wpctl", "set-mute", target, "toggle"])


def audio_devices(kind, done):
    """kind: sinks | sources → done([(name, description, is_default)])"""
    def got_default(_ok, default):
        default = default.strip()

        def got(_ok2, out):
            try:
                items = json.loads(out or "[]")
            except ValueError:
                items = []
            res = []
            for it in items:
                name = it.get("name", "")
                if kind == "sources" and name.endswith(".monitor"):
                    continue
                res.append((name, it.get("description") or name, name == default))
            done(res)
        run_async(["pactl", "-f", "json", "list", kind], got)
    run_async(["pactl", "get-default-sink" if kind == "sinks" else "get-default-source"], got_default)


def audio_set_default(kind, name, done=None):
    run_async(["pactl", "set-default-sink" if kind == "sinks" else "set-default-source", name], done)


# ─── power profile ──────────────────────────────────────────────────────────
PROFILES = [("power-saver", tr("Экономия"), C.I["leaf"]), ("balanced", tr("Баланс"), C.I["speed"]),
            ("performance", tr("Производительность"), C.I["speed"])]


def profile_get(done):
    if not C.has("powerprofilesctl"):
        done(None)
        return
    run_async(["powerprofilesctl", "get"], lambda ok, out: done(out.strip() if ok else None))


def profile_set(p, done=None):
    run_async(["powerprofilesctl", "set", p], done)


# ─── Do Not Disturb, night light, keep awake ────────────────────────────────
def dnd_get():
    from notifications import dnd_on
    return dnd_on()


def pgrep(pattern, full=False):
    return run_sync(["pgrep", "-f" if full else "-x", pattern]).strip() != ""


def pgrep_async(pattern, done, full=False):
    run_async(["pgrep", "-f" if full else "-x", pattern], lambda ok, out: done(bool(out.strip())))


def night_get():
    return pgrep("wlsunset")


def night_set(on, temp=4000):
    if on:
        C.spawn(["pkill", "-x", "wlsunset"])
        # the same "day" and "night" temperature — the warm light just stays on
        C.spawn(["wlsunset", "-t", str(int(temp)), "-T", str(int(temp) + 1), "-S", "06:00", "-s", "18:00"])
    else:
        C.spawn(["pkill", "-x", "wlsunset"])


def caffeine_get():
    return pgrep("systemd-inhibit --what=idle:sleep --who=Nebula", full=True)


def caffeine_set(on):
    if on:
        C.spawn(["systemd-inhibit", "--what=idle:sleep", "--who=Nebula", tr("--why=Не засыпать"), "sleep", "infinity"])
    else:
        C.spawn(["pkill", "-f", "systemd-inhibit --what=idle:sleep --who=Nebula"])


# ─── Wi-Fi (libnm) ──────────────────────────────────────────────────────────
class Wifi:
    def __init__(self):
        self.client = None
        self.listeners = []
        try:
            import gi
            gi.require_version("NM", "1.0")
            from gi.repository import NM
            self.NM = NM
            self.client = NM.Client.new(None)
            self.client.connect("notify::wireless-enabled", lambda *_: self.changed())
            self.client.connect("notify::primary-connection", lambda *_: self.changed())
            for d in self.devices():
                d.connect("notify::active-access-point", lambda *_: self.changed())
                d.connect("access-point-added", lambda *_: self.changed())
                d.connect("access-point-removed", lambda *_: self.changed())
                d.connect("state-changed", lambda *_: self.changed())
        except Exception:
            self.client = None
        self.pending = None

    def changed(self):
        if self.pending:
            return
        def fire():
            self.pending = None
            for fn in list(self.listeners):
                fn()
            return False
        self.pending = GLib.timeout_add(150, fire)

    def devices(self):
        if not self.client:
            return []
        return [d for d in self.client.get_devices() if d.get_device_type() == self.NM.DeviceType.WIFI]

    @property
    def available(self):
        return bool(self.devices())

    @property
    def enabled(self):
        return bool(self.client and self.client.wireless_get_enabled())

    def set_enabled(self, on):
        run_async(["nmcli", "radio", "wifi", "on" if on else "off"])

    def ssid_of(self, ap):
        s = ap.get_ssid()
        if not s:
            return None
        return self.NM.utils_ssid_to_utf8(s.get_data())

    def active(self):
        for d in self.devices():
            ap = d.get_active_access_point()
            if ap:
                return self.ssid_of(ap), ap.get_strength()
        return None

    def networks(self):
        """[(ssid, strength, secure, active, saved)] — one entry per SSID, strongest first."""
        saved = set()
        if self.client:
            for c in self.client.get_connections():
                sw = c.get_setting_wireless()
                if sw and sw.get_ssid():
                    saved.add(self.NM.utils_ssid_to_utf8(sw.get_ssid().get_data()))
        act = self.active()
        best = {}
        for d in self.devices():
            for ap in d.get_access_points():
                ssid = self.ssid_of(ap)
                if not ssid:
                    continue
                secure = bool(ap.get_wpa_flags() or ap.get_rsn_flags() or (ap.get_flags() & 1))
                st = ap.get_strength()
                if ssid not in best or st > best[ssid][1]:
                    best[ssid] = (ssid, st, secure, bool(act and act[0] == ssid), ssid in saved)
        return sorted(best.values(), key=lambda n: (not n[3], -n[1]))

    def scan(self):
        for d in self.devices():
            try:
                d.request_scan_async(None, lambda dev, res: self._scan_done(dev, res))
            except Exception:
                pass

    def _scan_done(self, dev, res):
        try:
            dev.request_scan_finish(res)
        except Exception:
            pass
        self.changed()

    def connect(self, ssid, password=None, done=None):
        argv = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            argv += ["password", password]
        run_async(argv, done)

    def disconnect(self, done=None):
        for d in self.devices():
            run_async(["nmcli", "device", "disconnect", d.get_iface()], done)


# ─── Bluetooth (bluetoothctl) ───────────────────────────────────────────────
class Bluetooth:
    def __init__(self):
        self.available = C.has("bluetoothctl")

    def state(self, done):
        """done(powered, [(mac, name, connected, paired)])"""
        if not self.available:
            done(None, [])
            return

        def got_show(_ok, out):
            if "Controller" not in out:
                done(None, [])
                return
            powered = "Powered: yes" in out

            def got_devices(_ok, devs):
                def got_conn(_ok, conn):
                    def got_paired(_ok, paired):
                        cset = {l.split()[1] for l in conn.splitlines() if l.startswith("Device ")}
                        pset = {l.split()[1] for l in paired.splitlines() if l.startswith("Device ")}
                        res = []
                        for l in devs.splitlines():
                            p = l.split(" ", 2)
                            if len(p) == 3 and p[0] == "Device":
                                name = p[2]
                                if re.fullmatch(r"([0-9A-F]{2}-){5}[0-9A-F]{2}", name):
                                    continue   # nameless devices from the scan
                                res.append((p[1], name, p[1] in cset, p[1] in pset))
                        res.sort(key=lambda d: (not d[2], not d[3], d[1].casefold()))
                        done(powered, res)
                    run_async(["bluetoothctl", "devices", "Paired"], got_paired)
                run_async(["bluetoothctl", "devices", "Connected"], got_conn)
            run_async(["bluetoothctl", "devices"], got_devices)
        run_async(["bluetoothctl", "show"], got_show)

    def set_power(self, on, done=None):
        if on:
            run_async(["rfkill", "unblock", "bluetooth"],
                      lambda *_: run_async(["bluetoothctl", "power", "on"], done))
        else:
            run_async(["bluetoothctl", "power", "off"], done)

    def toggle_device(self, mac, connected, paired, done=None):
        if connected:
            run_async(["bluetoothctl", "disconnect", mac], done)
        elif paired:
            run_async(["bluetoothctl", "connect", mac], done)
        else:
            # a new device: pair → trust → connect (blueman's agent asks for a PIN if needed)
            run_async(["sh", "-c", f"bluetoothctl pair {mac} && bluetoothctl trust {mac} && bluetoothctl connect {mac}"],
                      done)

    def scan(self, done=None):
        run_async(["bluetoothctl", "--timeout", "8", "scan", "on"], done)


# ─── display and scale (niri) ───────────────────────────────────────────────
def outputs():
    return _parse_outputs(run_sync(["niri", "msg", "-j", "outputs"]))


def _parse_outputs(text):
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return []
    res = []
    for name, o in data.items():
        if not o.get("logical"):
            continue
        mode = o["modes"][o["current_mode"]] if o.get("current_mode") is not None else None
        res.append(dict(name=name, model=f"{o.get('make', '')} {o.get('model', '')}".strip(),
                        scale=o["logical"]["scale"], width=mode["width"] if mode else 0,
                        height=mode["height"] if mode else 0,
                        refresh=round(mode["refresh_rate"] / 1000) if mode else 0))
    return res


def set_scale(name, scale):
    """Write to conf.d/outputs.kdl (niri applies and remembers it by itself)."""
    path = C.CONF / "niri" / "conf.d" / "outputs.kdl"
    try:
        text = path.read_text()
    except OSError:
        text = "// Monitors (list them with: niri msg outputs)\n"
    val = f"{scale:g}"
    m = re.search(r'(?m)^output\s+"' + re.escape(name) + r'"\s*\{', text)
    if m:
        # end of the block: count the braces
        i, depth = m.end(), 1
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        block = text[m.start():i]
        if re.search(r"(?m)^\s*scale\s+\S+", block):
            nb = re.sub(r"(?m)^(\s*)scale\s+\S+", lambda mm: f"{mm.group(1)}scale {val}", block, count=1)
        else:
            nb = block[:block.index("{") + 1] + f"\n    scale {val}" + block[block.index("{") + 1:]
        text = text[:m.start()] + nb + text[i:]
    else:
        text = text.rstrip("\n") + f'\n\noutput "{name}" {{\n    scale {val}\n}}\n'
    tmp = path.with_suffix(".kdl.nbtmp")
    tmp.write_text(text)
    os.replace(tmp, path)


# ─── time ───────────────────────────────────────────────────────────────────
def time_info_async(done):
    def got(_ok, out):
        d = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
        done(d.get("Timezone", ""), d.get("NTP") == "yes", d.get("CanNTP") == "yes")
    run_async(["timedatectl", "show", "-p", "Timezone", "-p", "NTP", "-p", "CanNTP"], got)


def outputs_async(done):
    run_async(["niri", "msg", "-j", "outputs"], lambda ok, out: done(_parse_outputs(out)))


def time_info():
    out = run_sync(["timedatectl", "show", "-p", "Timezone", "-p", "NTP", "-p", "CanNTP"])
    d = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    return d.get("Timezone", ""), d.get("NTP") == "yes", d.get("CanNTP") == "yes"


_TZ = None


def timezones():
    global _TZ
    if _TZ is None:
        _TZ = [t for t in run_sync(["timedatectl", "list-timezones"], timeout=4).splitlines() if t]
    return _TZ


# ─── profile ────────────────────────────────────────────────────────────────
FACE = C.HOME / ".face"


def avatar_set(src, done=None):
    """nb-avatar: a 512px square into ~/.face (+ .face.icon) and the photo for the login screen."""
    run_async([str(BIN / "nb-avatar"), "set", src, "--quiet"], lambda ok, _o: done and done(ok))


def avatar_remove():
    for p in (FACE, C.HOME / ".face.icon"):
        try:
            p.unlink()
        except OSError:
            pass
