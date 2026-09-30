import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import backend as hw  # noqa: E402
from .pages import (BatteryPage, FansPage, GraphicsPage, LightingPage,  # noqa: E402
                    OverviewPage, PerformancePage)

APP_ID = "io.github.erfanium.TufControl"
VERSION = "1.0"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

CSS = """
.stat-card { padding: 14px 16px 10px 16px; }
.stat-icon { color: var(--accent-color); }
.stat-value {
  font-size: 26pt; font-weight: 800;
  font-feature-settings: "tnum";
  letter-spacing: -0.5px;
}
.stat-value.large { font-size: 34pt; }
.stat-unit { font-weight: 600; margin-top: 12px; }
.curve-card { padding: 16px 12px 14px 8px; }
.small-pill { padding: 4px 14px; min-height: 0; font-size: 0.9em; }

.profile-card {
  border-radius: 12px;
  padding: 0 8px;
  background: var(--card-bg-color);
  box-shadow: 0 0 0 1px var(--card-shade-color), 0 1px 3px 1px rgb(0 0 6 / 3%);
}
.profile-card:hover { background: color-mix(in srgb, var(--card-bg-color), currentColor 4%); }
.profile-card:checked {
  background: color-mix(in srgb, var(--accent-bg-color) 16%, var(--card-bg-color));
  box-shadow: 0 0 0 2px var(--accent-bg-color);
  color: var(--accent-color);
}
.profile-card:checked label.dim-label { color: inherit; opacity: 0.75; }

.badge {
  font-size: 0.8em; font-weight: 700;
  padding: 3px 10px; border-radius: 99px;
}
.badge.accent { background: var(--accent-bg-color); color: var(--accent-fg-color); }
.badge.dim { background: alpha(currentColor, 0.1); }

levelbar.battery-bar block.filled { background: var(--success-bg-color); }

button.swatch {
  min-width: 30px; min-height: 30px; padding: 0;
  border-radius: 99px;
  box-shadow: inset 0 0 0 1px rgb(0 0 0 / 15%);
}
button.swatch:hover { box-shadow: inset 0 0 0 1px rgb(0 0 0 / 15%), 0 0 0 2px var(--accent-bg-color); }

.kbd-level-0 { opacity: 0.25; }
.kbd-level-1 { opacity: 0.5; }
.kbd-level-2 { opacity: 0.75; }
"""


class LegacySidebar(Gtk.ScrolledWindow):
    """Fallback for libadwaita < 1.9, which has no Adw.Sidebar."""

    def __init__(self, pages, sections, on_activated):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("navigation-sidebar")
        first_of_section = {sec[0] for sec in sections[1:]}
        for key in (k for sec in sections for k in sec):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6)
            box.append(Gtk.Image.new_from_icon_name(pages[key].icon))
            box.append(Gtk.Label(label=pages[key].title, xalign=0))
            row.set_child(box)
            self.listbox.append(row)
        self.listbox.set_header_func(
            lambda row, before: row.set_header(Gtk.Separator() if before and list(
                k for sec in sections for k in sec)[row.get_index()] in first_of_section else None))
        self.listbox.connect("row-activated", lambda _lb, row: on_activated(self, row.get_index()))
        self.set_child(self.listbox)

    def set_selected(self, index):
        self.listbox.select_row(self.listbox.get_row_at_index(index))


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="TUF Control")
        self.set_default_size(1040, 760)
        self.set_size_request(360, 420)
        self.sensors = hw.Sensors()
        self._clamp_seen = 0

        self.pages = {
            "overview": OverviewPage(self),
            "fans": FansPage(self),
            "performance": PerformancePage(self),
            "battery": BatteryPage(self),
            "lighting": LightingPage(self),
            "graphics": GraphicsPage(self),
        }

        # ---- content
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        for key, page in self.pages.items():
            self.stack.add_named(page, key)

        self.content_header = Adw.HeaderBar()
        self.banner = Adw.Banner(
            title="CPU is clamped at 400 MHz — the power limits were dropped",
            button_label="Fix Now")
        self.banner.connect("button-clicked", lambda *_: self._fix_clamp())

        content_view = Adw.ToolbarView()
        content_view.add_top_bar(self.content_header)
        content_view.add_top_bar(self.banner)
        content_view.set_content(self.stack)
        self.content_page = Adw.NavigationPage(title="Overview", child=content_view)

        # ---- sidebar (Adw.Sidebar, as used by GNOME Settings)
        sections = (("overview",), ("fans", "performance", "graphics"), ("battery", "lighting"))
        self._sidebar_keys = [k for sec in sections for k in sec]
        if hasattr(Adw, "Sidebar"):
            self.sidebar = Adw.Sidebar()
            for section_keys in sections:
                section = Adw.SidebarSection()
                for key in section_keys:
                    page = self.pages[key]
                    section.append(Adw.SidebarItem(title=page.title, icon_name=page.icon))
                self.sidebar.append(section)
            self.sidebar.connect("activated", self._sidebar_activated)
        else:
            self.sidebar = LegacySidebar(self.pages, sections, self._sidebar_activated)

        menu = Gio.Menu()
        menu.append("Refresh", "win.refresh")
        menu.append("About TUF Control", "app.about")
        side_header = Adw.HeaderBar()
        side_header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                            primary=True, tooltip_text="Main Menu"))

        side_view = Adw.ToolbarView()
        side_view.add_top_bar(side_header)
        side_view.set_content(self.sidebar)
        sidebar_page = Adw.NavigationPage(title="TUF Control", child=side_view)

        self.split = Adw.NavigationSplitView(sidebar=sidebar_page, content=self.content_page,
                                             min_sidebar_width=220, max_sidebar_width=280)

        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)

        # ---- actions
        act = Gio.SimpleAction.new("refresh", None)
        act.connect("activate", lambda *_: self.refresh_all())
        self.add_action(act)
        app.set_accels_for_action("win.refresh", ["<Control>r", "F5"])
        for i, key in enumerate(self._sidebar_keys):
            a = Gio.SimpleAction.new(f"page-{key}", None)
            a.connect("activate", lambda *_a, k=key: self.show_page(k))
            self.add_action(a)
            app.set_accels_for_action(f"win.page-{key}", [f"<Alt>{i + 1}"])

        self.show_page("overview")
        self.refresh_all()
        self._tick()
        self._timer = GLib.timeout_add(1000, self._tick)
        self.connect("close-request", self._on_close)

    # ----------------------------------------------------------------------

    def _on_close(self, *_):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        return False

    def _sidebar_activated(self, _sidebar, index):
        self.show_page(self._sidebar_keys[index])

    def show_page(self, key):
        page = self.pages[key]
        self.stack.set_visible_child_name(key)
        self.content_page.set_title(page.title)
        self.sidebar.set_selected(self._sidebar_keys.index(key))
        self.split.set_show_content(True)
        page.refresh()

    def refresh_all(self):
        for p in self.pages.values():
            p.refresh()

    def after_profile_change(self, ok, msg=""):
        if not ok:
            self.toast(f"Failed: {msg}")
        # the profile switch changes PPT defaults and the active fan curve
        GLib.timeout_add(600, lambda: self.refresh_all() and False)

    def toast(self, msg):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(msg), timeout=3))

    def _fix_clamp(self):
        self.banner.set_revealed(False)
        hw.fix_ppt(lambda ok, msg: self.toast(msg if ok else f"Failed: {msg}"))

    def _tick(self):
        s = self.sensors.sample()
        visible = self.stack.get_visible_child_name()
        # the overview keeps its history even when hidden
        self.pages["overview"].update(s)
        if visible != "overview":
            self.pages[visible].update(s)

        # 400 MHz clamp detector : busy CPU, low clock
        if s["cpu_usage"] and s["cpu_usage"] > 60 and s["freq_max"] and s["freq_max"] < 1000:
            self._clamp_seen += 1
        else:
            self._clamp_seen = 0
        if self._clamp_seen >= 3:
            self.banner.set_revealed(True)
        return True


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name("TUF Control")
        a = Gio.SimpleAction.new("about", None)
        a.connect("activate", self._about)
        self.add_action(a)
        a = Gio.SimpleAction.new("quit", None)
        a.connect("activate", lambda *_: self.quit())
        self.add_action(a)
        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("window.close", ["<Control>w"])

    def do_startup(self):
        Adw.Application.do_startup(self)
        display = Gdk.Display.get_default()
        Gtk.IconTheme.get_for_display(display).add_search_path(os.path.join(DATA_DIR, "icons"))
        prov = Gtk.CssProvider()
        prov.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            display, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        win = self.get_active_window() or MainWindow(self)
        win.present()

    def _about(self, *_):
        info = hw.system_info()
        d = Adw.AboutDialog(
            application_name="TUF Control",
            application_icon=APP_ID,
            developer_name="erfanium",
            version=VERSION,
            comments=f"A GNOME-native control center for the {info['product']}.\n"
                     "Built on asusctl, supergfxctl and the asus-armoury firmware attributes.",
            license_type=Gtk.License.GPL_3_0,
        )
        d.present(self.get_active_window())


def main():
    return Application().run(sys.argv)
