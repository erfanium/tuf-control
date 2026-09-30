"""Interactive 8-point fan curve editor drawn with Cairo."""

import math

from gi.repository import Adw, GObject, Gdk, Gtk, Pango, PangoCairo

T_MIN, T_MAX = 20, 100
P_MIN, P_MAX = 0, 100
PAD_L, PAD_R, PAD_T, PAD_B = 44, 16, 16, 30
HIT_RADIUS = 14


def _rgba(c, alpha=None):
    return (c.red, c.green, c.blue, c.alpha if alpha is None else alpha)


class CurveEditor(Gtk.DrawingArea):
    __gtype_name__ = "TufCurveEditor"
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.points = [(40, 0), (45, 0), (50, 0), (55, 0), (60, 35), (65, 55), (70, 75), (80, 100)]
        self.ghost = None          # the other fan's curve, drawn faintly
        self.live_temp = None      # current temperature marker
        self.hover = None
        self.drag = None
        self._drag_origin = None

        self.set_content_height(300)
        self.set_hexpand(True)
        self.set_focusable(True)
        self.set_draw_func(self._draw)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Fan curve"])

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        style = Adw.StyleManager.get_default()
        style.connect("notify::dark", lambda *_: self.queue_draw())
        style.connect("notify::accent-color-rgba", lambda *_: self.queue_draw())

    # ------------------------------------------------------------------ API

    def set_points(self, points, emit=False):
        self.points = [(int(t), int(p)) for t, p in points]
        self.queue_draw()
        if emit:
            self.emit("changed")

    def set_ghost(self, points):
        self.ghost = points
        self.queue_draw()

    def set_live_temp(self, t):
        if t != self.live_temp:
            self.live_temp = t
            self.queue_draw()

    def duty_at(self, temp):
        pts = self.points
        if temp <= pts[0][0]:
            return pts[0][1]
        for (t0, p0), (t1, p1) in zip(pts, pts[1:]):
            if temp <= t1:
                return p0 + (p1 - p0) * (temp - t0) / max(1, t1 - t0)
        return pts[-1][1]

    # -------------------------------------------------------------- geometry

    def _plot(self):
        w, h = self.get_width(), self.get_height()
        return PAD_L, PAD_T, max(1, w - PAD_L - PAD_R), max(1, h - PAD_T - PAD_B)

    def _to_xy(self, t, p):
        x0, y0, pw, ph = self._plot()
        return (x0 + (t - T_MIN) / (T_MAX - T_MIN) * pw,
                y0 + ph - (p - P_MIN) / (P_MAX - P_MIN) * ph)

    def _from_xy(self, x, y):
        x0, y0, pw, ph = self._plot()
        return (T_MIN + (x - x0) / pw * (T_MAX - T_MIN),
                P_MIN + (y0 + ph - y) / ph * (P_MAX - P_MIN))

    def _hit(self, x, y):
        best, best_d = None, HIT_RADIUS
        for i, (t, p) in enumerate(self.points):
            px, py = self._to_xy(t, p)
            d = math.hypot(px - x, py - y)
            if d <= best_d:
                best, best_d = i, d
        return best

    def _move_point(self, i, t, p):
        pts = self.points
        lo_t = pts[i - 1][0] + 1 if i > 0 else T_MIN
        hi_t = pts[i + 1][0] - 1 if i < len(pts) - 1 else T_MAX
        lo_p = pts[i - 1][1] if i > 0 else P_MIN
        hi_p = pts[i + 1][1] if i < len(pts) - 1 else P_MAX
        t = int(round(min(max(t, lo_t), hi_t)))
        p = int(round(min(max(p, lo_p), hi_p)))
        if (t, p) != pts[i]:
            pts[i] = (t, p)
            self.queue_draw()
            self.emit("changed")

    # ---------------------------------------------------------------- events

    def _on_motion(self, _c, x, y):
        if self.drag is not None:
            return
        h = self._hit(x, y)
        if h != self.hover:
            self.hover = h
            self.set_cursor_from_name("grab" if h is not None else None)
            self.queue_draw()

    def _on_leave(self, _c):
        if self.drag is None and self.hover is not None:
            self.hover = None
            self.queue_draw()

    def _on_drag_begin(self, g, x, y):
        self.grab_focus()
        self.drag = self._hit(x, y)
        if self.drag is None:
            g.set_state(Gtk.EventSequenceState.DENIED)
            return
        self.hover = self.drag
        self._drag_origin = (x, y)
        self.set_cursor_from_name("grabbing")
        g.set_state(Gtk.EventSequenceState.CLAIMED)

    def _on_drag_update(self, _g, dx, dy):
        if self.drag is None:
            return
        x, y = self._drag_origin
        t, p = self._from_xy(x + dx, y + dy)
        self._move_point(self.drag, t, p)

    def _on_drag_end(self, _g, _dx, _dy):
        self.drag = None
        self.set_cursor_from_name("grab" if self.hover is not None else None)
        self.queue_draw()

    def _on_key(self, _c, keyval, _code, state):
        if keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab) and state & Gdk.ModifierType.CONTROL_MASK:
            return False
        sel = self.hover if self.hover is not None else 0
        step = 5 if state & Gdk.ModifierType.SHIFT_MASK else 1
        t, p = self.points[sel]
        if keyval in (Gdk.KEY_bracketright, Gdk.KEY_period):
            self.hover = min(sel + 1, len(self.points) - 1)
        elif keyval in (Gdk.KEY_bracketleft, Gdk.KEY_comma):
            self.hover = max(sel - 1, 0)
        elif keyval == Gdk.KEY_Up:
            self.hover = sel
            self._move_point(sel, t, p + step)
        elif keyval == Gdk.KEY_Down:
            self.hover = sel
            self._move_point(sel, t, p - step)
        elif keyval == Gdk.KEY_Right:
            self.hover = sel
            self._move_point(sel, t + step, p)
        elif keyval == Gdk.KEY_Left:
            self.hover = sel
            self._move_point(sel, t - step, p)
        else:
            return False
        self.queue_draw()
        return True

    # --------------------------------------------------------------- drawing

    def _text(self, cr, text, x, y, align=0.0, valign=0.5, font="Cantarell 9"):
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription.from_string(font))
        layout.set_text(text, -1)
        _, log = layout.get_pixel_extents()
        cr.move_to(x - log.width * align, y - log.height * valign)
        PangoCairo.show_layout(cr, layout)
        cr.new_path()
        return log.width, log.height

    def _path(self, cr, pts):
        cr.move_to(*self._to_xy(T_MIN, pts[0][1]))
        for t, p in pts:
            cr.line_to(*self._to_xy(t, p))
        cr.line_to(*self._to_xy(T_MAX, pts[-1][1]))

    def _draw(self, _area, cr, w, h):
        fg = self.get_color()
        accent = Adw.StyleManager.get_default().get_accent_color_rgba()
        dark = Adw.StyleManager.get_default().get_dark()
        x0, y0, pw, ph = self._plot()

        # grid
        cr.set_line_width(1)
        cr.set_source_rgba(*_rgba(fg, 0.08))
        for p in range(0, 101, 25):
            _, y = self._to_xy(T_MIN, p)
            cr.move_to(x0, round(y) + 0.5)
            cr.line_to(x0 + pw, round(y) + 0.5)
        for t in range(T_MIN, T_MAX + 1, 10):
            x, _ = self._to_xy(t, 0)
            cr.move_to(round(x) + 0.5, y0)
            cr.line_to(round(x) + 0.5, y0 + ph)
        cr.stroke()

        # axis labels
        cr.set_source_rgba(*_rgba(fg, 0.55))
        for p in range(0, 101, 25):
            _, y = self._to_xy(T_MIN, p)
            self._text(cr, f"{p}%", x0 - 8, y, align=1.0)
        for t in range(T_MIN, T_MAX + 1, 10):
            x, _ = self._to_xy(t, 0)
            self._text(cr, f"{t}°", x, y0 + ph + 14, align=0.5)

        # ghost curve (other fan)
        if self.ghost:
            cr.set_source_rgba(*_rgba(fg, 0.25))
            cr.set_line_width(1.5)
            cr.set_dash([4, 4])
            self._path(cr, self.ghost)
            cr.stroke()
            cr.set_dash([])

        # area + line
        self._path(cr, self.points)
        cr.line_to(x0 + pw, y0 + ph)
        cr.line_to(x0, y0 + ph)
        cr.close_path()
        cr.set_source_rgba(*_rgba(accent, 0.22 if dark else 0.15))
        cr.fill()

        self._path(cr, self.points)
        cr.set_source_rgba(*_rgba(accent))
        cr.set_line_width(2.5)
        cr.set_line_join(1)  # round
        cr.stroke()

        # live temperature marker
        if self.live_temp is not None and T_MIN <= self.live_temp <= T_MAX:
            duty = self.duty_at(self.live_temp)
            lx, ly = self._to_xy(self.live_temp, duty)
            cr.set_source_rgba(0.90, 0.38, 0.0, 0.9)
            cr.set_line_width(1.5)
            cr.set_dash([3, 3])
            cr.move_to(round(lx) + 0.5, y0)
            cr.line_to(round(lx) + 0.5, y0 + ph)
            cr.stroke()
            cr.set_dash([])
            cr.arc(lx, ly, 4, 0, 2 * math.pi)
            cr.fill()
            self._text(cr, f"{self.live_temp:.0f}°C", lx + 6, y0 + 8, font="Cantarell Bold 9")

        # handles
        cr.new_path()
        for i, (t, p) in enumerate(self.points):
            x, y = self._to_xy(t, p)
            active = i == self.hover or i == self.drag
            r = 8 if active else 6
            cr.arc(x, y, r, 0, 2 * math.pi)
            cr.set_source_rgba(*(_rgba(accent) if active else ((0.19, 0.19, 0.21, 1) if dark else (1, 1, 1, 1))))
            cr.fill_preserve()
            cr.set_source_rgba(*_rgba(accent))
            cr.set_line_width(2.5)
            cr.stroke()

        # tooltip bubble for the active point
        i = self.drag if self.drag is not None else self.hover
        if i is not None:
            t, p = self.points[i]
            x, y = self._to_xy(t, p)
            label = f"{t}°C  ·  {p}%"
            layout = PangoCairo.create_layout(cr)
            layout.set_font_description(Pango.FontDescription.from_string("Cantarell Bold 9"))
            layout.set_text(label, -1)
            _, log = layout.get_pixel_extents()
            bw, bh = log.width + 16, log.height + 8
            bx = min(max(x - bw / 2, x0), x0 + pw - bw)
            by = y - bh - 14 if y - bh - 14 > 0 else y + 14
            _rounded(cr, bx, by, bw, bh, bh / 2)
            cr.set_source_rgba(*_rgba(accent))
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 1)
            cr.move_to(bx + 8, by + 4)
            PangoCairo.show_layout(cr, layout)


def _rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class Sparkline(Gtk.DrawingArea):
    """Small live history chart for the overview cards."""

    __gtype_name__ = "TufSparkline"

    def __init__(self, vmin=0, vmax=100, length=60):
        super().__init__()
        self.values = []
        self.vmin, self.vmax, self.length = vmin, vmax, length
        self.set_content_height(36)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def push(self, v):
        if v is None:
            return
        self.values.append(v)
        del self.values[:-self.length]
        self.queue_draw()

    def _draw(self, _a, cr, w, h):
        if len(self.values) < 2:
            return
        accent = Adw.StyleManager.get_default().get_accent_color_rgba()
        vmax = max(self.vmax, max(self.values))
        vmin = min(self.vmin, min(self.values))
        span = (vmax - vmin) or 1
        # stretch across the card until the history buffer is full
        step = w / (max(len(self.values), 2) - 1)
        off = 0
        pts = [(off + i * step, h - 2 - (v - vmin) / span * (h - 4)) for i, v in enumerate(self.values)]
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.set_source_rgba(*_rgba(accent))
        cr.set_line_width(2)
        cr.set_line_join(1)
        cr.stroke_preserve()
        cr.line_to(pts[-1][0], h)
        cr.line_to(pts[0][0], h)
        cr.close_path()
        cr.set_source_rgba(*_rgba(accent, 0.15))
        cr.fill()
