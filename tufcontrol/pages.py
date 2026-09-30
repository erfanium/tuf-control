"""Content pages of the control center."""

import json
import os

from gi.repository import Adw, Gdk, GLib, Gtk

from . import backend as hw
from .curve import CurveEditor, Sparkline

STATE_FILE = os.path.join(GLib.get_user_config_dir(), "tuf-control", "state.json")

PROFILE_ICONS = {
    "Quiet": "power-profile-power-saver-symbolic",
    "Balanced": "power-profile-balanced-symbolic",
    "Performance": "power-profile-performance-symbolic",
}
PROFILE_DESC = {
    "Quiet": "Lowest noise and power draw",
    "Balanced": "Everyday performance",
    "Performance": "Maximum power, louder fans",
}


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fmt(v, spec, unit="", none="—"):
    return none if v is None else f"{v:{spec}}{unit}"


def toggle_group(items, on_change):
    """items: [(name, label, icon)] → Adw.ToggleGroup with a silent setter."""
    group = Adw.ToggleGroup()
    for name, label, icon in items:
        t = Adw.Toggle(name=name, tooltip=label)
        if label:
            t.set_label(label)
        if icon and not label:
            t.set_icon_name(icon)
        group.add(t)
    group._silent = False

    def changed(g, _p):
        if not g._silent and g.get_active_name():
            on_change(g.get_active_name())

    group.connect("notify::active-name", changed)

    def set_silently(name):
        group._silent = True
        group.set_active_name(name)
        group._silent = False

    group.set_silently = set_silently
    return group


class Page(Adw.PreferencesPage):
    title = ""
    icon = ""

    def __init__(self, win):
        super().__init__()
        self.win = win

    def update(self, sample):
        pass

    def refresh(self):
        pass

    def done(self, ok_msg=None):
        """Standard result handler that shows a toast."""
        def cb(ok, msg=""):
            if ok:
                if ok_msg or msg:
                    self.win.toast(ok_msg or msg)
            else:
                self.win.toast(f"Failed: {msg}")
            self.refresh()
        return cb


# ==========================================================================
# Overview


class StatCard(Gtk.Box):
    def __init__(self, icon, title, unit="", spark=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("card")
        self.add_css_class("stat-card")

        head = Gtk.Box(spacing=8)
        img = Gtk.Image.new_from_icon_name(icon)
        img.add_css_class("stat-icon")
        head.append(img)
        lbl = Gtk.Label(label=title, xalign=0, hexpand=True)
        lbl.add_css_class("caption-heading")
        lbl.add_css_class("dim-label")
        head.append(lbl)
        self.sub = Gtk.Label(xalign=1)
        self.sub.add_css_class("caption")
        self.sub.add_css_class("dim-label")
        head.append(self.sub)
        self.append(head)

        row = Gtk.Box(spacing=4)
        self.value = Gtk.Label(label="—", xalign=0)
        self.value.add_css_class("stat-value")
        row.append(self.value)
        self.unit = Gtk.Label(label=unit, xalign=0, valign=Gtk.Align.BASELINE)
        self.unit.add_css_class("stat-unit")
        self.unit.add_css_class("dim-label")
        row.append(self.unit)
        self.append(row)

        self.spark = None
        if spark:
            self.spark = Sparkline(*spark)
            self.append(self.spark)

    def set(self, value, sub=None, spark_value=None):
        self.value.set_label(value)
        if sub is not None:
            self.sub.set_label(sub)
        if self.spark is not None:
            self.spark.push(spark_value)


class OverviewPage(Page):
    title = "Overview"
    icon = "computer-symbolic"

    def __init__(self, win):
        super().__init__(win)
        info = hw.system_info()

        # Hero
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_bottom=6)
        t = Gtk.Label(label=info["family"] or info["product"], xalign=0, wrap=True)
        t.add_css_class("title-1")
        hero.append(t)
        s = Gtk.Label(label=f"{info['product']}  ·  BIOS {info['bios']}", xalign=0, wrap=True)
        s.add_css_class("dim-label")
        hero.append(s)
        g = Adw.PreferencesGroup()
        g.add(hero)
        self.add(g)

        # Stat cards
        self.cards = {
            "cpu_temp": StatCard("tuf-temperature-symbolic", "CPU Temperature", "°C", (30, 100)),
            "cpu_usage": StatCard("tuf-chip-symbolic", "CPU Load", "%", (0, 100)),
            "cpu_fan": StatCard("tuf-fan-symbolic", "CPU Fan", "RPM", (0, 6000)),
            "gpu_fan": StatCard("tuf-fan-symbolic", "GPU Fan", "RPM", (0, 6000)),
            "freq": StatCard("tuf-speed-symbolic", "CPU Clock", "GHz", (0, 5)),
            "battery": StatCard("battery-level-80-symbolic", "Battery", "%"),
        }
        flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
            min_children_per_line=1, max_children_per_line=3,
            column_spacing=12, row_spacing=12,
        )
        for c in self.cards.values():
            flow.append(c)
            c.get_parent().set_focusable(False)
        g = Adw.PreferencesGroup()
        g.add(flow)
        self.add(g)

        # Quick controls
        g = Adw.PreferencesGroup(title="Quick Settings")
        row = Adw.ActionRow(title="Power Profile")
        row.add_prefix(Gtk.Image.new_from_icon_name("power-profile-balanced-symbolic"))
        self.profile_row = row
        self.profile = toggle_group(
            [(p, p, None) for p in hw.PROFILES],
            lambda name: hw.set_profile(name, self.win.after_profile_change),
        )
        self.profile.set_valign(Gtk.Align.CENTER)
        row.add_suffix(self.profile)
        g.add(row)

        row = Adw.ActionRow(title="Keyboard Backlight")
        row.add_prefix(Gtk.Image.new_from_icon_name("keyboard-brightness-symbolic"))
        self.kbd = toggle_group(
            [(str(i), n, None) for i, n in enumerate(["Off", "Low", "Mid", "High"])],
            lambda name: hw.set_kbd_level(int(name), self.done()),
        )
        self.kbd.set_valign(Gtk.Align.CENTER)
        row.add_suffix(self.kbd)
        g.add(row)

        self.fan_row = Adw.ActionRow(title="Fan Mode", activatable=True)
        self.fan_row.add_prefix(Gtk.Image.new_from_icon_name("tuf-fan-symbolic"))
        self.fan_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        self.fan_row.connect("activated", lambda *_: self.win.show_page("fans"))
        g.add(self.fan_row)
        self.add(g)

    def refresh(self):
        self.kbd.set_silently(str(hw.get_kbd_level()))
        hw.get_profiles(self._got_profiles)

    def _got_profiles(self, p):
        if "active" in p:
            self.profile.set_silently(p["active"])
            self.profile_row.set_subtitle(PROFILE_DESC.get(p["active"], ""))

    def update(self, s):
        c = self.cards
        c["cpu_temp"].set(fmt(s["cpu_temp"], ".0f"),
                          f"SSD {fmt(s['ssd_temp'], '.0f', '°')}", s["cpu_temp"])
        c["cpu_usage"].set(fmt(s["cpu_usage"], ".0f"), None, s["cpu_usage"])
        c["cpu_fan"].set(fmt(s["cpu_fan"], "d"), None, s["cpu_fan"])
        c["gpu_fan"].set(fmt(s["gpu_fan"], "d"), None, s["gpu_fan"])
        fmax = s["freq_max"] / 1000 if s["freq_max"] else None
        favg = s["freq_avg"] / 1000 if s["freq_avg"] else None
        c["freq"].set(fmt(fmax, ".2f"), f"avg {fmt(favg, '.1f', ' GHz')}", fmax)

        cap = s["bat_capacity"]
        status = s["bat_status"]
        if s["bat_power"] and status in ("Charging", "Discharging"):
            status += f" · {s['bat_power']:.1f} W"
        c["battery"].set(fmt(cap, "d"), status)
        if cap is not None:
            level = min(100, max(0, round(cap / 10) * 10))
            suffix = "-charging" if s["bat_status"] == "Charging" else (
                "-plugged-in" if s["ac_online"] else "")
            img = c["battery"].get_first_child().get_first_child()
            img.set_from_icon_name(f"battery-level-{level}{suffix}-symbolic")

        custom = s["curve_enable"] == 1
        self.fan_row.set_subtitle("Custom curve" if custom else "Firmware automatic")


# ==========================================================================
# Fans


class FansPage(Page):
    title = "Fans"
    icon = "tuf-fan-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.state = load_state()
        self.curves = {"cpu": None, "gpu": None}
        self.saved = {"cpu": None, "gpu": None}
        self.fan = "cpu"
        self.active_profile = None
        self._loading = False

        # --- live status
        g = Adw.PreferencesGroup(title="Status")
        self.mode_row = Adw.ActionRow(title="Fan Control")
        self.mode_row.add_prefix(Gtk.Image.new_from_icon_name("tuf-fan-symbolic"))
        self.mode_badge = Gtk.Label(valign=Gtk.Align.CENTER)
        self.mode_badge.add_css_class("badge")
        self.mode_row.add_suffix(self.mode_badge)
        g.add(self.mode_row)

        self.rpm_rows = {}
        for key, title in (("cpu_fan", "CPU Fan"), ("gpu_fan", "GPU Fan")):
            row = Adw.ActionRow(title=title)
            bar = Gtk.LevelBar(min_value=0, max_value=6500, valign=Gtk.Align.CENTER, width_request=140)
            bar.remove_offset_value("low")
            bar.remove_offset_value("high")
            bar.remove_offset_value("full")
            lbl = Gtk.Label(width_chars=9, xalign=1)
            lbl.add_css_class("numeric")
            row.add_suffix(bar)
            row.add_suffix(lbl)
            g.add(row)
            self.rpm_rows[key] = (bar, lbl)
        self.add(g)

        # --- curve editor
        g = Adw.PreferencesGroup(title="Fan Curve")
        self.curve_group = g
        self.fan_switch = toggle_group(
            [("cpu", "CPU", None), ("gpu", "GPU", None)], self._switch_fan)
        self.fan_switch.set_valign(Gtk.Align.CENTER)
        g.set_header_suffix(self.fan_switch)

        self.profile_combo = Adw.ComboRow(
            title="Profile", subtitle="Each power profile keeps its own curve",
            model=Gtk.StringList.new(hw.PROFILES))
        self.profile_combo.connect("notify::selected", lambda *_: self._load_curves())
        g.add(self.profile_combo)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12)
        card.add_css_class("card")
        card.add_css_class("curve-card")
        self.editor = CurveEditor()
        self.editor.connect("changed", self._edited)
        card.append(self.editor)

        presets = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        for name, label in (("silent", "Silent"), ("floor", "Floor"), ("full", "Full Speed")):
            b = Gtk.Button(label=label)
            b.add_css_class("pill")
            b.add_css_class("small-pill")
            b.connect("clicked", self._preset, name)
            presets.append(b)
        card.append(presets)
        hint = Gtk.Label(
            label="Drag points to shape the curve. The orange line shows the current CPU temperature.",
            wrap=True, justify=Gtk.Justification.CENTER)
        hint.add_css_class("caption")
        hint.add_css_class("dim-label")
        card.append(hint)
        g.add(card)

        self.link_row = Adw.SwitchRow(
            title="Same Curve for Both Fans",
            subtitle="Edits to one fan are mirrored to the other",
            active=self.state.get("link_fans", True))
        self.link_row.connect("notify::active", self._link_changed)
        links = Adw.PreferencesGroup(margin_top=12)
        links.add(self.link_row)

        g.add(links)
        self.add(g)

        # --- actions
        bar = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, margin_top=6)
        self.revert_btn = Gtk.Button(label="Revert", sensitive=False)
        self.revert_btn.add_css_class("pill")
        self.revert_btn.connect("clicked", lambda *_: self._revert())
        self.apply_btn = Gtk.Button(label="Apply Curve")
        self.apply_btn.add_css_class("pill")
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", lambda *_: self._apply())
        bar.append(self.revert_btn)
        bar.append(self.apply_btn)
        g = Adw.PreferencesGroup()
        g.add(bar)
        self.add(g)

        # --- troubleshooting
        g = Adw.PreferencesGroup(
            title="Troubleshooting",
            description="On FX507 the BIOS drops the CPU power limits when a custom "
                        "curve is enabled, pinning the CPU at 400 MHz. Applying a "
                        "curve re-sets them automatically.")
        r = Adw.ButtonRow(title="Re-apply CPU Power Limits", start_icon_name="view-refresh-symbolic")
        r.connect("activated", lambda *_: hw.fix_ppt(self.done()))
        g.add(r)
        r = Adw.ButtonRow(title="Restore Factory Fan Curve", start_icon_name="edit-undo-symbolic")
        r.add_css_class("destructive-action")
        r.connect("activated", lambda *_: self._confirm_reset())
        g.add(r)
        self.add(g)

    # ---------------------------------------------------------------- loading

    def refresh(self):
        hw.get_profiles(self._got_profiles)

    def _got_profiles(self, p):
        active = p.get("active")
        if active and active != self.active_profile:
            self.active_profile = active
            if active in hw.PROFILES:
                self.profile_combo.set_selected(hw.PROFILES.index(active))
            self._load_curves()
        elif self.curves["cpu"] is None:
            self._load_curves()

    def profile(self):
        return hw.PROFILES[self.profile_combo.get_selected()]

    def _load_curves(self):
        prof = self.profile()
        active = " (active)" if prof == self.active_profile else ""
        self.profile_combo.set_subtitle(f"Editing the {prof} profile{active}")
        hw.get_fan_curves(prof, self._got_curves)

    def _got_curves(self, curves):
        if not curves:
            self.win.toast("Could not read fan curves from asusd")
            return
        for fan in ("cpu", "gpu"):
            if fan in curves:
                self.curves[fan] = list(curves[fan]["points"])
                self.saved[fan] = list(curves[fan]["points"])
        self.enabled_in_profile = any(c["enabled"] for c in curves.values())
        self._show()
        self._dirty(False)

    def _show(self):
        other = "gpu" if self.fan == "cpu" else "cpu"
        if self.curves[self.fan]:
            self.editor.set_points(self.curves[self.fan])
        linked = self.link_row.get_active() and self.curves[self.fan] == self.curves[other]
        self.editor.set_ghost(None if linked else self.curves[other])

    # ---------------------------------------------------------------- editing

    def _switch_fan(self, name):
        self.fan = name
        self._show()

    def _edited(self, _e):
        pts = list(self.editor.points)
        self.curves[self.fan] = pts
        if self.link_row.get_active():
            self.curves["gpu" if self.fan == "cpu" else "cpu"] = list(pts)
        self._dirty(True)

    def _preset(self, _b, name):
        self.editor.set_points(hw.PRESETS[name], emit=True)

    def _link_changed(self, row, _p):
        self.state["link_fans"] = row.get_active()
        save_state(self.state)
        if row.get_active():
            other = "gpu" if self.fan == "cpu" else "cpu"
            self.curves[other] = list(self.curves[self.fan] or [])
            self._dirty(True)
        self._show()

    def _dirty(self, dirty):
        dirty = dirty and self.curves != self.saved
        self.revert_btn.set_sensitive(dirty)

    def _revert(self):
        self.curves = {k: list(v) if v else v for k, v in self.saved.items()}
        self._show()
        self._dirty(False)

    # ----------------------------------------------------------------- apply

    def _apply(self):
        if not self.curves["cpu"] or not self.curves["gpu"]:
            return
        self.apply_btn.set_sensitive(False)
        self.apply_btn.set_label("Applying…")

        def finished(ok, msg):
            self.apply_btn.set_sensitive(True)
            self.apply_btn.set_label("Apply Curve")
            self.win.toast(msg if ok else f"Failed: {msg}")
            self._load_curves()

        hw.apply_fan_curves(self.profile(), self.curves["cpu"], self.curves["gpu"], finished)

    def _confirm_reset(self):
        d = Adw.AlertDialog(
            heading="Restore Factory Fan Curve?",
            body="Custom curves will be disabled for all profiles and asusd will be "
                 "restarted. The CPU recovers full speed in about 30 seconds.")
        d.add_response("cancel", "Cancel")
        d.add_response("reset", "Restore")
        d.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")

        def resp(_d, r):
            if r == "reset":
                hw.reset_fan_curve(lambda ok, msg: (
                    self.win.toast(msg if ok else f"Failed: {msg}"),
                    GLib.timeout_add_seconds(3, lambda: self._load_curves() and False)))

        d.connect("response", resp)
        d.present(self.win)

    # ---------------------------------------------------------------- update

    def update(self, s):
        for key, (bar, lbl) in self.rpm_rows.items():
            v = s[key] or 0
            bar.set_value(min(v, 6500))
            lbl.set_label(f"{v} RPM")
        custom = s["curve_enable"] == 1
        self.mode_row.set_subtitle(
            "Following your custom curve" if custom else "Firmware controls the fans")
        self.mode_badge.set_label("Custom" if custom else "Auto")
        self.mode_badge.set_css_classes(["badge", "accent" if custom else "dim"])
        self.editor.set_live_temp(s["cpu_temp"])


# ==========================================================================
# Performance


class PerformancePage(Page):
    title = "Performance"
    icon = "power-profile-performance-symbolic"

    def __init__(self, win):
        super().__init__(win)

        # --- profile picker (big cards)
        g = Adw.PreferencesGroup(title="Power Profile")
        box = Gtk.Box(spacing=12, homogeneous=True)
        self.profile_buttons = {}
        group = None
        for p in hw.PROFILES:
            b = Gtk.ToggleButton(group=group)
            group = group or b
            b.add_css_class("profile-card")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                            margin_top=14, margin_bottom=14)
            img = Gtk.Image.new_from_icon_name(PROFILE_ICONS[p])
            img.set_pixel_size(32)
            inner.append(img)
            lbl = Gtk.Label(label=p)
            lbl.add_css_class("heading")
            inner.append(lbl)
            d = Gtk.Label(label=PROFILE_DESC[p], wrap=True, justify=Gtk.Justification.CENTER)
            d.add_css_class("caption")
            d.add_css_class("dim-label")
            inner.append(d)
            b.set_child(inner)
            b.connect("toggled", self._profile_toggled, p)
            box.append(b)
            self.profile_buttons[p] = b
        self._silent = False
        g.add(box)
        self.add(g)

        g = Adw.PreferencesGroup(title="Automatic Switching",
                                 description="Profile applied when the power source changes")
        self.ac_row = Adw.ComboRow(title="On AC Power", model=Gtk.StringList.new(hw.PROFILES))
        self.ac_row.add_prefix(Gtk.Image.new_from_icon_name("ac-adapter-symbolic"))
        self.bat_row = Adw.ComboRow(title="On Battery", model=Gtk.StringList.new(hw.PROFILES))
        self.bat_row.add_prefix(Gtk.Image.new_from_icon_name("battery-level-50-symbolic"))
        self.ac_row.connect("notify::selected", self._auto_changed, "ac")
        self.bat_row.connect("notify::selected", self._auto_changed, "battery")
        g.add(self.ac_row)
        g.add(self.bat_row)
        self.add(g)

        # --- PPT
        pl1 = hw.attr("ppt_pl1_spl")
        pl2 = hw.attr("ppt_pl2_sppt")
        self.ppt_group = None
        if pl1 and pl2:
            g = Adw.PreferencesGroup(
                title="CPU Power Limits",
                description="Package power the CPU may draw. Writing these needs administrator rights.")
            self.pl1 = Adw.SpinRow.new_with_range(pl1["min"], pl1["max"], 1)
            self.pl1.set_title("Sustained (PL1)")
            self.pl1.set_subtitle("Long-term power limit, in watts")
            self.pl2 = Adw.SpinRow.new_with_range(pl2["min"], pl2["max"], 1)
            self.pl2.set_title("Boost (PL2)")
            self.pl2.set_subtitle("Short-term turbo limit, in watts")
            g.add(self.pl1)
            g.add(self.pl2)
            btns = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
            b = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Firmware Defaults")
            b.add_css_class("flat")
            b.connect("clicked", lambda *_: hw.fix_ppt(self.done()))
            btns.append(b)
            b = Gtk.Button(label="Apply")
            b.add_css_class("suggested-action")
            b.connect("clicked", self._apply_ppt)
            btns.append(b)
            g.set_header_suffix(btns)
            self.ppt_group = g
            self.add(g)

        # --- GPU / display
        g = Adw.PreferencesGroup(title="Tuning")
        self.boost = None
        nb = hw.attr("nv_dynamic_boost")
        if nb and nb["min"] is not None:
            self.boost = Adw.SpinRow.new_with_range(nb["min"], nb["max"], 1)
            self.boost.set_title("NVIDIA Dynamic Boost")
            self.boost.set_subtitle("Extra watts shifted from CPU to GPU")
            self.boost.add_prefix(Gtk.Image.new_from_icon_name("tuf-gpu-symbolic"))
            self._boost_timer = 0
            self.boost.connect("notify::value", self._boost_changed)
            g.add(self.boost)
        self.overdrive = None
        if hw.attr("panel_overdrive"):
            self.overdrive = Adw.SwitchRow(title="Panel Overdrive",
                                           subtitle="Faster pixel response, may cause ghosting")
            self.overdrive.add_prefix(Gtk.Image.new_from_icon_name("video-display-symbolic"))
            self.overdrive.connect("notify::active", self._overdrive_changed)
            g.add(self.overdrive)
        if self.boost or self.overdrive:
            self.add(g)

    def refresh(self):
        self._silent = True
        pl1, pl2 = hw.attr("ppt_pl1_spl"), hw.attr("ppt_pl2_sppt")
        if self.ppt_group and pl1 and pl2:
            self.pl1.set_value(pl1["current"])
            self.pl2.set_value(pl2["current"])
            self.ppt_group.set_description(
                f"Package power the CPU may draw. Firmware defaults for this profile: "
                f"{pl1['default']} W / {pl2['default']} W. Writing these needs administrator rights.")
        if self.boost:
            nb = hw.attr("nv_dynamic_boost")
            self.boost.set_value(nb["current"])
        if self.overdrive:
            self.overdrive.set_active(hw.attr("panel_overdrive")["current"] == 1)
        self._silent = False
        hw.get_profiles(self._got_profiles)

    def _got_profiles(self, p):
        self._silent = True
        if p.get("active") in self.profile_buttons:
            self.profile_buttons[p["active"]].set_active(True)
        if p.get("ac") in hw.PROFILES:
            self.ac_row.set_selected(hw.PROFILES.index(p["ac"]))
        if p.get("battery") in hw.PROFILES:
            self.bat_row.set_selected(hw.PROFILES.index(p["battery"]))
        self._silent = False

    def _profile_toggled(self, b, p):
        if b.get_active() and not self._silent:
            hw.set_profile(p, self.win.after_profile_change)

    def _auto_changed(self, row, _p, target):
        if not self._silent:
            hw.set_profile(hw.PROFILES[row.get_selected()], self.done(), target)

    def _apply_ppt(self, _b):
        pl1, pl2 = int(self.pl1.get_value()), int(self.pl2.get_value())
        if pl2 < pl1:
            self.win.toast("Boost limit (PL2) must not be lower than PL1")
            return
        hw.fix_ppt(self.done(), pl1, pl2)

    def _boost_changed(self, row, _p):
        if self._silent:
            return
        if self._boost_timer:
            GLib.source_remove(self._boost_timer)

        def fire():
            self._boost_timer = 0
            hw.set_armoury("nv_dynamic_boost", int(row.get_value()),
                           self.done(f"Dynamic Boost set to {int(row.get_value())} W"))
            return False

        self._boost_timer = GLib.timeout_add(700, fire)

    def _overdrive_changed(self, row, _p):
        if not self._silent:
            hw.set_armoury("panel_overdrive", 1 if row.get_active() else 0, self.done())


# ==========================================================================
# Battery


class BatteryPage(Page):
    title = "Battery"
    icon = "battery-level-80-symbolic"

    def __init__(self, win):
        super().__init__(win)

        # hero
        hero = Gtk.Box(spacing=18, margin_bottom=6)
        self.hero_icon = Gtk.Image.new_from_icon_name("battery-level-80-symbolic")
        self.hero_icon.set_pixel_size(64)
        self.hero_icon.add_css_class("dim-label")
        hero.append(self.hero_icon)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
        self.hero_pct = Gtk.Label(xalign=0)
        self.hero_pct.add_css_class("stat-value")
        self.hero_pct.add_css_class("large")
        col.append(self.hero_pct)
        self.hero_status = Gtk.Label(xalign=0)
        self.hero_status.add_css_class("dim-label")
        col.append(self.hero_status)
        self.hero_bar = Gtk.LevelBar(min_value=0, max_value=100)
        self.hero_bar.add_css_class("battery-bar")
        col.append(self.hero_bar)
        hero.append(col)
        g = Adw.PreferencesGroup()
        g.add(hero)
        self.add(g)

        # charging
        g = Adw.PreferencesGroup(title="Charging")
        row = Adw.ActionRow(title="Charge Limit",
                            subtitle="Keeping the battery below 100% extends its lifespan")
        row.add_prefix(Gtk.Image.new_from_icon_name("battery-level-80-plugged-in-symbolic"))
        g.add(row)
        self.limit_row = row

        scale_row = Gtk.ListBoxRow(activatable=False)
        sbox = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 20, 100, 5)
        self.scale.set_hexpand(True)
        self.scale.set_draw_value(False)
        for v in (60, 80, 100):
            self.scale.add_mark(v, Gtk.PositionType.BOTTOM, f"{v}%")
        self.limit_lbl = Gtk.Label(width_chars=5, xalign=1)
        self.limit_lbl.add_css_class("title-3")
        self.limit_lbl.add_css_class("numeric")
        sbox.append(self.scale)
        sbox.append(self.limit_lbl)
        scale_row.set_child(sbox)
        g.add(scale_row)
        self._limit_timer = 0
        self._silent = False
        self.scale.connect("value-changed", self._limit_changed)

        r = Adw.ButtonRow(title="Charge to 100% Once", start_icon_name="battery-full-charging-symbolic")
        r.connect("activated", lambda *_: hw.charge_oneshot(
            self.done("Charging to 100% once; the limit returns afterwards")))
        g.add(r)
        self.add(g)

        # health
        g = Adw.PreferencesGroup(title="Health")
        self.health_rows = {}
        for key, title in (("health", "Capacity"), ("full", "Full Charge"),
                           ("cycles", "Charge Cycles"), ("model", "Battery")):
            r = Adw.ActionRow(title=title)
            lbl = Gtk.Label()
            lbl.add_css_class("dim-label")
            lbl.add_css_class("numeric")
            r.add_suffix(lbl)
            g.add(r)
            self.health_rows[key] = lbl
        self.add(g)

    def refresh(self):
        b = hw.battery_info()
        self._silent = True
        if b["limit"]:
            self.scale.set_value(b["limit"])
            self.limit_lbl.set_label(f"{b['limit']}%")
        self._silent = False
        self.health_rows["health"].set_label(fmt(b["health"], ".0f", "% of design"))
        self.health_rows["full"].set_label(
            f"{fmt(b['full_wh'], '.1f', ' Wh')} / {fmt(b['design_wh'], '.1f', ' Wh')}")
        self.health_rows["cycles"].set_label(str(b["cycles"]) if b["cycles"] else "Not reported")
        self.health_rows["model"].set_label(" · ".join(x for x in (b["model"], b["technology"]) if x))

    def _limit_changed(self, scale):
        v = int(round(scale.get_value()))
        self.limit_lbl.set_label(f"{v}%")
        if self._silent:
            return
        if self._limit_timer:
            GLib.source_remove(self._limit_timer)

        def fire():
            self._limit_timer = 0
            hw.set_charge_limit(v, self.done(f"Charge limit set to {v}%"))
            return False

        self._limit_timer = GLib.timeout_add(600, fire)

    def update(self, s):
        cap = s["bat_capacity"]
        self.hero_pct.set_label(fmt(cap, "d", "%"))
        st = s["bat_status"]
        if st == "Not charging":
            st = "Plugged in, not charging"
        if s["bat_power"] and s["bat_status"] in ("Charging", "Discharging"):
            st += f"  ·  {s['bat_power']:.1f} W"
        self.hero_status.set_label(st)
        if cap is not None:
            self.hero_bar.set_value(cap)
            level = min(100, max(0, round(cap / 10) * 10))
            suffix = "-charging" if s["bat_status"] == "Charging" else (
                "-plugged-in" if s["ac_online"] else "")
            self.hero_icon.set_from_icon_name(f"battery-level-{level}{suffix}-symbolic")


# ==========================================================================
# Lighting


AURA_EFFECTS = [
    ("static", "Static"),
    ("breathe", "Breathing"),
    ("rainbow-cycle", "Rainbow Cycle"),
    ("pulse", "Pulse"),
]
SPEEDS = [("low", "Slow"), ("med", "Medium"), ("high", "Fast")]


class LightingPage(Page):
    title = "Lighting"
    icon = "keyboard-brightness-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.state = load_state()
        aura = self.state.setdefault("aura", {})

        g = Adw.PreferencesGroup(title="Keyboard Backlight")
        box = Gtk.Box(spacing=12, homogeneous=True)
        self.levels = []
        group = None
        for i, name in enumerate(("Off", "Low", "Medium", "High")):
            b = Gtk.ToggleButton(group=group)
            group = group or b
            b.add_css_class("profile-card")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                            margin_top=12, margin_bottom=12)
            img = Gtk.Image.new_from_icon_name("keyboard-brightness-symbolic")
            img.set_pixel_size(24)
            img.add_css_class(f"kbd-level-{i}")
            inner.append(img)
            inner.append(Gtk.Label(label=name))
            b.set_child(inner)
            b.connect("toggled", self._level_toggled, i)
            box.append(b)
            self.levels.append(b)
        self._silent = False
        g.add(box)
        self.add(g)

        g = Adw.PreferencesGroup(title="Effect")
        self.effect = Adw.ComboRow(title="Mode",
                                   model=Gtk.StringList.new([n for _, n in AURA_EFFECTS]))
        keys = [k for k, _ in AURA_EFFECTS]
        self.effect.set_selected(keys.index(aura.get("effect", "static")) if aura.get("effect") in keys else 0)
        self.effect.connect("notify::selected", lambda *_: self._sync_rows())
        g.add(self.effect)

        self.colour_btn = self._colour_button(aura.get("colour", "ff2a00"))
        self.colour_row = Adw.ActionRow(title="Colour")
        self.colour_row.add_suffix(self.colour_btn)
        self.colour_row.set_activatable_widget(self.colour_btn)
        g.add(self.colour_row)

        self.colour2_btn = self._colour_button(aura.get("colour2", "0044ff"))
        self.colour2_row = Adw.ActionRow(title="Second Colour")
        self.colour2_row.add_suffix(self.colour2_btn)
        self.colour2_row.set_activatable_widget(self.colour2_btn)
        g.add(self.colour2_row)

        self.speed = Adw.ComboRow(title="Speed", model=Gtk.StringList.new([n for _, n in SPEEDS]))
        sk = [k for k, _ in SPEEDS]
        self.speed.set_selected(sk.index(aura.get("speed", "med")) if aura.get("speed") in sk else 1)
        g.add(self.speed)

        # swatches
        sw = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=12,
                         min_children_per_line=4, column_spacing=6, row_spacing=6,
                         margin_top=12, homogeneous=True)
        for hexc in ("ff2a00", "ff7a00", "ffd000", "36d11f", "00c8a0", "00a2ff",
                     "2b50ff", "8a2bff", "ff2bd6", "ffffff"):
            b = Gtk.Button(tooltip_text=f"#{hexc}", halign=Gtk.Align.CENTER)
            b.add_css_class("swatch")
            b.add_css_class(f"swatch-{hexc}")
            b.connect("clicked", self._swatch, hexc)
            sw.append(b)
        g.add(sw)

        apply = Gtk.Button(label="Apply Effect", halign=Gtk.Align.CENTER, margin_top=18)
        apply.add_css_class("pill")
        apply.add_css_class("suggested-action")
        apply.connect("clicked", self._apply)
        g.add(apply)
        self.add(g)
        self._sync_rows()

        css = "".join(f".swatch-{h} {{ background: #{h}; }}" for h in (
            "ff2a00", "ff7a00", "ffd000", "36d11f", "00c8a0", "00a2ff",
            "2b50ff", "8a2bff", "ff2bd6", "ffffff"))
        prov = Gtk.CssProvider()
        prov.load_from_string(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _colour_button(self, hexc):
        b = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        c = Gdk.RGBA()
        c.parse(f"#{hexc}")
        b.set_rgba(c)
        return b

    @staticmethod
    def _hex(btn):
        c = btn.get_rgba()
        return "%02x%02x%02x" % (round(c.red * 255), round(c.green * 255), round(c.blue * 255))

    def _swatch(self, _b, hexc):
        c = Gdk.RGBA()
        c.parse(f"#{hexc}")
        self.colour_btn.set_rgba(c)
        self._apply()

    def _sync_rows(self):
        eff = AURA_EFFECTS[self.effect.get_selected()][0]
        self.colour_row.set_visible(eff in ("static", "breathe", "pulse"))
        self.colour2_row.set_visible(eff == "breathe")
        self.speed.set_visible(eff in ("breathe", "rainbow-cycle"))

    def _apply(self, *_):
        eff = AURA_EFFECTS[self.effect.get_selected()][0]
        speed = SPEEDS[self.speed.get_selected()][0]
        c1, c2 = self._hex(self.colour_btn), self._hex(self.colour2_btn)
        self.state["aura"] = {"effect": eff, "colour": c1, "colour2": c2, "speed": speed}
        save_state(self.state)
        hw.set_aura(eff, c1, c2, speed, self.done("Lighting updated"))

    def refresh(self):
        self._silent = True
        lvl = hw.get_kbd_level()
        if 0 <= lvl < len(self.levels):
            self.levels[lvl].set_active(True)
        self._silent = False

    def _level_toggled(self, b, i):
        if b.get_active() and not self._silent:
            hw.set_kbd_level(i, self.done())


# ==========================================================================
# Graphics

GFX_INFO = {
    "Integrated": ("Integrated", "NVIDIA GPU powered off. Best battery life.", "battery-level-100-symbolic"),
    "Hybrid": ("Hybrid", "Intel GPU drives the display, NVIDIA available on demand.", "tuf-gpu-symbolic"),
    "AsusMuxDgpu": ("Dedicated (MUX)", "Display wired straight to the NVIDIA GPU. Requires a reboot.", "video-display-symbolic"),
    "Vfio": ("VFIO", "NVIDIA GPU detached for virtual machine passthrough.", "computer-symbolic"),
    "AsusEgpu": ("External GPU", "Use an ASUS XG Mobile external GPU.", "tuf-gpu-symbolic"),
}


class GraphicsPage(Page):
    title = "Graphics"
    icon = "tuf-gpu-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.group = Adw.PreferencesGroup(
            title="GPU Mode",
            description="Switching modes may require logging out or rebooting.")
        self.add(self.group)
        self.mode_rows = {}
        self.current = None
        self._silent = False

        g = Adw.PreferencesGroup(title="Status")
        self.status_row = Adw.ActionRow(title="NVIDIA GPU Power")
        self.status_lbl = Gtk.Label()
        self.status_lbl.add_css_class("dim-label")
        self.status_row.add_suffix(self.status_lbl)
        g.add(self.status_row)
        self.pending_row = Adw.ActionRow(title="Pending Action", visible=False)
        self.pending_row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
        g.add(self.pending_row)
        self.add(g)

        if not hw.GFX_AVAILABLE:
            self.group.set_description("supergfxctl is not installed.")

    def refresh(self):
        hw.get_gfx(self._got)

    def _got(self, info):
        if not info:
            return
        if not self.mode_rows:
            first = None
            for m in info["supported"]:
                title, desc, icon = GFX_INFO.get(m, (m, "", "tuf-gpu-symbolic"))
                row = Adw.ActionRow(title=title, subtitle=desc)
                row.add_prefix(Gtk.Image.new_from_icon_name(icon))
                chk = Gtk.CheckButton(valign=Gtk.Align.CENTER)
                if first:
                    chk.set_group(first)
                first = first or chk
                chk.connect("toggled", self._toggled, m)
                row.add_suffix(chk)
                row.set_activatable_widget(chk)
                self.group.add(row)
                self.mode_rows[m] = chk
        self._silent = True
        self.current = info["mode"]
        if info["mode"] in self.mode_rows:
            self.mode_rows[info["mode"]].set_active(True)
        self._silent = False
        self.status_lbl.set_label((info["status"] or "unknown").capitalize())
        pend = info.get("pending") or ""
        show = bool(pend) and not any(w in pend.lower() for w in ("none", "no action"))
        self.pending_row.set_visible(show)
        self.pending_row.set_subtitle(pend)

    def _toggled(self, chk, mode):
        if self._silent or not chk.get_active() or mode == self.current:
            return
        title = GFX_INFO.get(mode, (mode,))[0]
        d = Adw.AlertDialog(
            heading=f"Switch to {title} Mode?",
            body="Save your work first — you will likely need to log out or reboot "
                 "for the change to take effect.")
        d.add_response("cancel", "Cancel")
        d.add_response("switch", "Switch")
        d.set_response_appearance("switch", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("cancel")

        def resp(_d, r):
            if r == "switch":
                hw.set_gfx(mode, lambda ok, msg: (
                    self.win.toast(msg or f"Switched to {title}" if ok else f"Failed: {msg}"),
                    self.refresh()))
            else:
                self.refresh()

        d.connect("response", resp)
        d.present(self.win)
