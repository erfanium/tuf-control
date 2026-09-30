"""Hardware access: sysfs sensors, asusctl/supergfxctl wrappers and the
privileged operations (PPT re-apply, factory fan curve reset)."""

import glob
import os
import re
import shutil
import time

from gi.repository import Gio, GLib

ARMOURY = "/sys/class/firmware-attributes/asus-armoury/attributes"
NBWMI = "/sys/devices/platform/asus-nb-wmi"
FAN_CONFIG = "/etc/asusd/fan_curves.ron"

def _power_supply(kind):
    for d in sorted(glob.glob("/sys/class/power_supply/*")):
        try:
            with open(os.path.join(d, "type")) as f:
                if f.read().strip() == kind:
                    return d
        except OSError:
            pass
    return "/nonexistent"


BATTERY = _power_supply("Battery")
AC = _power_supply("Mains")
KBD_LED = "/sys/class/leds/asus::kbd_backlight"
HELPER = "/usr/local/libexec/tuf-control-helper"

PROFILES = ["Quiet", "Balanced", "Performance"]
KBD_LEVELS = ["off", "low", "med", "high"]

# Built-in curve presets (temperature °C, duty %)
PRESETS = {
    "silent": [(40, 0), (45, 0), (50, 0), (55, 0), (60, 35), (65, 55), (70, 75), (80, 100)],
    "floor": [(30, 15), (40, 15), (45, 20), (50, 35), (55, 50), (60, 65), (70, 85), (80, 100)],
    "full": [(30, 100), (40, 100), (50, 100), (60, 100), (70, 100), (80, 100), (90, 100), (100, 100)],
}


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def read_int(path, default=None):
    v = read(path)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def find_hwmon(name):
    for d in glob.glob("/sys/class/hwmon/hwmon*"):
        if read(os.path.join(d, "name")) == name:
            return d
    return None


# --------------------------------------------------------------------------
# Async process helpers


def run(argv, callback=None):
    """Run argv asynchronously; callback(ok, stdout, stderr) on the main loop."""
    try:
        proc = Gio.Subprocess.new(
            argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        )
    except GLib.Error as e:
        if callback:
            GLib.idle_add(lambda: callback(False, "", e.message) and False)
        return

    def done(p, res):
        try:
            _, out, err = p.communicate_utf8_finish(res)
            ok = p.get_successful()
        except GLib.Error as e:
            ok, out, err = False, "", e.message
        if callback:
            callback(ok, out or "", (err or out or "").strip())

    proc.communicate_utf8_async(None, None, done)


def run_chain(steps, callback):
    """Run a list of steps sequentially, stopping at the first failure.

    A step is an argv list, a float (seconds to wait) or a callable taking a
    continuation `next(ok, err)`.
    """
    steps = list(steps)

    def step(ok=True, _out="", err=""):
        if not ok:
            callback(False, err)
            return
        if not steps:
            callback(True, "")
            return
        s = steps.pop(0)
        if isinstance(s, (int, float)):
            GLib.timeout_add(int(s * 1000), lambda: step() and False)
        elif callable(s):
            s(lambda ok, err="": step(ok, "", err))
        else:
            run(s, step)

    step()


def clean_err(err):
    lines = [
        ln for ln in err.splitlines()
        if ln.strip() and "Multiple asusd interfaces" not in ln
    ]
    return lines[-1] if lines else "Command failed"


# --------------------------------------------------------------------------
# Sensors


class Sensors:
    def __init__(self):
        self.coretemp = find_hwmon("coretemp")
        self.asus = find_hwmon("asus")
        self.curve = find_hwmon("asus_custom_fan_curve")
        self.nvme = find_hwmon("nvme")
        self.acpitz = find_hwmon("acpitz")
        self._last_stat = None

    def _cpu_usage(self):
        try:
            with open("/proc/stat") as f:
                parts = [int(x) for x in f.readline().split()[1:]]
        except OSError:
            return None
        idle = parts[3] + parts[4]
        total = sum(parts)
        prev, self._last_stat = self._last_stat, (idle, total)
        if not prev or total == prev[1]:
            return None
        return 100.0 * (1 - (idle - prev[0]) / (total - prev[1]))

    def _cpu_freq(self):
        freqs = [
            read_int(p)
            for p in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq")
        ]
        freqs = [f for f in freqs if f]
        return (max(freqs) / 1000, sum(freqs) / len(freqs) / 1000) if freqs else (None, None)

    def sample(self):
        s = {"time": time.monotonic()}
        t = read_int(f"{self.coretemp}/temp1_input") if self.coretemp else None
        s["cpu_temp"] = t / 1000 if t is not None else None
        t = read_int(f"{self.acpitz}/temp1_input") if self.acpitz else None
        s["board_temp"] = t / 1000 if t is not None else None
        t = read_int(f"{self.nvme}/temp1_input") if self.nvme else None
        s["ssd_temp"] = t / 1000 if t is not None else None
        s["cpu_fan"] = read_int(f"{self.asus}/fan1_input") if self.asus else None
        s["gpu_fan"] = read_int(f"{self.asus}/fan2_input") if self.asus else None
        s["cpu_usage"] = self._cpu_usage()
        s["freq_max"], s["freq_avg"] = self._cpu_freq()
        s["curve_enable"] = read_int(f"{self.curve}/pwm1_enable") if self.curve else None

        s["bat_status"] = read(f"{BATTERY}/status", "Unknown")
        s["bat_capacity"] = read_int(f"{BATTERY}/capacity")
        cur = read_int(f"{BATTERY}/current_now")
        volt = read_int(f"{BATTERY}/voltage_now")
        s["bat_power"] = cur * volt / 1e12 if cur is not None and volt else None
        s["ac_online"] = read(f"{AC}/online") == "1"
        return s


def battery_info():
    full = read_int(f"{BATTERY}/charge_full")
    design = read_int(f"{BATTERY}/charge_full_design")
    volt = read_int(f"{BATTERY}/voltage_min_design")
    return {
        "health": 100 * full / design if full and design else None,
        "full_wh": full * volt / 1e12 if full and volt else None,
        "design_wh": design * volt / 1e12 if design and volt else None,
        "cycles": read_int(f"{BATTERY}/cycle_count"),
        "limit": read_int(f"{BATTERY}/charge_control_end_threshold"),
        "model": read(f"{BATTERY}/model_name", ""),
        "technology": read(f"{BATTERY}/technology", ""),
    }


def system_info():
    return {
        "product": read("/sys/class/dmi/id/product_name", "ASUS Laptop").replace("_", " "),
        "family": read("/sys/class/dmi/id/product_family", ""),
        "bios": read("/sys/class/dmi/id/bios_version", ""),
    }


# --------------------------------------------------------------------------
# Firmware attributes


def attr(name):
    base = os.path.join(ARMOURY, name)
    if not os.path.isdir(base):
        return None
    return {
        "current": read_int(f"{base}/current_value"),
        "default": read_int(f"{base}/default_value"),
        "min": read_int(f"{base}/min_value"),
        "max": read_int(f"{base}/max_value"),
    }


def set_armoury(name, value, callback):
    run(["asusctl", "armoury", "set", name, str(value)],
        lambda ok, out, err: callback(ok, "" if ok else clean_err(err)))


# --------------------------------------------------------------------------
# Privileged operations


def _privileged(helper_args, shell_cmd):
    """argv for a root operation: the installed helper if available (no
    password thanks to its polkit policy), otherwise pkexec + bash -c."""
    if os.getuid() == 0:
        return ["bash", "-c", shell_cmd]
    if os.access(HELPER, os.X_OK):
        return ["pkexec", HELPER] + helper_args
    return ["pkexec", "bash", "-c", shell_cmd]


def ppt_argv(pl1=None, pl2=None):
    """Write PL1/PL2. Without values, re-apply firmware defaults — this is the
    FX507 400 MHz clamp workaround (see README)."""
    if os.path.isdir(f"{ARMOURY}/ppt_pl1_spl"):
        if pl1 is None:
            pl1 = read_int(f"{ARMOURY}/ppt_pl1_spl/default_value", 80)
            pl2 = read_int(f"{ARMOURY}/ppt_pl2_sppt/default_value", 80)
        cmd = (f"echo {int(pl1)} > '{ARMOURY}/ppt_pl1_spl/current_value'; "
               f"echo {int(pl2)} > '{ARMOURY}/ppt_pl2_sppt/current_value'")
    elif os.path.exists(f"{NBWMI}/ppt_pl1_spl"):
        pl1 = 80 if pl1 is None else pl1
        pl2 = 80 if pl2 is None else pl2
        cmd = f"echo {int(pl1)} > '{NBWMI}/ppt_pl1_spl'; echo {int(pl2)} > '{NBWMI}/ppt_pl2_sppt'"
    else:
        return None, None, None
    return _privileged(["ppt", str(int(pl1)), str(int(pl2))], cmd), pl1, pl2


def fix_ppt(callback, pl1=None, pl2=None):
    argv, pl1, pl2 = ppt_argv(pl1, pl2)
    if not argv:
        callback(False, "No PPT interface found")
        return
    run(argv, lambda ok, out, err: callback(
        ok, f"Power limits set: PL1 {pl1} W · PL2 {pl2} W" if ok else clean_err(err)))


def reset_fan_curve(callback):
    curve = find_hwmon("asus_custom_fan_curve")
    if not curve:
        callback(False, "asus_custom_fan_curve hwmon not found")
        return
    cmd = (f"echo 3 > '{curve}/pwm1_enable'; echo 3 > '{curve}/pwm2_enable'; "
           f"sed -i 's/^\\(\\s*\\)enabled: true,/\\1enabled: false,/' '{FAN_CONFIG}'; "
           "systemctl restart asusd")
    run(_privileged(["reset-curve"], cmd),
        lambda ok, out, err: callback(ok, "Factory fan curve restored" if ok else clean_err(err)))


def curve_to_data(points):
    return ",".join(f"{int(t)}c:{int(p)}%" for t, p in points)


def apply_fan_curves(profile, cpu_points, gpu_points, callback):
    """Set both curves, enable them, wait, then re-apply
    the CPU power limits the BIOS drops when a custom curve is enabled."""
    steps = [
        ["asusctl", "fan-curve", "--mod-profile", profile, "--fan", "cpu",
         "--data", curve_to_data(cpu_points)],
        ["asusctl", "fan-curve", "--mod-profile", profile, "--fan", "gpu",
         "--data", curve_to_data(gpu_points)],
        ["asusctl", "fan-curve", "--mod-profile", profile, "--enable-fan-curves", "true"],
        1.0,
        lambda nxt: fix_ppt(lambda ok, msg: nxt(ok, msg)),
    ]
    run_chain(steps, lambda ok, err: callback(
        ok, f"Fan curve applied to {profile}" if ok else clean_err(err)))


_CURVE_RE = re.compile(
    r"fan:\s*(\w+),\s*pwm:\s*\(([^)]*)\),\s*temp:\s*\(([^)]*)\),\s*enabled:\s*(\w+)", re.S)


def get_fan_curves(profile, callback):
    """callback({'cpu': {'points': [...], 'enabled': bool}, 'gpu': ...} or None)"""

    def done(ok, out, err):
        if not ok:
            callback(None)
            return
        curves = {}
        for fan, pwm, temp, enabled in _CURVE_RE.findall(out):
            pwm = [int(x) for x in pwm.split(",") if x.strip()]
            temp = [int(x) for x in temp.split(",") if x.strip()]
            curves[fan.lower()] = {
                "points": [(t, round(p * 100 / 255)) for t, p in zip(temp, pwm)],
                "enabled": enabled == "true",
            }
        callback(curves or None)

    run(["asusctl", "fan-curve", "--mod-profile", profile], done)


# --------------------------------------------------------------------------
# asusctl simple getters/setters


def get_profiles(callback):
    def done(ok, out, err):
        res = {}
        for key, pat in (("active", r"Active profile:\s*(\w+)"),
                         ("ac", r"AC profile\s*(\w+)"),
                         ("battery", r"Battery profile\s*(\w+)")):
            m = re.search(pat, out)
            if m:
                res[key] = m.group(1)
        callback(res)

    run(["asusctl", "profile", "get"], done)


def set_profile(profile, callback, target=None):
    argv = ["asusctl", "profile", "set"]
    if target == "ac":
        argv.append("-a")
    elif target == "battery":
        argv.append("-b")
    run(argv + [profile], lambda ok, out, err: callback(ok, "" if ok else clean_err(err)))


def get_kbd_level():
    v = read_int(f"{KBD_LED}/brightness")
    return v if v is not None else 0


def set_kbd_level(level, callback):
    run(["asusctl", "leds", "set", KBD_LEVELS[level]],
        lambda ok, out, err: callback(ok, "" if ok else clean_err(err)))


def set_charge_limit(limit, callback):
    run(["asusctl", "battery", "limit", str(int(limit))],
        lambda ok, out, err: callback(ok, "" if ok else clean_err(err)))


def charge_oneshot(callback):
    run(["asusctl", "battery", "oneshot"],
        lambda ok, out, err: callback(ok, "" if ok else clean_err(err)))


def set_aura(effect, colour, colour2, speed, callback):
    argv = ["asusctl", "aura", "effect", effect]
    if effect in ("static", "pulse"):
        argv += ["-c", colour]
    elif effect == "breathe":
        argv += ["--colour", colour, "--colour2", colour2, "--speed", speed]
    elif effect == "rainbow-cycle":
        argv += ["--speed", speed]
    run(argv, lambda ok, out, err: callback(ok, "" if ok else clean_err(err)))


# --------------------------------------------------------------------------
# Graphics (supergfxctl)

GFX_AVAILABLE = shutil.which("supergfxctl") is not None


def get_gfx(callback):
    if not GFX_AVAILABLE:
        callback(None)
        return
    res = {}

    def got_supported(ok, out, err):
        res["supported"] = re.findall(r"\w+", out) if ok else []
        run(["supergfxctl", "-g"], got_mode)

    def got_mode(ok, out, err):
        res["mode"] = out.strip() if ok else None
        run(["supergfxctl", "-S"], got_status)

    def got_status(ok, out, err):
        res["status"] = out.strip() if ok else None
        run(["supergfxctl", "-p"], got_pending)

    def got_pending(ok, out, err):
        res["pending"] = out.strip() if ok else None
        callback(res)

    run(["supergfxctl", "-s"], got_supported)


def set_gfx(mode, callback):
    run(["supergfxctl", "-m", mode],
        lambda ok, out, err: callback(ok, out.strip() if ok else clean_err(err)))
