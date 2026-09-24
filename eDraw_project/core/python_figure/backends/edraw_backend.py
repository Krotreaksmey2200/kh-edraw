"""eDraw / QPainter backend for Python Figure.

Author-facing surface::

    PARAMS = {"a": {"min": -3, "max": 3, "step": 0.1, "value": 1}}

    def eDraw(ed, p):
        ed.axes(-5, 5, -5, 5)
        ed.plot(lambda x: p["a"] * x**2, xmin=-3, xmax=3)
        ed.point(p.get("t", 0), 0, label="A")

``ed`` is injected by eDraw when ``eDraw(ed, p)`` runs.  It is not a standalone
Python package and should not be imported.  User code never touches QPainter /
QPointF / QColor / etc.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

from core.python_figure.ast_guard import SandboxError, validate_source
from core.python_figure.protocol import Backend, BackendProgram, RenderResult

_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "reversed": reversed,
    "sorted": sorted,
    "any": any,
    "all": all,
    "map": map,
    "filter": filter,
    "int": int,
    "float": float,
    "round": round,
}



def _make_sandbox_globals(allow_modules: tuple[str, ...] = ()) -> dict:
    g = {
        "__builtins__": _SAFE_BUILTINS,
        "math": math,
    }
    _ = allow_modules
    return g


@dataclass
class _Style:
    color: str = "#1f77b4"
    width: float = 2.0
    line_style: str = "solid"
    alpha: float | int | None = 1.0
    fill: str = "#60a5fa"
    fill_alpha: float = 0.25
    font_size: int = 12


def _to_qcolor(value, alpha=None):
    if isinstance(value, QColor):
        c = value
    elif isinstance(value, str):
        c = QColor(value)
        if not c.isValid():
            c = QColor("#000")
    elif isinstance(value, (list, tuple)):
        vals = list(value)
        if len(vals) == 3:
            rgb = vals
            a_val = alpha if alpha is not None else 1.0
            c = QColor(int(rgb[0] * 255.0), int(rgb[1] * 255.0), int(rgb[2] * 255.0))
        elif len(vals) == 4:
            c = QColor(int(vals[0] * 255.0), int(vals[1] * 255.0), int(vals[2] * 255.0), int(vals[3] * 255.0))
        else:
            c = QColor("#000")
    else:
        c = QColor("#000")
    if alpha is not None and isinstance(alpha, (int, float)):
        a = max(0.0, min(1.0, float(alpha)))
        c.setAlphaF(a)
    return c


class EDrawContext:
    """The ``ed`` object passed to the user's ``eDraw(ed, p)`` function.

    Coordinates passed to drawing methods are in *world* space.  Use
    ``axes()`` to set bounds and draw axes/grid, or ``view()``/``axis()`` to set
    only the visible coordinate bounds.  If the user forgets, a default
    (-10, 10, -10, 10) window is applied and a warning is recorded.
    """

    def __init__(self, painter: QPainter, size_px: tuple[int, int], render_scale: float = 1.0):
        self.painter = painter
        self.size_px = size_px
        self.render_scale = render_scale
        self._xmin: float = -10.0
        self._xmax: float = 10.0
        self._ymin: float = -10.0
        self._ymax: float = 10.0
        self._draw_grid: bool = True
        self._draw_axis: bool = True
        self._draw_ticks: bool = True
        self._draw_labels: bool = True
        self._draw_border: bool = True
        self._draw_arrows: bool = True
        self._grid_step: float | None = None
        self._style_stack: list[_Style] = [_Style()]
        self._legend_items: list[tuple[str, str]] = []
        self._warned_no_axes = False

    @property
    def _style(self) -> _Style:
        return self._style_stack[-1]

    def _ensure_axes(self):
        if not hasattr(self, "_axes_set"):
            self._warned_no_axes = True
            self._xmin, self._xmax, self._ymin, self._ymax = -10, 10, -10, 10
            self._axes_set = True

    def _to_device(self, x: float, y: float) -> tuple[float, float]:
        """World -> device (pixel) coordinates.  Y axis inverted (up is up)."""
        sx = (self.size_px[0] - 1) / max(abs(self._xmax - self._xmin), 1e-12)
        sy = (self.size_px[1] - 1) / max(abs(self._ymax - self._ymin), 1e-12)
        dx = (x - self._xmin) * sx
        dy = (self._ymax - y) * sy
        return dx, dy

    def _device_scale_x(self) -> float:
        return (self.size_px[0] - 1) / max(abs(self._xmax - self._xmin), 1e-12)

    def _device_scale_y(self) -> float:
        return (self.size_px[1] - 1) / max(abs(self._ymax - self._ymin), 1e-12)

    def _make_pen(self, color=None, width=None, style=None, alpha=None) -> QPen:
        s = self._style
        c = _to_qcolor(color if color is not None else s.color, alpha if alpha is not None else s.alpha)
        w = width if width is not None else s.width
        pen = QPen(c)
        pen.setWidthF(w)
        if (style if style is not None else s.line_style) == "dashed":
            pen.setStyle(Qt.PenStyle.DashLine)
        elif (style if style is not None else s.line_style) == "dotted":
            pen.setStyle(Qt.PenStyle.DotLine)
        else:
            pen.setStyle(Qt.PenStyle.SolidLine)
        return pen

    def view(self, xmin: float, xmax: float, ymin: float, ymax: float, **kwargs):
        """Set visible world-coordinate bounds without drawing axes/grid."""
        if xmax <= xmin or ymax <= ymin:
            raise ValueError("view(): xmax phải > xmin và ymax phải > ymin.")
        self._xmin = xmin
        self._xmax = xmax
        self._ymin = ymin
        self._ymax = ymax
        if kwargs.get("aspect") == "equal":
            self._apply_equal_aspect()

    def _apply_equal_aspect(self):
        """Expand current bounds so one world unit has the same pixel scale."""
        x_span = abs(self._xmax - self._xmin)
        y_span = abs(self._ymax - self._ymin)
        if x_span < 1e-12 or y_span < 1e-12:
            return
        target_ratio = self.size_px[0] / max(self.size_px[1], 1)
        current_ratio = x_span / y_span
        if abs(current_ratio - target_ratio) < 1e-12:
            return
        cx = (self._xmin + self._xmax) / 2.0
        cy = (self._ymin + self._ymax) / 2.0
        if current_ratio < target_ratio:
            new_half = (x_span / target_ratio) / 2.0
            self._ymin = cy - new_half
            self._ymax = cy + new_half
        else:
            new_half = (y_span * target_ratio) / 2.0
            self._xmin = cx - new_half
            self._xmax = cx + new_half

    def axis(self, *args, **kwargs):
        """Matplotlib-like viewport/control command.

        Examples::

            ed.axis([-5, 5, -5, 5])
            ed.axis("off")
            ed.axis("on")
            ed.axis("off", "equal")
            ed.axis(grid=False, labels=False)
        """
        defaults = {
            "grid": True,
            "axes": True,
            "ticks": True,
            "labels": True,
            "border": True,
            "arrows": True,
            "grid_step": None,
        }
        commands = []
        numeric_values = []
        for arg in args:
            if isinstance(arg, str):
                commands.append(arg)
            elif isinstance(arg, (list, tuple)):
                numeric_values = list(arg)
            elif isinstance(arg, (int, float)):
                numeric_values.append(arg)

        for cmd in commands:
            if cmd == "off":
                defaults["grid"] = False
                defaults["axes"] = False
                defaults["ticks"] = False
                defaults["labels"] = False
            elif cmd == "on":
                defaults["grid"] = True
                defaults["axes"] = True
                defaults["ticks"] = True
                defaults["labels"] = True
            elif cmd == "equal":
                pass
            else:
                raise ValueError("axis(): chỉ hỗ trợ 'on', 'off', 'equal' hoặc 4 giới hạn.")

        if "aspect" in kwargs and kwargs["aspect"] == "equal":
            pass

        for key, value in kwargs.items():
            if key in defaults:
                defaults[key] = value

        if numeric_values:
            if len(numeric_values) == 4:
                self._xmin, self._xmax, self._ymin, self._ymax = (
                    numeric_values[0], numeric_values[1], numeric_values[2], numeric_values[3]
                )
            else:
                raise ValueError("axis(): cần 4 giá trị xmin, xmax, ymin, ymax.")
            self._axes_set = True

        if "grid_step" in kwargs:
            self._grid_step = kwargs["grid_step"]

        self._draw_grid = defaults["grid"]
        self._draw_axis = defaults["axes"]
        self._draw_ticks = defaults["ticks"]
        self._draw_labels = defaults["labels"]
        self._draw_border = defaults["border"]
        self._draw_arrows = defaults["arrows"]

    def xlim(self, xmin: float, xmax: float):
        """Set visible x range while preserving the current y range."""
        self._xmin = xmin
        self._xmax = xmax
        self._axes_set = True

    def ylim(self, ymin: float, ymax: float):
        """Set visible y range while preserving the current x range."""
        self._ymin = ymin
        self._ymax = ymax
        self._axes_set = True

    def set_xlim(self, xmin: float, xmax: float):
        self._xmin = xmin
        self._xmax = xmax
        self._axes_set = True

    def set_ylim(self, ymin: float, ymax: float):
        self._ymin = ymin
        self._ymax = ymax
        self._axes_set = True

    def grid(self, visible: bool = True, step: float | None = None):
        """Set grid visibility for the next ``axes()`` call."""
        self._draw_grid = visible
        if step is not None:
            self._grid_step = step

    def show_grid(self):
        self._draw_grid = True

    def hide_grid(self):
        self._draw_grid = False

    def show_axis(self):
        self._draw_axis = True

    def hide_axis(self):
        self._draw_axis = False

    def show_ticks(self):
        self._draw_ticks = True

    def hide_ticks(self):
        self._draw_ticks = False

    def show_labels(self):
        self._draw_labels = True

    def hide_labels(self):
        self._draw_labels = False

    def axes(
        self,
        xmin: float,
        xmax: float,
        ymin: float,
        ymax: float,
        grid: bool = True,
        grid_step: float = 1.0,
        axis: bool = True,
        axis_color: str = "#444",
        grid_color: str = "#e2e8f0",
        show_ticks: bool = True,
        ticks: bool = True,
        tick_labels: bool = True,
        labels: bool = True,
        xlabel: str | None = None,
        ylabel: str | None = None,
        border: bool = True,
        arrows: bool = True,
        tick_color: str = "#666",
        **kwargs,
    ):
        """Set the world->device transform and draw axes + optional grid."""
        defaults = {
            "grid": grid,
            "axes": axis,
            "ticks": show_ticks,
            "labels": labels,
            "border": border,
            "arrows": arrows,
            "grid_step": grid_step,
        }
        for key, value in kwargs.items():
            if key in defaults:
                defaults[key] = value

        draw_grid = defaults["grid"]
        draw_axis = defaults["axes"]
        draw_ticks = defaults["ticks"]
        draw_labels = defaults["labels"]
        draw_border = defaults["border"]
        draw_arrows = defaults["arrows"]

        step_setting = defaults["grid_step"]
        step = step_setting if step_setting is not None else _auto_grid_step(xmin, xmax, ymin, ymax)

        self._xmin = xmin
        self._xmax = xmax
        self._ymin = ymin
        self._ymax = ymax
        self._axes_set = True

        if draw_axis and draw_arrows:
            pen = self._make_pen(color=axis_color, width=1.5)
            self.painter.setPen(pen)
            self._draw_axis_arrow(tip=(xmax, 0), angle=0, color=axis_color, size=8.0)
            self._draw_axis_arrow(tip=(0, ymax), angle=90, color=axis_color, size=8.0)

        if draw_grid:
            pen = self._make_pen(color=grid_color, width=0.5, alpha=0.5)
            self.painter.setPen(pen)
            x = math.ceil(xmin / step) * step
            while x <= xmax:
                dx, _ = self._to_device(x, 0)
                self.painter.drawLine(int(dx), 0, int(dx), self.size_px[1] - 1)
                x += step
            y = math.ceil(ymin / step) * step
            while y <= ymax:
                _, dy = self._to_device(0, y)
                self.painter.drawLine(0, int(dy), self.size_px[0] - 1, int(dy))
                y += step

        if draw_ticks:
            self._draw_ticks(color=tick_color, grid_step=step, tick_labels=draw_labels)

        if draw_labels and (xlabel or ylabel):
            self._draw_axis_labels(xlabel=xlabel or "", ylabel=ylabel or "", color="#222")

        if draw_border:
            pen = self._make_pen(color="#000", width=1.0)
            self.painter.setPen(pen)
            self.painter.drawRect(0, 0, self.size_px[0] - 1, self.size_px[1] - 1)

    def _draw_axis_arrow(self, tip, angle, color, size=8.0):
        ux, uy = self._to_device(*tip)
        angle_rad = math.radians(angle)
        nx = -math.sin(angle_rad)
        ny = -math.cos(angle_rad)
        base_x = ux - nx * 0.022 * size
        base_y = uy - ny * 0.022 * size
        half = 0.42 * size
        head = QPolygonF([
            QPointF(ux, uy),
            QPointF(base_x + nx * half, base_y + ny * half),
            QPointF(base_x - nx * half, base_y - ny * half),
        ])
        pen = self._make_pen(color=color, width=1.5)
        self.painter.setPen(pen)
        self.painter.setBrush(QBrush(_to_qcolor(color)))
        self.painter.drawPolygon(head)

    def _draw_axis_labels(self, xlabel: str, ylabel: str, color: str = "#222"):
        font = QFont("Arial", 10)
        self.painter.setFont(font)
        fm = QFontMetricsF(font)
        p = self.painter
        if xlabel:
            dx, _ = self._to_device((self._xmin + self._xmax) / 2.0, self._ymin)
            p.setPen(_to_qcolor(color))
            p.drawText(QPointF(dx - fm.horizontalAdvance(xlabel) / 2, self.size_px[1] - 1 + 14), xlabel)
        if ylabel:
            _, dy = self._to_device(self._xmin, (self._ymin + self._ymax) / 2.0)
            p.setPen(_to_qcolor(color))
            p.drawText(QPointF(0, dy - 8), ylabel)

    def _draw_ticks(self, color: str = "#666", grid_step: float | None = None, tick_labels: bool = True):
        ui = self._render_scale
        font = QFont("Arial", max(1, int(round(8 * ui))))
        self._painter.setFont(font)
        fm = QFontMetricsF(font)
        pen = self._make_pen(color=color, width=1.0)
        self._painter.setPen(pen)
        if grid_step:
            step = float(grid_step)
        else:
            step = _auto_grid_step(self._xmin, self._xmax, self._ymin, self._ymax)
        y_axis = 0.0 if (self._ymin <= 0 <= self._ymax) else self._ymin
        x = math.ceil(self._xmin / step) * step
        while x <= self._xmax + 1e-09:
            if abs(x) > 1e-09:
                p = self._to_device(x, y_axis)
                self._painter.drawLine(QPointF(p.x(), p.y() - 3 * ui), QPointF(p.x(), p.y() + 3 * ui))
                if tick_labels:
                    label = _format_tick(x)
                    w = fm.horizontalAdvance(label)
                    self._painter.drawText(QPointF(p.x() - w / 2, p.y() + 14 * ui), label)
            x += step
        x_axis = 0.0 if (self._xmin <= 0 <= self._xmax) else self._xmin
        y = math.ceil(self._ymin / step) * step
        while y <= self._ymax + 1e-09:
            if abs(y) > 1e-09:
                p = self._to_device(x_axis, y)
                self._painter.drawLine(QPointF(p.x() - 3 * ui, p.y()), QPointF(p.x() + 3 * ui, p.y()))
                if tick_labels:
                    label = _format_tick(y)
                    w = fm.horizontalAdvance(label)
                    self._painter.drawText(QPointF(p.x() - w - 5 * ui, p.y() + 4 * ui), label)
            y += step

    def plot(
        self,
        fn: Callable,
        xmin: float | None = None,
        xmax: float | None = None,
        n: int = 20000,
        color: str | None = None,
        width: float | None = None,
        style: str | None = None,
        alpha: float | None = None,
        label: str | None = None,
        label_at_end: bool = False,
    ):
        """Plot y = fn(x) as a polyline."""
        self._ensure_axes()
        a = xmin if xmin is not None else self._xmin
        b = xmax if xmax is not None else self._xmax
        pen = self._make_pen(color=color, width=width, style=style, alpha=alpha)
        self.painter.setPen(pen)
        path = QPainterPath()
        first = True
        for i in range(n + 1):
            x = a + (b - a) * i / n
            y = fn(x)
            p = QPointF(*self._to_device(x, y))
            if first:
                path.moveTo(p)
                first = False
            else:
                path.lineTo(p)
        self.painter.drawPath(path)
        if label:
            self._legend_items.append((label, color or self._style.color))
        if label_at_end:
            y_end = fn(b)
            p_end = QPointF(*self._to_device(b, y_end))
            self.painter.drawText(p_end, f"  {label}" if label else "")

    def curve(self, fn: Callable, **kwargs):
        self.plot(fn, **kwargs)

    def fill_between(
        self,
        fn1: Callable,
        fn2: Callable,
        xmin: float | None = None,
        xmax: float | None = None,
        n: int = 20000,
        fill: str | None = None,
        alpha: float | None = None,
        stroke: str | None = None,
        width: float | None = None,
        style: str | None = None,
        label: str | None = None,
    ):
        """Fill the region between two curves y=fn1(x) and y=fn2(x)."""
        self._ensure_axes()
        a = float(self._xmin if xmin is None else xmin)
        b = float(self._xmax if xmax is None else xmax)
        if b <= a:
            return None
        n = min(2000, max(10, int(n)))

        def y2(x: float) -> float:
            if callable(fn2):
                return float(fn2(x))
            return float(fn2)

        top = []
        bottom = []
        for i in range(n + 1):
            x = a + (b - a) * i / n
            try:
                y_top = float(fn1(x))
                y_bottom = float(y2(x))
            except Exception:
                continue
            top.append(self._to_device(x, y_top))
            bottom.append(self._to_device(x, y_bottom))

        if len(top) < 2 or len(bottom) < 2:
            return None
        poly = QPolygonF(top + list(reversed(bottom)))
        self._painter.save()
        if stroke is not None:
            self._painter.setPen(self._make_pen(stroke, width, style))
        else:
            self._painter.setPen(Qt.PenStyle.NoPen)
        fill_color = fill if fill is not None else self._style.fill
        fill_alpha = self._style.fill_alpha if alpha is None else alpha
        self._painter.setBrush(QBrush(_to_qcolor(fill_color, fill_alpha)))
        self._painter.drawPolygon(poly)
        self._painter.restore()
        if label:
            self._legend_items.append((str(label), _to_qcolor(fill_color, fill_alpha)))

    def area(self, fn: Callable, baseline: float = 0, **kwargs):
        self.fill_between(lambda x, _b=baseline: max(fn(x), _b), lambda x, _b=baseline: min(fn(x), _b), **kwargs)

    def fill_under(self, fn: Callable, baseline: float = 0, **kwargs):
        self.fill_between(fn, lambda x, _b=baseline: _b, **kwargs)

    def fill(
        self,
        xs: list | None = None,
        ys: list | None = None,
        fill: str | None = None,
        alpha: float | None = None,
        stroke: str | None = None,
        width: float | None = None,
        label: str | None = None,
        **kwargs,
    ):
        """Matplotlib-like polygon fill from xs/ys arrays or [(x, y), ...]."""
        points = kwargs.get("points") or kwargs.get("polygon")
        if points is None and xs is not None and ys is not None:
            points = list(zip(xs, ys))
        if not points:
            return
        poly = QPolygonF([QPointF(*self._to_device(pt[0], pt[1])) for pt in points])
        fill_color = _to_qcolor(fill or self._style.fill, alpha if alpha is not None else self._style.fill_alpha)
        self.painter.setPen(Qt.PenStyle.NoPen)
        self.painter.setBrush(QBrush(fill_color))
        self.painter.drawPolygon(poly)
        if stroke:
            pen = self._make_pen(color=stroke, width=width)
            self.painter.setPen(pen)
            self.painter.setBrush(Qt.BrushStyle.NoBrush)
            self.painter.drawPolygon(poly)
        if label:
            self._legend_items.append((label, fill or self._style.fill))

    def parametric(
        self,
        fn: Callable,
        tmin: float = 0,
        tmax: float = 2 * math.pi,
        n: int = 20000,
        color: str | None = None,
        width: float | None = None,
        style: str | None = None,
        alpha: float | None = None,
        label: str | None = None,
    ):
        self._ensure_axes()
        pen = self._make_pen(color=color, width=width, style=style, alpha=alpha)
        self.painter.setPen(pen)
        path = QPainterPath()
        first = True
        for i in range(n + 1):
            t_ = tmin + (tmax - tmin) * i / n
            xy = fn(t_)
            x, y = xy[0], xy[1]
            p = QPointF(*self._to_device(x, y))
            if first:
                path.moveTo(p)
                first = False
            else:
                path.lineTo(p)
        self.painter.drawPath(path)
        if label:
            self._legend_items.append((label, color or self._style.color))

    def point(
        self,
        x: float,
        y: float,
        radius: float = 1.0,
        color: str | None = None,
        alpha: float | None = None,
        label: str | None = None,
        label_offset: tuple[float, float] = (0, 0),
        label_color: str | None = None,
    ):
        p = QPointF(*self._to_device(x, y))
        pen = self._make_pen(color=color, alpha=alpha)
        self.painter.setPen(pen)
        scaled_radius = radius * self._device_scale_x() * 0.015
        self.painter.setBrush(QBrush(pen.color()))
        self.painter.drawEllipse(p, scaled_radius, scaled_radius)
        if label:
            tx = p.x() + label_offset[0] * self._device_scale_x()
            ty = p.y() + label_offset[1] * self._device_scale_y()
            self.painter.setPen(_to_qcolor(label_color or "#222"))
            self.painter.drawText(QPointF(tx, ty), f"  {label}")

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str | None = None,
        width: float | None = None,
        style: str | None = None,
        alpha: float | None = None,
    ):
        pen = self._make_pen(color=color, width=width, style=style, alpha=alpha)
        self.painter.setPen(pen)
        p1 = QPointF(*self._to_device(x1, y1))
        p2 = QPointF(*self._to_device(x2, y2))
        self.painter.drawLine(p1, p2)

    def segment(self, p1: tuple, p2: tuple, **kwargs):
        self.line(p1[0], p1[1], p2[0], p2[1], **kwargs)

    def hline(
        self,
        y: float,
        xmin: float | None = None,
        xmax: float | None = None,
        color: str | None = None,
        width: float | None = None,
        style: str | None = None,
        alpha: float | None = None,
    ):
        a = xmin if xmin is not None else self._xmin
        b = xmax if xmax is not None else self._xmax
        self.line(a, y, b, y, color=color, width=width, style=style, alpha=alpha)

    def vline(
        self,
        x: float,
        ymin: float | None = None,
        ymax: float | None = None,
        color: str | None = None,
        width: float | None = None,
        style: str | None = None,
        alpha: float | None = None,
    ):
        a = ymin if ymin is not None else self._ymin
        b = ymax if ymax is not None else self._ymax
        self.line(x, a, x, b, color=color, width=width, style=style, alpha=alpha)

    def scatter(
        self,
        points: list | None = None,
        xs: list | None = None,
        ys: list | None = None,
        radius: float = 1.0,
        color: str | None = None,
        alpha: float | None = None,
        labels: list | None = None,
        label_color: str | None = None,
        label: str | None = None,
        legend_label: str | None = None,
    ):
        """Draw multiple points.  Accepts ``points=[(x,y), ...]`` or xs/ys."""
        if points is None and xs is not None and ys is not None:
            points = list(zip(xs, ys))
        if not points:
            return
        for i, pt in enumerate(points):
            point_label = labels[i] if labels and i < len(labels) else None
            self.point(
                pt[0], pt[1], radius=radius, color=color, alpha=alpha,
                label=point_label, label_color=label_color,
            )
        if legend_label or label:
            self._legend_items.append((legend_label or label or "", color or self._style.color))

    def circle(
        self,
        cx: float,
        cy: float,
        r: float,
        fill: str | None = None,
        stroke: str | None = None,
        width: float | None = None,
        n: int = 64,
        alpha: float | None = None,
        fill_alpha: float | None = None,
    ):
        """Circle in world coords -- sampled as a polygon to respect non-uniform axes."""
        pen = self._make_pen(color=stroke, width=width, alpha=alpha)
        poly = QPolygonF()
        for i in range(n + 1):
            a = 2.0 * math.pi * i / n
            x = cx + r * math.cos(a)
            y = cy + r * math.sin(a)
            poly.append(QPointF(*self._to_device(x, y)))
        if fill:
            self.painter.setPen(Qt.PenStyle.NoPen)
            self.painter.setBrush(QBrush(_to_qcolor(fill, fill_alpha or self._style.fill_alpha)))
            self.painter.drawPolygon(poly)
        self.painter.setPen(pen)
        self.painter.setBrush(Qt.BrushStyle.NoBrush)
        self.painter.drawPolygon(poly)

    def ellipse(
        self,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
        fill: str | None = None,
        stroke: str | None = None,
        width: float | None = None,
        n: int = 64,
        alpha: float | None = None,
        fill_alpha: float | None = None,
    ):
        pen = self._make_pen(color=stroke, width=width, alpha=alpha)
        poly = QPolygonF()
        for i in range(n + 1):
            a = 2.0 * math.pi * i / n
            x = cx + rx * math.cos(a)
            y = cy + ry * math.sin(a)
            poly.append(QPointF(*self._to_device(x, y)))
        if fill:
            self.painter.setPen(Qt.PenStyle.NoPen)
            self.painter.setBrush(QBrush(_to_qcolor(fill, fill_alpha or self._style.fill_alpha)))
            self.painter.drawPolygon(poly)
        self.painter.setPen(pen)
        self.painter.setBrush(Qt.BrushStyle.NoBrush)
        self.painter.drawPolygon(poly)

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: str | None = None,
        stroke: str | None = None,
        width: float | None = None,
        alpha: float | None = None,
        fill_alpha: float | None = None,
    ):
        poly = QPolygonF([
            QPointF(*self._to_device(x, y)),
            QPointF(*self._to_device(x + w, y)),
            QPointF(*self._to_device(x + w, y + h)),
            QPointF(*self._to_device(x, y + h)),
        ])
        if fill:
            self.painter.setPen(Qt.PenStyle.NoPen)
            self.painter.setBrush(QBrush(_to_qcolor(fill, fill_alpha or self._style.fill_alpha)))
            self.painter.drawPolygon(poly)
        pen = self._make_pen(color=stroke, width=width, alpha=alpha)
        self.painter.setPen(pen)
        self.painter.setBrush(Qt.BrushStyle.NoBrush)
        self.painter.drawPolygon(poly)

    def rectangle(self, *args, **kwargs):
        self.rect(*args, **kwargs)

    def polygon(
        self,
        points: list,
        fill: str | None = None,
        stroke: str | None = None,
        width: float | None = None,
        close: bool = True,
        style: str | None = None,
        alpha: float | None = None,
        fill_alpha: float | None = None,
    ):
        poly = QPolygonF([QPointF(*self._to_device(pt[0], pt[1])) for pt in points])
        if fill:
            self.painter.setPen(Qt.PenStyle.NoPen)
            self.painter.setBrush(QBrush(_to_qcolor(fill, fill_alpha or self._style.fill_alpha)))
            self.painter.drawPolygon(poly)
        pen = self._make_pen(color=stroke, width=width, style=style, alpha=alpha)
        self.painter.setPen(pen)
        self.painter.setBrush(Qt.BrushStyle.NoBrush)
        self.painter.drawPolygon(poly)

    def polyline(
        self,
        points: list,
        color: str | None = None,
        width: float | None = None,
        style: str | None = None,
        alpha: float | None = None,
    ):
        pen = self._make_pen(color=color, width=width, style=style, alpha=alpha)
        self.painter.setPen(pen)
        for i in range(len(points) - 1):
            p1 = QPointF(*self._to_device(points[i][0], points[i][1]))
            p2 = QPointF(*self._to_device(points[i + 1][0], points[i + 1][1]))
            self.painter.drawLine(p1, p2)

    def fill_polygon(
        self,
        points: list,
        fill: str | None = None,
        alpha: float | None = None,
        stroke: str | None = None,
        width: float | None = None,
        style: str | None = None,
    ):
        pen = self._make_pen(color=stroke, width=width, style=style)
        self.painter.setPen(pen)
        poly = QPolygonF([QPointF(*self._to_device(pt[0], pt[1])) for pt in points])
        if fill:
            self.painter.setBrush(QBrush(_to_qcolor(fill, alpha or self._style.fill_alpha)))
        else:
            self.painter.setBrush(QBrush(_to_qcolor(self._style.fill, self._style.fill_alpha)))
        self.painter.drawPolygon(poly)

    def region(self, points: list, **kwargs):
        self.fill_polygon(points, **kwargs)

    def vector(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str | None = None,
        width: float | None = None,
        head_size: float = 0.5,
        alpha: float | None = None,
    ):
        p1 = QPointF(*self._to_device(x1, y1))
        p2 = QPointF(*self._to_device(x2, y2))
        pen = self._make_pen(color=color, width=width, alpha=alpha)
        self.painter.setPen(pen)
        self.painter.drawLine(p1, p2)
        dx = x2 - x1
        dy = y2 - y1
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1e-6:
            return
        ux = dx / length
        uy = dy / length
        scaled_head = head_size * self._device_scale_x() * 0.02
        bx = p2.x() - ux * scaled_head
        by = p2.y() - uy * scaled_head
        nx = -uy
        ny = ux
        half = 0.5 * scaled_head
        head = QPolygonF([
            QPointF(p2.x(), p2.y()),
            QPointF(bx + nx * half, by + ny * half),
            QPointF(bx - nx * half, by - ny * half),
        ])
        self.painter.setBrush(QBrush(pen.color()))
        self.painter.drawPolygon(head)

    def arrow(
        self,
        x: float,
        y: float,
        dx: float,
        dy: float,
        color: str | None = None,
        width: float | None = None,
        head_size: float = 0.5,
        alpha: float | None = None,
        length_includes_head: bool = True,
        **_,
    ):
        """Matplotlib-like arrow from (x, y) by delta (dx, dy)."""
        self.vector(x, y, x + dx, y + dy, color=color, width=width, head_size=head_size, alpha=alpha)

    def label(
        self,
        x: float,
        y: float,
        text: str,
        color: str | None = None,
        font_size: int = 1,
        anchor: str = "center",
        bg: str | None = None,
        _device_offset: tuple[float, float] = (0, 0),
    ):
        """Text at world point (x, y), always rendered upright (no axes rotation)."""
        p = QPointF(*self._to_device(x, y))
        ui = self.painter
        size = font_size * 2 + 4
        font = QFont("Arial", size)
        ui.setFont(font)
        fm = QFontMetricsF(font)
        w = fm.horizontalAdvance(text)
        h = fm.height()
        dx = 0
        dy = 0
        if "left" in anchor:
            dx = 0
        elif "right" in anchor:
            dx = -w
        else:
            dx = -w / 2
        if "top" in anchor:
            dy = h
        elif "bottom" in anchor:
            dy = 0
        else:
            dy = h / 2
        tx = p.x() + dx + _device_offset[0]
        ty = p.y() + dy + _device_offset[1]
        if bg:
            ui.fillRect(QRectF(tx - 2, ty - h, w + 4, h + 4), _to_qcolor(bg, 0.8))
        ui.setPen(_to_qcolor(color or "#000"))
        ui.drawText(QPointF(tx, ty), text)

    def text(self, x: float, y: float, s: str, **kwargs):
        """Matplotlib-like alias for ``label()``."""
        self.label(x, y, s, **kwargs)

    def title(self, text: str, color: str | None = None, font_size: int = 2, bg: str | None = None):
        ui = self.painter
        font = QFont("Arial", font_size * 4 + 4)
        ui.setFont(font)
        fm = QFontMetricsF(font)
        s = fm.horizontalAdvance(text)
        x = (self.size_px[0] - s) / 2
        y = 1.0 + fm.ascent()
        if bg:
            ui.fillRect(QRectF(x - 4, 0, s + 8, fm.height() + 4), _to_qcolor(bg, 0.8))
        ui.setPen(_to_qcolor(color or "#111827"))
        ui.drawText(QPointF(x, y), text)

    def annotate(
        self,
        text: str,
        xy: tuple[float, float],
        xytext: tuple[float, float] | None = None,
        arrow: bool = True,
        color: str | None = None,
        arrow_color: str | None = None,
        font_size: int = 1,
        anchor: str = "center",
        bg: str | None = None,
    ):
        """Place a label and optionally draw an arrow to ``xy``."""
        x, y = xy
        tx, ty = xytext if xytext else (x, y)
        self.label(tx, ty, text, color=color, font_size=font_size, anchor=anchor, bg=bg)
        if arrow and xytext:
            dx = tx - x
            dy = ty - y
            length = math.sqrt(dx * dx + dy * dy)
            if length > 1e-12:
                ux = dx / length
                uy = dy / length
                sx = x + ux * 1.2
                sy = y + uy * 1.2
                self.line(sx, sy, tx - ux * 0.5, ty - uy * 0.5, color=arrow_color or color or "#222", width=1.2)

    def legend(self, loc: str = "upper right", font_size: int = 1, bg: str = "#111827", border: bool = True):
        """Draw a small legend from labels passed to plot/scatter/fill_between."""
        ui = self.painter
        font = QFont("Arial", font_size * 6 + 4)
        ui.setFont(font)
        item = []
        labels = [s for s, _ in self._legend_items if s and s.strip() and s != "_"]
        if not labels:
            return
        text_w = max(ui.fontMetrics().horizontalAdvance(l) for l in labels)
        row_h = 16
        box_w = text_w + 30
        box_h = len(labels) * row_h + 20
        margin = 10
        loc_norm = loc.strip().lower()
        x0 = self.size_px[0] - box_w - margin
        y0 = margin
        if "left" in loc_norm:
            x0 = margin
        if "lower" in loc_norm or "bottom" in loc_norm:
            y0 = self.size_px[1] - box_h - margin
        ui.fillRect(QRectF(x0, y0, box_w, box_h), _to_qcolor(bg, 0.88))
        if border:
            ui.setPen(_to_qcolor("#cbd5e1"))
            ui.drawRect(QRectF(x0, y0, box_w, box_h))
        for i, (label, color) in enumerate(self._legend_items):
            if not label or label.strip() == "" or label == "_":
                continue
            cy = y0 + 10 + i * row_h
            ui.fillRect(QRectF(x0 + 8, cy - 4, 12, 8), _to_qcolor(color))
            ui.setPen(_to_qcolor("#ffffff"))
            ui.drawText(QPointF(x0 + 26, cy + 4), label)

    def set_style(
        self,
        color: str | None = None,
        width: float | None = None,
        line_style: str | None = None,
        alpha: float | None = None,
        fill: str | None = None,
        fill_alpha: float | None = None,
        font_size: int | None = None,
    ):
        s = self._style
        if color is not None:
            s.color = color
        if width is not None:
            s.width = width
        if line_style is not None:
            s.line_style = line_style
        if alpha is not None:
            s.alpha = alpha
        if fill is not None:
            s.fill = fill
        if fill_alpha is not None:
            s.fill_alpha = fill_alpha
        if font_size is not None:
            s.font_size = font_size

    def style(self, **kwargs):
        self.set_style(**kwargs)

    def set_color(self, color: str):
        self._style.color = color

    def set_width(self, width: float):
        self._style.width = width

    def set_linewidth(self, width: float):
        self._style.width = width

    def set_linestyle(self, style: str):
        self._style.line_style = style

    def set_alpha(self, alpha: float):
        self._style.alpha = alpha

    def set_fill(self, fill: str, alpha: float | None = None):
        self._style.fill = fill
        if alpha is not None:
            self._style.fill_alpha = alpha

    def set_font_size(self, size: int):
        self._style.font_size = size

    def push(self):
        import copy
        self._style_stack.append(copy.copy(self._style))

    def pop(self):
        if len(self._style_stack) > 1:
            self._style_stack.pop()


def _auto_grid_step(xmin, xmax, ymin, ymax):
    span = max(abs(xmax - xmin), abs(ymax - ymin))
    if span <= 0:
        return 1.0
    raw = span / 10.0
    mag = 10.0 ** int(math.floor(math.log10(raw))) if raw > 0 else 1.0
    norm = raw / mag
    if norm < 1.5:
        step = 1.0 * mag
    elif norm < 3.5:
        step = 2.0 * mag
    elif norm < 7.5:
        step = 5.0 * mag
    else:
        step = 10.0 * mag
    return step


def _format_tick(v: float) -> str:
    if abs(v) < 1e-6:
        return "0"
    return f"{v:g}"


class EDrawBackend:
    """Default backend -- runs user code with QPainter primitives via ``ed``."""

    name = "edraw"
    allow_modules = frozenset({"math"})

    def compile(self, code: str) -> BackendProgram:
        validate_source(code, allow_modules=self.allow_modules)
        sandbox = {"__builtins__": _SAFE_BUILTINS, "__name__": "__edraw__"}
        locals_dict: dict[str, Any] = {}
        try:
            compiled = compile(code, "<python_figure>", "exec")
        except SyntaxError as exc:
            raise ValueError(f"Cú pháp Python lỗi: {exc}") from exc
        exec(compiled, sandbox, locals_dict)
        draw_fn = locals_dict.get("eDraw")
        warnings: list[str] = []
        if draw_fn is None:
            legacy_draw = locals_dict.get("draw")
            if legacy_draw is not None:
                warnings.append("Hàm draw(ed, p) cũ vẫn chạy được, nhưng hãy đổi sang eDraw(ed, p).")
                draw_fn = legacy_draw
            else:
                raise ValueError("Code thiếu hàm eDraw(ed, p). Hãy định nghĩa: def eDraw(ed, p): ...")
        raw_params = locals_dict.get("PARAMS", {})
        param_specs = _normalise_param_specs(raw_params) if isinstance(raw_params, dict) else {}
        program = BackendProgram(
            source=code,
            compiled_code=compiled,
            warnings=warnings,
            payload={"draw_fn": draw_fn, "params": param_specs},
        )
        return program

    def render(
        self,
        program: BackendProgram,
        params: dict[str, float],
        size_px: tuple[int, int],
    ) -> RenderResult:
        if not program or not program.payload:
            raise ValueError("Backend program rỗng (chưa compile).")
        draw_fn = program.payload.get("draw")
        if draw_fn is None:
            raise ValueError("Backend program rỗng (chưa compile).")
        w = max(1, int(size_px[0]))
        h = max(1, int(size_px[1]))
        render_scale = float(getattr(program, "__edraw_render_scale__", 1.0))
        user_params = dict(params) if params else {}
        image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        ed = EDrawContext(image, painter, (w, h), render_scale)
        draw_fn(ed, user_params)
        painter.end()
        return RenderResult(image=image, warnings=list(program.warnings))


def _normalise_param_specs(raw: dict) -> dict:
    """Validate & normalise the user-supplied PARAMS dict."""
    out: dict[str, dict] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        lo = float(spec.get("min", 0.0))
        hi = float(spec.get("max", 1.0))
        step = float(spec.get("step", 1.0))
        value = float(spec.get("value", lo))
        label = spec.get("label", "")
        out[name] = {"min": lo, "max": hi, "step": step, "value": value, "label": label}
    return out
