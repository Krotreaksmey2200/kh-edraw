'''
core/drawing_engine.py
Logic vẽ thuần túy, không phụ thuộc widget:
- Quản lý trạng thái stroke.
- Tạo đường cong mượt bằng midpoint quadratic Bézier.
- Lọc jitter / bỏ điểm quá sát.
- Hỗ trợ pressure tùy chọn mà vẫn giữ tương thích API cũ.
- Hỗ trợ thêm các mode hình học cho toolbar nhóm mới.

API công khai được giữ:
- DrawMode
- DrawingEngine.draw_pen
- DrawingEngine.eraser_pen
- DrawingEngine.on_press(pos, ...)
- DrawingEngine.on_move(pos, ...)
- DrawingEngine.on_release(pos, ...)
- DrawingEngine.get_preview_path()

API bổ sung không phá tương thích:
- get_preview_segments(): trả các đoạn nét có width riêng để vẽ pressure.
- take_committed_segments(): trả và xóa các đoạn đã commit sau on_release().
'''
from __future__ import annotations
import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor, QPainterPath, QPen, QPolygonF, QTransform,
)


class DrawMode(Enum):
    FREEHAND = auto()
    HIGHLIGHT = auto()
    ERASER = auto()
    LINE = auto()
    ARROW = auto()
    ARROW_DOUBLE = auto()
    ARROW_CLOSED = auto()
    ARROW_DOUBLE_CLOSED = auto()
    ARROW_STEALTH = auto()
    ARROW_DOUBLE_STEALTH = auto()
    LINE_DIAMOND = auto()
    LINE_DOT = auto()
    LINE_DIMENSION = auto()
    LINE_BRACE = auto()
    BEZIER = auto()
    CIRCLE = auto()
    SEMICIRCLE = auto()
    ELLIPSE = auto()
    HALF_ELLIPSE = auto()
    PARABOLA = auto()
    RECTANGLE = auto()
    TRIANGLE = auto()
    PARALLELOGRAM = auto()
    CUSTOM_CURVE = auto()
    CUSTOM_LINE = auto()
    CUSTOM_POLYGON = auto()
    CUSTOM_GEOMETRY = auto()
    CUSTOM_FREE = auto()
    TYPE = auto()
    SELECT_RECT = auto()
    SELECT_FREE = auto()


class PenKind(Enum):
    NORMAL = auto()
    CALLIGRAPHY = auto()


@dataclass
class PenSample:
    x: float
    y: float
    pressure: float = 1.0
    time: float = 0.0

    def point(self) -> QPointF:
        return QPointF(self.x, self.y)


@dataclass
class CalligraphyProfile:
    angle_deg: float = 45.0
    broad_width: float = 6.0
    thin_width: float = 1.0
    pressure_gain: float = 0.10
    spacing: float = 0.65
    smoothing: float = 0.55


@dataclass
class RoundPenProfile:
    spacing: float = 0.65
    smoothing: float = 0.55
    pressure_strength: float = 0.80


@dataclass
class InkOutline:
    path: QPainterPath
    bounds: QRectF


@dataclass
class StrokeSegment:
    path: QPainterPath
    width: float


# ---------------------------------------------------------------------------
#  One-Euro jitter filter
# ---------------------------------------------------------------------------

class _LowPassFilter:
    def __init__(self):
        self._value = None

    def reset(self):
        self._value = None

    def apply(self, value, alpha):
        if self._value is None:
            self._value = value
        else:
            self._value = alpha * value + (1.0 - alpha) * self._value
        return self._value


class _OneEuroValueFilter:
    def __init__(self, *, min_cutoff, beta, d_cutoff):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._x_filter = _LowPassFilter()
        self._dx_filter = _LowPassFilter()
        self._last_raw = None
        self._last_time = None

    def reset(self):
        self._x_filter.reset()
        self._dx_filter.reset()
        self._last_raw = None
        self._last_time = None

    @staticmethod
    def _alpha(cutoff, dt):
        cutoff = max(0.001, float(cutoff))
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / max(0.0001, dt))

    def __call__(self, value, timestamp):
        if self._last_time is None or self._last_raw is None:
            self._last_raw = value
            self._last_time = timestamp
            self._x_filter.reset()
            self._dx_filter.reset()
            return value
        dt = max(0.0001, timestamp - self._last_time)
        dx_hat = (value - self._last_raw) / dt
        alpha_d = self._alpha(self.d_cutoff, dt)
        dx = self._dx_filter.apply(dx_hat, alpha_d)
        cutoff = self.min_cutoff + self.beta * abs(dx)
        alpha = self._alpha(cutoff, dt)
        result = self._x_filter.apply(value, alpha)
        self._last_raw = value
        self._last_time = timestamp
        return result


class OneEuroPointFilter:
    '''One Euro filter for QPointF with separate raw and filtered state.'''

    def __init__(self, *, min_cutoff, beta, d_cutoff):
        self._x = _OneEuroValueFilter(min_cutoff=min_cutoff, beta=beta, d_cutoff=d_cutoff)
        self._y = _OneEuroValueFilter(min_cutoff=min_cutoff, beta=beta, d_cutoff=d_cutoff)

    def reset(self):
        self._x.reset()
        self._y.reset()

    def set_params(self, min_cutoff=None, beta=None, d_cutoff=None):
        for axis in (self._x, self._y):
            if min_cutoff is not None:
                axis.min_cutoff = max(0.05, float(min_cutoff))
            if beta is not None:
                axis.beta = max(0.0, float(beta))
            if d_cutoff is not None:
                axis.d_cutoff = max(0.05, float(d_cutoff))

    @property
    def min_cutoff(self):
        return self._x.min_cutoff

    @property
    def beta(self):
        return self._x.beta

    @property
    def d_cutoff(self):
        return self._x.d_cutoff

    def __call__(self, pos, timestamp):
        x = self._x(pos.x(), timestamp)
        y = self._y(pos.y(), timestamp)
        return QPointF(x, y)


# ---------------------------------------------------------------------------
#  Geometry / custom-tool path builders
# ---------------------------------------------------------------------------

def _build_midpoint_marker(points):
    '''Chấm tròn tại trung điểm của 2 điểm.'''
    path = QPainterPath()
    if len(points) < 2:
        return path
    p0 = points[0]
    p1 = points[1]
    mid_x = (p0.x() + p1.x()) / 2
    mid_y = (p0.y() + p1.y()) / 2
    if math.hypot(p1.x() - p0.x(), p1.y() - p0.y()) < 1:
        return path
    r = 6.0
    path.addEllipse(QRectF(mid_x - r, mid_y - r, r * 2, r * 2))
    return path


def _build_perpendicular_bisector(points):
    '''Đường trung trực của đoạn nối 2 điểm.'''
    path = QPainterPath()
    if len(points) < 2:
        return path
    p0 = points[0]
    p1 = points[1]
    dx = p1.x() - p0.x()
    dy = p1.y() - p0.y()
    length = math.hypot(dx, dy)
    if length < 1:
        return path
    mid_x = (p0.x() + p1.x()) / 2
    mid_y = (p0.y() + p1.y()) / 2
    ux = dx / length
    uy = dy / length
    nx = -uy
    ny = ux
    arm = 250
    path.moveTo(QPointF(mid_x - nx * arm, mid_y - ny * arm))
    path.lineTo(QPointF(mid_x + nx * arm, mid_y + ny * arm))
    return path


def _build_flat_brace_connector(points):
    '''Đường nối dạng ngoặc nhọn dẹt có đoạn thẳng dài.'''
    path = QPainterPath()
    if len(points) < 2:
        return path
    p0 = points[0]
    p1 = points[1]
    dx = p1.x() - p0.x()
    dy = p1.y() - p0.y()
    length = math.hypot(dx, dy)
    if length < 1:
        return path
    ux = dx / length
    uy = dy / length
    nx = -uy
    ny = ux
    depth = 8
    r = 15
    if length < 4 * r:
        r = length / 4
        depth = r * 0.6
    path.moveTo(p0)
    p_base_start = QPointF(p0.x() + r * ux + depth * nx, p0.y() + r * uy + depth * ny)
    c1 = QPointF(p0.x() + depth * nx, p0.y() + depth * ny)
    path.quadTo(c1, p_base_start)
    p_mid_left = QPointF(
        p0.x() + (length / 2 - r) * ux + depth * nx,
        p0.y() + (length / 2 - r) * uy + depth * ny,
    )
    path.lineTo(p_mid_left)
    p_mid = QPointF(
        p0.x() + (length / 2) * ux + 2 * depth * nx,
        p0.y() + (length / 2) * uy + 2 * depth * ny,
    )
    c2 = QPointF(
        p0.x() + (length / 2) * ux + depth * nx,
        p0.y() + (length / 2) * uy + depth * ny,
    )
    path.quadTo(c2, p_mid)
    p_mid_right = QPointF(
        p0.x() + (length / 2 + r) * ux + depth * nx,
        p0.y() + (length / 2 + r) * uy + depth * ny,
    )
    c3 = QPointF(
        p0.x() + (length / 2) * ux + depth * nx,
        p0.y() + (length / 2) * uy + depth * ny,
    )
    path.quadTo(c3, p_mid_right)
    p_base_end = QPointF(
        p0.x() + (length - r) * ux + depth * nx,
        p0.y() + (length - r) * uy + depth * ny,
    )
    path.lineTo(p_base_end)
    c4 = QPointF(p1.x() + depth * nx, p1.y() + depth * ny)
    path.quadTo(c4, p1)
    return path


def _build_free_polygon(points, *, closed):
    '''Da giac tu do: moi diem click la mot dinh, ket thuc bang chuot phai.'''
    path = QPainterPath()
    if len(points) < 2:
        return path
    path.moveTo(points[0])
    for pt in points[1:]:
        path.lineTo(pt)
    if closed and len(points) >= 3:
        path.closeSubpath()
    return path


def _build_freehand_sketch(points, *, closed):
    '''Duong cong Catmull-Rom di qua chuoi diem nguoi dung click.'''
    path = QPainterPath()
    if len(points) < 2:
        return path
    if len(points) == 2:
        path.moveTo(points[0])
        path.lineTo(points[1])
        return path
    path.moveTo(points[0])
    for i in range(len(points) - 1):
        p0 = points[max(0, i - 1)]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[min(len(points) - 1, i + 2)]
        cp1x = p1.x() + (p2.x() - p0.x()) / 6
        cp1y = p1.y() + (p2.y() - p0.y()) / 6
        cp2x = p2.x() - (p3.x() - p1.x()) / 6
        cp2y = p2.y() - (p3.y() - p1.y()) / 6
        path.cubicTo(QPointF(cp1x, cp1y), QPointF(cp2x, cp2y), p2)
    if closed:
        path.closeSubpath()
    return path


# ---------------------------------------------------------------------------
#  DrawingEngine
# ---------------------------------------------------------------------------

class DrawingEngine:
    '''
    Giữ toàn bộ trạng thái stroke đang diễn ra.

    Điểm nâng cấp quan trọng so với path-only engine:
    - on_press/on_move/on_release vẫn nhận QPointF như cũ.
    - Có thể truyền thêm pressure nếu Canvas nhận được QTabletEvent.
    - FREEHAND vẫn trả QPainterPath fallback, đồng thời lưu các StrokeSegment
      để Canvas vẽ nét pressure/dynamic-width mượt hơn.
    '''

    def __init__(self):
        self.mode = DrawMode.FREEHAND
        self.pen_kind = PenKind.NORMAL
        self.pen_color = QColor(Qt.GlobalColor.black)
        self.pen_width = 3
        self.highlight_color = QColor('#eab308')
        self.highlight_width = 15
        self.highlight_opacity = 50
        self.line_color = QColor(Qt.GlobalColor.black)
        self.line_width = 3
        self.line_opacity = 100
        self.curve_color = QColor(Qt.GlobalColor.black)
        self.curve_width = 3
        self.curve_opacity = 100
        self.curve_fill_enabled = False
        self.curve_border_enabled = True
        self.polygon_color = QColor(Qt.GlobalColor.black)
        self.polygon_width = 3
        self.polygon_opacity = 100
        self.polygon_fill_enabled = False
        self.polygon_border_enabled = True
        self.polygon_fill_color = QColor('#94a3b8')
        self.polygon_fill_opacity = 0
        self.polygon_fill_style = 'solid'
        self.polygon_fill_style_idx = 0
        self.markdown_font_size = 16
        self.pen_opacity = 100
        self.pen_style = Qt.PenStyle.SolidLine
        self.pen_dash_pattern = None
        self.pen_style_idx = 0
        self.eraser_width = 20
        self.tool_attrs = {}
        self.tool_attrs_follow_pen = True
        self.freehand_smoothing = 0.52
        self.calligraphy_profile = CalligraphyProfile()
        self.round_pen_profile = RoundPenProfile()
        self.freehand_min_distance = 0
        self.ink_sampling_min_distance = 0.5
        self.final_stroke_smoothing_enabled = False
        self.free_close_enabled = True
        self.one_euro = OneEuroPointFilter(min_cutoff=2.5, beta=0.5, d_cutoff=1)
        self._lead_lookahead_sec = 0
        self._lead_predict_min_speed = 1000
        self.use_pressure = False
        self.pressure_width_strength = 1
        self.velocity_width_strength = 0.1
        self._path = QPainterPath()
        self._smooth_anchor = QPointF()
        self._last_raw_pos = QPointF()
        self._last_raw_point = None
        self._last_filtered_point = None
        self._stroke_start = QPointF()
        self._path_current_pos = QPointF()
        self._freehand_points = 0
        self._freehand_moved = False
        self._stroke_points_buffer = []
        self._last_pressure = None
        self._last_width = float(self.pen_width)
        self._segments = []
        self._committed_segments = []
        self._raw_samples = []
        self._wet_outline = None
        self._committed_outline = None
        self._wet_prefix_path = QPainterPath()
        self._wet_prefix_bounds = QRectF()
        self._wet_frozen_index = 0
        self._wet_sample_tail = 36
        self._wet_freeze_chunk = 12
        self._round_samples = []
        self._round_wet_outline = None
        self._round_wet_prefix_path = QPainterPath()
        self._round_wet_prefix_bounds = QRectF()
        self._round_wet_frozen_index = 0
        self._round_wet_sample_tail = 36
        self._round_wet_freeze_chunk = 12
        self.p0 = QPointF()
        self.p1 = QPointF()
        self.p2 = QPointF()
        self.p3 = QPointF()
        self.bezier_step = 0
        self.ellipse_step = 0
        self.parabola_step = 0
        self.polygon_step = 0
        self.is_dragging = False
        self.cursor_pos = QPointF(-9999, -9999)
        self.custom_tools = {}
        self.geometry_tools = {
            'midpoint_2': {
                'name': 'midpoint_2',
                'description': 'Trung điểm',
                'n_points': 2,
                'fn': _build_midpoint_marker,
                'tool_type': 'geometry',
                'built_in': True,
            },
            'perpendicular_bisector': {
                'name': 'perpendicular_bisector',
                'description': 'Đường trung trực',
                'n_points': 2,
                'fn': _build_perpendicular_bisector,
                'tool_type': 'geometry',
                'built_in': True,
            },
        }
        self.free_tools = {
            'free_polygon': {
                'name': 'free_polygon',
                'description': 'Đa giác',
                'n_points': -1,
                'min_points': 3,
                'fn': _build_free_polygon,
                'tool_type': 'free',
                'built_in': True,
                'close_toggle': True,
            },
            'freehand_sketch': {
                'name': 'freehand_sketch',
                'description': 'Đường cong',
                'n_points': -1,
                'min_points': 2,
                'fn': _build_freehand_sketch,
                'tool_type': 'free',
                'built_in': True,
                'close_toggle': True,
            },
        }
        self.current_custom_tool = None
        self.custom_points = []

    # ------------------------------------------------------------------
    #  Mode helpers
    # ------------------------------------------------------------------

    def _is_line_mode(self):
        return self.mode in (
            DrawMode.LINE, DrawMode.ARROW, DrawMode.ARROW_DOUBLE,
            DrawMode.ARROW_CLOSED, DrawMode.ARROW_DOUBLE_CLOSED,
            DrawMode.ARROW_STEALTH, DrawMode.ARROW_DOUBLE_STEALTH,
            DrawMode.LINE_DIAMOND, DrawMode.LINE_DOT,
            DrawMode.LINE_DIMENSION, DrawMode.LINE_BRACE,
            DrawMode.CUSTOM_LINE, DrawMode.CUSTOM_GEOMETRY,
        )

    def _is_simple_drag_mode(self):
        if self._is_line_mode():
            return True
        if self.mode in (DrawMode.CUSTOM_LINE, DrawMode.CUSTOM_GEOMETRY):
            return True
        return self.mode in (DrawMode.CIRCLE, DrawMode.SEMICIRCLE)

    def _is_curve_mode(self):
        return self.mode in (
            DrawMode.BEZIER, DrawMode.CIRCLE, DrawMode.SEMICIRCLE,
            DrawMode.ELLIPSE, DrawMode.HALF_ELLIPSE, DrawMode.PARABOLA,
            DrawMode.CUSTOM_CURVE, DrawMode.CUSTOM_FREE,
        )

    def _is_polygon_mode(self):
        return self.mode in (
            DrawMode.RECTANGLE, DrawMode.TRIANGLE,
            DrawMode.PARALLELOGRAM, DrawMode.CUSTOM_POLYGON,
        )

    # ------------------------------------------------------------------
    #  Tool attribute management
    # ------------------------------------------------------------------

    def _active_tool_attr_key(self):
        '''Khóa thuộc tính riêng cho từng công cụ hình học đang active.'''
        if self.mode in (
            DrawMode.FREEHAND, DrawMode.HIGHLIGHT, DrawMode.ERASER,
            DrawMode.SELECT_RECT, DrawMode.SELECT_FREE,
        ):
            return None
        if self.mode in (
            DrawMode.CUSTOM_LINE, DrawMode.CUSTOM_CURVE,
            DrawMode.CUSTOM_POLYGON, DrawMode.CUSTOM_GEOMETRY,
            DrawMode.CUSTOM_FREE,
        ):
            if not self.current_custom_tool:
                return None
            return f'{self.mode.name}:{self.current_custom_tool}'
        return self.mode.name

    def _active_tool_follows_pen(self):
        '''Công cụ hình học dùng trực tiếp thuộc tính của bút vẽ active.'''
        if self.tool_attrs_follow_pen:
            return True
        return self._active_tool_attr_key() is not None

    def reset_tool_attrs_to_defaults(self):
        '''Đưa các công cụ hình học về bộ thuộc tính mặc định độc lập.'''
        self.tool_attrs.clear()
        self.line_color = QColor(Qt.GlobalColor.black)
        self.line_width = 3
        self.line_opacity = 100
        self.curve_color = QColor(Qt.GlobalColor.black)
        self.curve_width = 3
        self.curve_opacity = 100
        self.curve_fill_enabled = False
        self.curve_border_enabled = True
        self.polygon_color = QColor(Qt.GlobalColor.black)
        self.polygon_width = 3
        self.polygon_opacity = 100
        self.polygon_fill_enabled = False
        self.polygon_border_enabled = True
        self.polygon_fill_color = QColor('#94a3b8')
        self.polygon_fill_opacity = 0
        self.polygon_fill_style = 'solid'
        self.polygon_fill_style_idx = 0

    def _default_tool_attrs(self):
        if self._is_polygon_mode():
            color = self.polygon_color
            width = self.polygon_width
            opacity = self.polygon_opacity
        elif self._is_curve_mode():
            color = self.curve_color
            width = self.curve_width
            opacity = self.curve_opacity
        elif self._is_line_mode():
            color = self.line_color
            width = self.line_width
            opacity = self.line_opacity
        else:
            color = self.pen_color
            width = self.pen_width
            opacity = self.pen_opacity
        return {
            'color': QColor(color),
            'width': int(width),
            'opacity': int(opacity),
            'style': Qt.PenStyle.SolidLine,
            'dash_pattern': None,
            'style_idx': 0,
            'border_enabled': True,
            'fill_enabled': bool(
                self.curve_fill_enabled if self._is_curve_mode()
                else self.polygon_fill_enabled
            ),
            'fill_color': QColor(self.polygon_fill_color),
            'fill_opacity': int(self.polygon_fill_opacity),
            'fill_style': self.polygon_fill_style,
            'fill_style_idx': int(self.polygon_fill_style_idx),
        }

    def _active_tool_attrs(self):
        key = self._active_tool_attr_key()
        if key is None:
            return None
        if key not in self.tool_attrs:
            self.tool_attrs[key] = self._default_tool_attrs()
        return self.tool_attrs[key]

    # ------------------------------------------------------------------
    #  Active color / width / opacity / style getters & setters
    # ------------------------------------------------------------------

    def get_active_color(self):
        if self._active_tool_follows_pen():
            return QColor(self.pen_color)
        attrs = self._active_tool_attrs()
        if attrs is None:
            return QColor(self.pen_color)
        return QColor(attrs['color'])

    def set_active_color(self, c):
        if self._active_tool_follows_pen():
            self.pen_color = QColor(c)
            return
        attrs = self._active_tool_attrs()
        if attrs is not None:
            attrs['color'] = QColor(c)

    def get_active_width(self):
        if self.mode == DrawMode.TYPE:
            return int(self.markdown_font_size)
        if self._active_tool_follows_pen():
            return int(self.pen_width)
        attrs = self._active_tool_attrs()
        if attrs is None:
            return int(self.pen_width)
        return int(attrs['width'])

    def set_active_width(self, w):
        if self.mode == DrawMode.TYPE:
            self.markdown_font_size = max(1, min(200, int(w)))
            return
        if self._active_tool_follows_pen():
            self.pen_width = int(w)
            return
        attrs = self._active_tool_attrs()
        if attrs is not None:
            attrs['width'] = int(w)

    def get_active_opacity(self):
        if self._active_tool_follows_pen():
            return int(self.pen_opacity)
        attrs = self._active_tool_attrs()
        if attrs is None:
            return int(self.pen_opacity)
        return int(attrs['opacity'])

    def set_active_opacity(self, v):
        v = max(0, min(100, int(v)))
        if self._active_tool_follows_pen():
            self.pen_opacity = v
            return
        attrs = self._active_tool_attrs()
        if attrs is not None:
            attrs['opacity'] = v

    def get_active_style_idx(self):
        if self._active_tool_follows_pen():
            return max(0, int(self.pen_style_idx))
        attrs = self._active_tool_attrs()
        if attrs is None:
            return 0
        return max(0, int(attrs.get('style_idx', 0)))

    def set_active_style(self, style, dash_pattern=None, style_idx=0):
        style_idx = max(0, int(style_idx))
        if self._active_tool_follows_pen():
            self.pen_style = style
            self.pen_dash_pattern = dash_pattern
            self.pen_style_idx = style_idx
            return
        attrs = self._active_tool_attrs()
        if attrs is not None:
            attrs['style'] = style
            attrs['dash_pattern'] = dash_pattern
            attrs['style_idx'] = style_idx

    # ------------------------------------------------------------------
    #  Border / fill toggle
    # ------------------------------------------------------------------

    def is_border_toggle_mode(self):
        if self.mode == DrawMode.CUSTOM_FREE:
            return True
        if self._is_curve_mode():
            return True
        return self._is_polygon_mode()

    def get_active_border_enabled(self):
        attrs = self._active_tool_attrs()
        if attrs is None:
            return True
        return bool(attrs.get('border_enabled', True))

    def set_active_border_enabled(self, enabled):
        enabled = bool(enabled)
        attrs = self._active_tool_attrs()
        if attrs is not None:
            attrs['border_enabled'] = enabled

    def should_draw_border(self):
        if self.is_border_toggle_mode():
            return self.get_active_border_enabled()
        return True

    # ------------------------------------------------------------------
    #  Region fill helpers
    # ------------------------------------------------------------------

    def _active_region_fill_attrs(self):
        if self._is_polygon_mode() or self._is_curve_mode() or self._active_tool_follows_pen():
            return None
        return self._active_tool_attrs()

    def get_active_fill_color(self):
        attrs = self._active_region_fill_attrs()
        if attrs is None:
            return QColor(self.polygon_fill_color)
        return QColor(attrs.get('fill_color', self.polygon_fill_color))

    def set_active_fill_color(self, color):
        attrs = self._active_region_fill_attrs()
        if attrs is not None:
            attrs['fill_color'] = QColor(color)

    def get_active_fill_enabled(self):
        attrs = self._active_region_fill_attrs()
        if attrs is None:
            return bool(self.polygon_fill_enabled)
        return bool(attrs.get('fill_enabled', self.polygon_fill_enabled))

    def set_active_fill_enabled(self, enabled):
        enabled = bool(enabled)
        attrs = self._active_region_fill_attrs()
        if attrs is not None:
            attrs['fill_enabled'] = enabled

    def get_active_fill_opacity(self):
        attrs = self._active_region_fill_attrs()
        if attrs is None:
            return int(self.polygon_fill_opacity)
        return int(attrs.get('fill_opacity', self.polygon_fill_opacity))

    def set_active_fill_opacity(self, value):
        value = max(0, min(100, int(value)))
        attrs = self._active_region_fill_attrs()
        if attrs is not None:
            attrs['fill_opacity'] = value

    def get_active_fill_style(self):
        attrs = self._active_region_fill_attrs()
        if attrs is None:
            return self.polygon_fill_style
        return attrs.get('fill_style', self.polygon_fill_style)

    def get_active_fill_style_idx(self):
        attrs = self._active_region_fill_attrs()
        if attrs is None:
            return int(self.polygon_fill_style_idx)
        return int(attrs.get('fill_style_idx', self.polygon_fill_style_idx))

    def set_active_fill_style(self, style_key=None, style_idx=None):
        if not style_key:
            style_key = 'solid'
        if style_idx is None:
            style_idx = 0
        attrs = self._active_region_fill_attrs()
        if attrs is not None:
            attrs['fill_style'] = str(style_key)
            attrs['fill_style_idx'] = int(style_idx)

    def should_fill_path(self):
        if self.mode == DrawMode.CUSTOM_GEOMETRY and self.current_custom_tool == 'midpoint_2':
            return True
        return self.mode in (
            DrawMode.ARROW_CLOSED, DrawMode.ARROW_DOUBLE_CLOSED,
            DrawMode.ARROW_STEALTH, DrawMode.ARROW_DOUBLE_STEALTH,
            DrawMode.LINE_DIAMOND, DrawMode.LINE_DOT,
        )

    @property
    def is_fillable_shape(self):
        return self.mode in (
            DrawMode.RECTANGLE, DrawMode.TRIANGLE,
            DrawMode.PARALLELOGRAM, DrawMode.CUSTOM_POLYGON,
        )

    def should_fill_polygon(self):
        if self.is_fillable_shape and self.get_active_fill_enabled():
            return self.get_active_fill_opacity() > 0
        return False

    def should_fill_curve_region(self):
        if self._is_curve_mode() and self.get_active_fill_enabled():
            return self.get_active_fill_opacity() > 0
        return False

    # ------------------------------------------------------------------
    #  Pen builders (properties)
    # ------------------------------------------------------------------

    @property
    def draw_pen(self):
        pen = QPen()
        color = QColor(self.get_active_color())
        opacity = self.get_active_opacity()
        if opacity < 100:
            color.setAlpha(max(0, min(255, int(opacity * 2.55))))
        pen.setColor(color)
        pen.setWidthF(float(self.get_active_width()))
        if self._active_tool_follows_pen():
            pen.setStyle(self.pen_style)
            if self.pen_dash_pattern:
                pen.setDashPattern(self.pen_dash_pattern)
        else:
            attrs = self._active_tool_attrs()
            if attrs is not None:
                pen.setStyle(attrs.get('style', Qt.PenStyle.SolidLine))
                if attrs.get('dash_pattern'):
                    pen.setDashPattern(attrs['dash_pattern'])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    @property
    def eraser_pen(self):
        pen = QPen()
        pen.setColor(QColor(Qt.GlobalColor.transparent))
        pen.setWidthF(float(self.eraser_width))
        pen.setStyle(Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    # ------------------------------------------------------------------
    #  Segment / stroke helpers
    # ------------------------------------------------------------------

    def should_use_segments(self):
        '''
        Chỉ dùng StrokeSegment width động cho pipeline cũ.

        Với nét đứt/chấm, vẽ cả QPainterPath bằng QPen dash của Qt sẽ giữ
        pattern liên tục hơn, tránh mỗi segment tự reset dash pattern.
        '''
        if self.mode == DrawMode.FREEHAND and self.pen_kind == PenKind.NORMAL:
            if not self.is_round_pen_freehand():
                if not self.pen_dash_pattern:
                    return self.pen_style == Qt.PenStyle.SolidLine
        return False

    def get_preview_segments(self):
        '''
        Trả các đoạn stroke đang vẽ để Canvas preview bằng width riêng.

        Nếu không có pressure hoặc đang không freehand, danh sách có thể rỗng.
        Canvas vẫn có thể fallback sang get_preview_path().
        '''
        if self.mode != DrawMode.FREEHAND or self.is_dragging:
            return []
        result = list(self._segments)
        if self._freehand_points > 0 and self._dist(self._path_current_pos, self.cursor_pos) > 0.01:
            tail = QPainterPath()
            tail.moveTo(self._path_current_pos)
            tail.lineTo(self.cursor_pos)
            result.append(StrokeSegment(tail, self._last_width))
            return result
        if self._freehand_points == 0 and self._dist(self._stroke_start, self.cursor_pos) > 0.01:
            tail = QPainterPath()
            tail.moveTo(self._stroke_start)
            tail.lineTo(self.cursor_pos)
            result.append(StrokeSegment(tail, self._last_width))
        return result

    def take_committed_segments(self):
        '''Lấy các segment của stroke vừa release để Canvas commit lên pixmap.'''
        out = self._committed_segments
        self._committed_segments = []
        return out

    # ------------------------------------------------------------------
    #  Freehand type checks
    # ------------------------------------------------------------------

    def is_round_pen_freehand(self):
        if self.mode == DrawMode.FREEHAND and self.pen_kind == PenKind.NORMAL:
            if not self.pen_dash_pattern:
                return self.pen_style == Qt.PenStyle.SolidLine
        return False

    def is_calligraphy_freehand(self):
        if self.mode == DrawMode.FREEHAND:
            return self.pen_kind == PenKind.CALLIGRAPHY
        return False

    # ------------------------------------------------------------------
    #  Outline preview / commit
    # ------------------------------------------------------------------

    def get_preview_outline(self):
        if not self.is_dragging:
            return None
        if self.is_calligraphy_freehand():
            return self._wet_outline
        if self.is_round_pen_freehand():
            return self._round_wet_outline
        return None

    def take_committed_outline(self):
        out = self._committed_outline
        self._committed_outline = None
        return out

    def calligraphy_dirty_padding(self):
        profile = self._active_calligraphy_profile()
        return max(12, profile.broad_width * 2 + 8)

    def outline_dirty_padding(self):
        if self.is_calligraphy_freehand():
            return self.calligraphy_dirty_padding()
        return max(12, float(self.get_active_width()) * 2 + 8)

    # ------------------------------------------------------------------
    #  Sample API
    # ------------------------------------------------------------------

    def add_sample(self, pos, pressure=None):
        self._append_calligraphy_sample(pos, pressure=pressure)

    def resample_samples(self, samples, spacing):
        return self._resample_samples(samples, spacing)

    def smooth_samples(self, samples, smoothing):
        profile = self._active_calligraphy_profile()
        return self._smooth_samples(samples, smoothing if smoothing is not None else profile.smoothing)

    def build_calligraphy_outline(self, samples, profile=None):
        if not profile:
            profile = self._active_calligraphy_profile()
        return self._build_calligraphy_outline(samples, profile)

    def build_round_pen_outline(self, samples, profile=None):
        if not profile:
            profile = self._active_round_pen_profile()
        return self._build_round_pen_outline(samples, profile)

    # ------------------------------------------------------------------
    #  Static / utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))

    @staticmethod
    def _dist(a, b):
        return math.hypot(a.x() - b.x(), a.y() - b.y())

    @staticmethod
    def _midpoint(a, b):
        return QPointF((a.x() + b.x()) * 0.5, (a.y() + b.y()) * 0.5)

    @staticmethod
    def _lerp(a, b, alpha):
        return QPointF(a.x() + (b.x() - a.x()) * alpha, a.y() + (b.y() - a.y()) * alpha)

    @staticmethod
    def _screen_angle_deg(center, pt):
        return -math.degrees(math.atan2(pt.y() - center.y(), pt.x() - center.x()))

    def _effective_min_distance(self):
        if self.freehand_min_distance > 0:
            return float(self.freehand_min_distance)
        return max(0.55, min(2.2, float(self.pen_width) * 0.3))

    def _adaptive_alpha(self, distance):
        smooth = self._clamp(float(self.freehand_smoothing), 0, 1)
        base = 0.9 - 0.44 * smooth
        speed_boost = min(0.28, distance / 16)
        if self._freehand_points <= 1:
            speed_boost += 0.12
        return self._clamp(base + speed_boost, 0.34, 0.94)

    def _normalise_pressure(self, pressure):
        if pressure is None:
            return 0.5
        return self._clamp(float(pressure), 0.0, 1.0)

    def _stroke_width(self, pressure, distance):
        base = max(0.1, float(self.get_active_width()))
        p = self._normalise_pressure(pressure)
        if self.use_pressure:
            w = base * (1.0 + (p - 0.5) * self.pressure_width_strength * 2)
        else:
            w = base
        w += max(0, min(0.5, distance * 0.002)) * self.velocity_width_strength
        return max(0.1, w)

    # ------------------------------------------------------------------
    #  Round pen profile
    # ------------------------------------------------------------------

    def _active_round_pen_profile(self):
        base = self.round_pen_profile
        return RoundPenProfile(
            spacing=max(0.35, float(base.spacing)),
            smoothing=self._clamp(float(base.smoothing), 0, 1),
            pressure_strength=self._clamp(float(base.pressure_strength), 0, 1),
        )

    def _round_pen_profile_with(self, profile, *, spacing, smoothing):
        return RoundPenProfile(
            spacing=max(0.35, float(spacing)),
            smoothing=self._clamp(float(smoothing), 0, 1),
            pressure_strength=profile.pressure_strength,
        )

    def _round_width(self, pressure, profile):
        base = max(0.35, float(self.get_active_width()))
        p = self._normalise_pressure(pressure)
        width = base * (0.6 + profile.pressure_strength * p * 0.8)
        return max(0.35, width)

    def _smooth_values(self, values, passes):
        if len(values) < 3:
            return list(values)
        smoothed = list(values)
        for _ in range(max(0, int(passes))):
            prev = smoothed[:]
            for i in range(1, len(values) - 1):
                smoothed[i] = prev[i - 1] * 0.25 + prev[i] * 0.5 + prev[i + 1] * 0.25
        return smoothed

    def _build_round_tap_outline(self, sample, profile):
        r = max(0.35, self._round_width(sample.pressure, profile) * 0.5)
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        path.addEllipse(QRectF(sample.x - r, sample.y - r, r * 2, r * 2))
        return InkOutline(path, path.boundingRect())

    def _append_round_sample(self, pos, *, pressure, force=False):
        sample = self._make_pen_sample(pos, pressure)
        if self._round_samples:
            last = self._round_samples[-1]
            distance = math.hypot(sample.x - last.x, sample.y - last.y)
            if distance <= 0.001:
                self._round_samples[-1] = sample
                self._last_pressure = pressure
                self._rebuild_round_wet_outline()
                return
            min_distance = max(0.25, self._active_round_pen_profile().spacing * 0.3)
            if force and distance < min_distance:
                return
            if not self._freehand_moved:
                self._freehand_moved = self._dist(self._stroke_start, QPointF(sample.x, sample.y)) >= min_distance
        self._round_samples.append(sample)
        self._last_pressure = pressure
        self._last_width = self._round_width(sample.pressure, self._active_round_pen_profile())
        self._rebuild_round_wet_outline()

    def _reset_round_wet_outline(self):
        self._round_wet_outline = None
        self._round_wet_prefix_path = QPainterPath()
        self._round_wet_prefix_path.setFillRule(Qt.FillRule.WindingFill)
        self._round_wet_prefix_bounds = QRectF()
        self._round_wet_frozen_index = 0

    def _rebuild_round_wet_outline(self, lead=None):
        if not self.is_round_pen_freehand() or not self._round_samples:
            self._round_wet_outline = None
            return
        profile = self._active_round_pen_profile()
        wet_profile = self._round_pen_profile_with(profile, spacing=0.75, smoothing=0.55)
        total = len(self._round_samples)
        freeze_to = max(0, total - self._round_wet_sample_tail)
        if freeze_to > self._round_wet_frozen_index:
            self._round_wet_frozen_index = freeze_to
            self._round_wet_prefix_path = QPainterPath()
            self._round_wet_prefix_path.setFillRule(Qt.FillRule.WindingFill)
            self._round_wet_prefix_bounds = QRectF()
            chunk_start = 0
            chunk_end = freeze_to
            if chunk_end > chunk_start:
                tail_samples = self._round_samples[chunk_start:chunk_end]
                prepared = self._prepare_dry_ink_samples(tail_samples, wet_profile.spacing)
                outline = self._build_round_pen_outline(prepared, wet_profile)
                if outline:
                    self._round_wet_prefix_path = outline.path
                    self._round_wet_prefix_bounds = outline.bounds
        wet_samples = self._round_samples[max(self._round_wet_frozen_index, 0):]
        if lead is not None:
            wet_samples = wet_samples + [lead]
        if len(wet_samples) < 2:
            tail_outline = None
            if wet_samples:
                tail_outline = self._build_round_tap_outline(wet_samples[0], wet_profile)
            combined = self._round_wet_prefix_path
            combined_bounds = self._round_wet_prefix_bounds
            if tail_outline:
                combined = QPainterPath(combined)
                combined.addPath(tail_outline.path)
                combined_bounds = combined_bounds.united(tail_outline.bounds) if not combined_bounds.isNull() else tail_outline.bounds
            self._round_wet_outline = InkOutline(combined, combined_bounds) if not combined.isEmpty() else None
            return
        prepared = self._prepare_dry_ink_samples(wet_samples, wet_profile.spacing)
        tail_outline = self._build_round_pen_outline(prepared, wet_profile)
        combined = QPainterPath(self._round_wet_prefix_path)
        combined_bounds = QRectF(self._round_wet_prefix_bounds)
        if tail_outline and not tail_outline.path.isEmpty():
            combined.addPath(tail_outline.path)
            combined_bounds = combined_bounds.united(tail_outline.bounds) if not combined_bounds.isNull() else tail_outline.bounds
        self._round_wet_outline = InkOutline(combined, combined_bounds) if not combined.isEmpty() else None

    def _build_round_pen_outline(
        self,
        samples: list[PenSample],
        profile: RoundPenProfile,
        *,
        width_passes: int = 1,
        cap_steps: int = 8,
        centerline_ready: bool = False,
    ) -> InkOutline | None:
        if not samples:
            return None
        if len(samples) == 1:
            return self._build_round_tap_outline(samples[0], profile)
        if centerline_ready:
            points = list(samples)
        else:
            points = self._smooth_samples(
                self._resample_samples(samples, profile.spacing),
                profile.smoothing,
            )
        if len(points) < 2:
            return self._build_round_tap_outline(samples[-1], profile)
        n = len(points)
        raw_dx = []
        raw_dy = []
        for i in range(n):
            prev_p = points[max(0, i - 1)]
            next_p = points[min(n - 1, i + 1)]
            raw_dx.append(next_p.x - prev_p.x)
            raw_dy.append(next_p.y - prev_p.y)
        sdx = raw_dx[:]
        sdy = raw_dy[:]
        for _ in range(2):
            pdx = sdx[:]
            pdy = sdy[:]
            for i in range(1, n - 1):
                sdx[i] = pdx[i - 1] * 0.25 + pdx[i] * 0.5 + pdx[i + 1] * 0.25
                sdy[i] = pdy[i - 1] * 0.25 + pdy[i] * 0.5 + pdy[i + 1] * 0.25
        tangents = []
        normals = []
        thetas = []
        for i in range(n):
            dx = sdx[i]
            dy = sdy[i]
            ln = math.hypot(dx, dy)
            if ln > 0.001:
                tx = dx / ln
                ty = dy / ln
                theta = math.atan2(dy, dx)
                nx = -ty
                ny = tx
            else:
                tx, ty = tangents[-1] if tangents else (1.0, 0.0)
                theta = thetas[-1] if thetas else 0.0
                nx, ny = normals[-1] if normals else (0.0, 1.0)
            tangents.append((tx, ty))
            normals.append((nx, ny))
            thetas.append(theta)

        widths = self._smooth_values(
            [self._round_width(sample.pressure, profile) for sample in points],
            width_passes,
        )
        left = []
        right = []
        for i, sample in enumerate(points):
            nx, ny = normals[i]
            r = widths[i] * 0.5
            left.append((sample.x + nx * r, sample.y + ny * r))
            right.append((sample.x - nx * r, sample.y - ny * r))

        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)

        def _center_seg_unit(i: int) -> tuple[float, float, float]:
            a = points[i]
            b = points[i + 1]
            dx = b.x - a.x
            dy = b.y - a.y
            ln = math.hypot(dx, dy)
            if ln <= 0.001:
                return (1.0, 0.0, 0.0)
            return (dx / ln, dy / ln, ln)

        def _aligned_handle(tangent: tuple[float, float], seg_unit: tuple[float, float], seg_len: float) -> float:
            alignment = max(0.0, tangent[0] * seg_unit[0] + tangent[1] * seg_unit[1])
            return seg_len * 0.34 * alignment

        def _cubic_forward(edge: list[tuple[float, float]], *, start_index: int, end_index: int, direction: int) -> None:
            i = start_index
            while i != end_index:
                j = i + direction
                sux, suy, seg_len = _center_seg_unit(min(i, j))
                if direction < 0:
                    sux = -sux
                    suy = -suy
                x1, y1 = edge[i]
                x2, y2 = edge[j]
                t1x, t1y = tangents[i]
                t2x, t2y = tangents[j]
                if direction < 0:
                    t1x = -t1x
                    t1y = -t1y
                    t2x = -t2x
                    t2y = -t2y
                h1 = _aligned_handle((t1x, t1y), (sux, suy), seg_len)
                h2 = _aligned_handle((t2x, t2y), (sux, suy), seg_len)
                path.cubicTo(
                    x1 + t1x * h1,
                    y1 + t1y * h1,
                    x2 - t2x * h2,
                    y2 - t2y * h2,
                    x2,
                    y2,
                )
                i = j

        def _arc_cap(cx: float, cy: float, r: float, start_angle: float, sweep: float) -> None:
            steps = max(3, int(cap_steps))
            for k in range(1, steps + 1):
                a = start_angle + sweep * (k / steps)
                path.lineTo(cx + math.cos(a) * r, cy + math.sin(a) * r)

        path.moveTo(left[0][0], left[0][1])
        _cubic_forward(left, start_index=0, end_index=n - 1, direction=1)
        _arc_cap(points[-1].x, points[-1].y, widths[-1] * 0.5, thetas[-1] + math.pi / 2, -math.pi)
        _cubic_forward(right, start_index=n - 1, end_index=0, direction=-1)
        _arc_cap(points[0].x, points[0].y, widths[0] * 0.5, thetas[0] - math.pi / 2, -math.pi)
        path.closeSubpath()

        if path.isEmpty():
            return None
        return InkOutline(path, path.boundingRect())

    # ------------------------------------------------------------------
    #  Calligraphy profile
    # ------------------------------------------------------------------

    def _active_calligraphy_profile(self):
        base = self.calligraphy_profile
        broad = max(1, float(self.get_active_width()))
        base_broad = max(0.1, float(base.broad_width))
        scale = broad / base_broad
        thin = max(0.35, min(broad * 0.85, float(base.thin_width) * scale))
        return CalligraphyProfile(
            angle_deg=float(base.angle_deg),
            broad_width=broad,
            thin_width=thin,
            pressure_gain=self._clamp(float(base.pressure_gain), 0, 0.25),
            spacing=max(0.35, float(base.spacing)),
            smoothing=self._clamp(float(base.smoothing), 0, 1),
        )

    def _calligraphy_profile_with(self, profile, *, spacing, smoothing):
        return CalligraphyProfile(
            angle_deg=profile.angle_deg,
            broad_width=profile.broad_width,
            thin_width=profile.thin_width,
            pressure_gain=profile.pressure_gain,
            spacing=max(0.35, float(spacing)),
            smoothing=self._clamp(float(smoothing), 0, 1),
        )

    # ------------------------------------------------------------------
    #  Pen sample factory
    # ------------------------------------------------------------------

    def _make_pen_sample(self, pos, pressure):
        return self._make_pen_sample_at(pos, pressure, time.perf_counter())

    def _make_pen_sample_at(self, pos, pressure, timestamp):
        p = self._normalise_pressure(pressure)
        return PenSample(pos.x(), pos.y(), p, timestamp)

    # ------------------------------------------------------------------
    #  Dual-ink (calligraphy / round pen) freehand
    # ------------------------------------------------------------------

    def _uses_dual_ink_freehand(self):
        if self.is_calligraphy_freehand():
            return True
        return self.is_round_pen_freehand()

    def _dual_ink_min_distance(self):
        if self.freehand_min_distance > 0:
            return max(0.1, float(self.freehand_min_distance))
        return self._clamp(float(self.ink_sampling_min_distance), 0.35, 1)

    def _start_dual_ink_stroke(self, pos, pressure=None):
        self.one_euro.reset()
        self._stroke_points_buffer = []
        self._last_raw_point = QPointF(pos)
        self._last_filtered_point = None
        now = time.perf_counter()
        filtered = self.one_euro(pos, now)
        sample = self._make_pen_sample_at(filtered, pressure, now)
        self._stroke_points_buffer.append(sample)
        self._path = QPainterPath()
        self._path.moveTo(filtered)
        self._stroke_start = QPointF(pos)
        self._smooth_anchor = QPointF(filtered)
        self._path_current_pos = QPointF(filtered)
        self._last_filtered_point = QPointF(filtered)
        self._last_raw_pos = QPointF(pos)
        self._last_pressure = pressure
        if self.is_round_pen_freehand():
            self._last_width = self._round_width(sample.pressure, self._active_round_pen_profile())
        elif self.is_calligraphy_freehand():
            self._last_width = self._active_calligraphy_profile().broad_width
        else:
            self._last_width = self._stroke_width(pressure, 0)
        self._sync_dual_ink_wet_outline(sample, replace_last=False)

    def _sync_dual_ink_wet_outline(self, sample, *, replace_last):
        '''Phản chiếu sample đã lọc sang buffer wet-outline và rebuild outline.'''
        if self.is_round_pen_freehand():
            target = self._round_samples
            rebuild = self._rebuild_round_wet_outline
        elif self.is_calligraphy_freehand():
            target = self._raw_samples
            rebuild = self._rebuild_wet_outline
        else:
            return
        if replace_last and target:
            target[-1] = sample
        else:
            target.append(sample)
        rebuild(self._dual_ink_lead_sample())

    def _dual_ink_lead_sample(self):
        '''Sample tạm tại / trước vị trí raw để wet outline kéo tới đầu bút.'''
        if not self._stroke_points_buffer:
            return None
        last = self._stroke_points_buffer[-1]
        raw = self._last_raw_pos
        if raw is None:
            return last
        lead_x = raw.x()
        lead_y = raw.y()
        if self._last_filtered_point is not None and self._last_width > 0:
            dx = raw.x() - self._last_filtered_point.x()
            dy = raw.y() - self._last_filtered_point.y()
            speed = math.hypot(dx, dy)
            if speed > self._lead_predict_min_speed and self._lead_lookahead_sec > 0:
                predict_cap = self._last_width * 1.5
                predict_len = min(speed * self._lead_lookahead_sec, predict_cap)
                total_cap = self._last_width * 4
                predict_len = min(predict_len, total_cap)
                length = math.hypot(dx, dy)
                if length > 0.001:
                    lead_x += dx / length * predict_len
                    lead_y += dy / length * predict_len
        return PenSample(lead_x, lead_y, last.pressure, last.time)

    def _append_dual_ink_point(self, pos, *, pressure=None, force=False):
        raw = QPointF(pos)
        last_raw = self._last_raw_point
        if last_raw is not None:
            d = math.hypot(raw.x() - last_raw.x(), raw.y() - last_raw.y())
            min_d = self._dual_ink_min_distance()
            if d < 0.001:
                return
            if force and d < min_d:
                return
        now = time.perf_counter()
        filtered = self.one_euro(raw, now)
        self._last_raw_point = QPointF(raw)
        self._last_filtered_point = QPointF(filtered)
        self._last_raw_pos = QPointF(raw)
        sample = self._make_pen_sample_at(filtered, pressure, now)
        if self._stroke_points_buffer:
            last_buf = self._stroke_points_buffer[-1]
            if math.hypot(sample.x - last_buf.x, sample.y - last_buf.y) <= 0.001:
                self._stroke_points_buffer[-1] = sample
                self._sync_dual_ink_wet_outline(sample, replace_last=True)
                self._last_pressure = pressure
                return
        self._stroke_points_buffer.append(sample)
        self._sync_dual_ink_wet_outline(sample, replace_last=False)
        self._last_pressure = pressure
        if self.is_round_pen_freehand():
            self._last_width = self._round_width(sample.pressure, self._active_round_pen_profile())
        elif self.is_calligraphy_freehand():
            self._last_width = self._active_calligraphy_profile().broad_width
        else:
            self._last_width = self._stroke_width(pressure, 0)

    @staticmethod
    def _sample_distance(a, b):
        return math.hypot(a.x - b.x, a.y - b.y)

    def _simplify_samples_by_distance(self, samples, min_distance):
        if len(samples) <= 2:
            return list(samples)
        min_distance = max(0, float(min_distance))
        out = [samples[0]]
        for sample in samples[1:-1]:
            if self._sample_distance(out[-1], sample) >= min_distance:
                out.append(sample)
        if self._sample_distance(out[-1], samples[-1]) > 0.001:
            out.append(samples[-1])
        else:
            out[-1] = samples[-1]
        return out

    def _virtual_endpoint(self, anchor, neighbor):
        return PenSample(
            anchor.x + (anchor.x - neighbor.x),
            anchor.y + (anchor.y - neighbor.y),
            anchor.pressure,
            anchor.time,
        )

    def _centripetal_catmull_rom_samples(self, samples: list[PenSample], spacing: float) -> list[PenSample]:
        if len(samples) < 3:
            return list(samples)
        spacing = max(0.55, float(spacing))
        out = [samples[0]]

        def _tj(ti: float, a: PenSample, b: PenSample) -> float:
            return ti + max(0.001, self._sample_distance(a, b)) ** 0.5

        def _blend(a: tuple[float, float], b: tuple[float, float], ta: float, tb: float, t: float) -> tuple[float, float]:
            denom = tb - ta
            if abs(denom) <= 1e-06:
                return b
            wa = (tb - t) / denom
            wb = (t - ta) / denom
            return (a[0] * wa + b[0] * wb, a[1] * wa + b[1] * wb)

        for i in range(len(samples) - 1):
            p1 = samples[i]
            p2 = samples[i + 1]
            p0 = samples[i - 1] if i > 0 else self._virtual_endpoint(p1, p2)
            p3 = samples[i + 2] if i + 2 < len(samples) else self._virtual_endpoint(p2, p1)
            t0 = 0.0
            t1 = _tj(t0, p0, p1)
            t2 = _tj(t1, p1, p2)
            t3 = _tj(t2, p2, p3)
            seg_len = self._sample_distance(p1, p2)
            steps = max(2, min(24, int(math.ceil(seg_len / spacing))))
            for step in range(1, steps + 1):
                u = step / steps
                t = t1 + (t2 - t1) * u
                a1 = _blend((p0.x, p0.y), (p1.x, p1.y), t0, t1, t)
                a2 = _blend((p1.x, p1.y), (p2.x, p2.y), t1, t2, t)
                a3 = _blend((p2.x, p2.y), (p3.x, p3.y), t2, t3, t)
                b1 = _blend(a1, a2, t0, t2, t)
                b2 = _blend(a2, a3, t1, t3, t)
                x, y = _blend(b1, b2, t1, t2, t)
                out.append(
                    PenSample(
                        x,
                        y,
                        p1.pressure + (p2.pressure - p1.pressure) * u,
                        p1.time + (p2.time - p1.time) * u,
                    )
                )
        return out

    def _prepare_dry_ink_samples(self, samples, spacing):
        simplified = self._simplify_samples_by_distance(samples, min_distance=0.35)
        return self._centripetal_catmull_rom_samples(simplified, spacing=max(0.55, spacing))

    def _clear_dual_ink_stroke(self):
        self._stroke_points_buffer = []
        self._last_raw_point = None
        self._last_filtered_point = None
        self.one_euro.reset()
        self._raw_samples = []
        self._round_samples = []
        self._reset_wet_outline()
        self._reset_round_wet_outline()
        self._path = QPainterPath()
        self._segments = []

    def _finish_dual_ink_stroke(self, pos, pressure=None):
        if not self._stroke_points_buffer:
            self._start_dual_ink_stroke(pos, pressure)
        total_distance = self._dist(self._stroke_start, pos)
        if total_distance < 1.0 and len(self._stroke_points_buffer) <= 1:
            sample = self._make_pen_sample(pos, pressure)
            if self.is_calligraphy_freehand():
                self._raw_samples.append(sample)
                outline = self._build_calligraphy_tap_outline(sample, self._active_calligraphy_profile())
                self._committed_outline = outline
                path = QPainterPath()
                path.moveTo(pos)
                path.lineTo(QPointF(pos.x() + 0.01, pos.y() + 0.01))
                self._segments = [StrokeSegment(path, self._active_calligraphy_profile().broad_width)]
            elif self.is_round_pen_freehand():
                self._round_samples.append(sample)
                outline = self._build_round_tap_outline(sample, self._active_round_pen_profile())
                self._committed_outline = outline
                path = QPainterPath()
                path.moveTo(pos)
                path.lineTo(QPointF(pos.x() + 0.01, pos.y() + 0.01))
                self._segments = [StrokeSegment(path, self._last_width)]
            self._stroke_points_buffer = []
            self._path = QPainterPath()
            return
        if self.is_calligraphy_freehand():
            spacing = self._active_calligraphy_profile().spacing
            prepared = self._prepare_dry_ink_samples(self._raw_samples, spacing)
            outline = self._build_calligraphy_outline(prepared, self._active_calligraphy_profile())
            self._committed_outline = outline
            self._raw_samples = prepared
        elif self.is_round_pen_freehand():
            spacing = self._active_round_pen_profile().spacing
            prepared = self._prepare_dry_ink_samples(self._round_samples, spacing)
            outline = self._build_round_pen_outline(prepared, self._active_round_pen_profile())
            self._committed_outline = outline
            self._round_samples = prepared
        self._stroke_points_buffer = []
        self._wet_outline = None
        self._round_wet_outline = None

    # ------------------------------------------------------------------
    #  Calligraphy sample & outline
    # ------------------------------------------------------------------

    def _append_calligraphy_sample(self, pos, *, pressure=None, force=False):
        sample = self._make_pen_sample(pos, pressure)
        if self._raw_samples:
            last = self._raw_samples[-1]
            distance = math.hypot(sample.x - last.x, sample.y - last.y)
            if distance <= 0.001:
                self._raw_samples[-1] = sample
                self._last_pressure = pressure
                self._rebuild_wet_outline()
                return
            min_distance = max(0.25, self._active_calligraphy_profile().spacing * 0.3)
            if force and distance < min_distance:
                return
            if not self._freehand_moved:
                self._freehand_moved = self._dist(self._stroke_start, QPointF(sample.x, sample.y)) >= min_distance
        self._raw_samples.append(sample)
        self._last_pressure = pressure
        self._rebuild_wet_outline()

    def _reset_wet_outline(self):
        self._wet_outline = None
        self._wet_prefix_path = QPainterPath()
        self._wet_prefix_path.setFillRule(Qt.FillRule.WindingFill)
        self._wet_prefix_bounds = QRectF()
        self._wet_frozen_index = 0

    def _union_bounds(self, a, b):
        if a.isNull():
            return QRectF(b)
        if b.isNull():
            return QRectF(a)
        return a.united(b)

    def _rebuild_wet_outline(self, lead=None):
        if not self.is_calligraphy_freehand() or not self._raw_samples:
            self._wet_outline = None
            return
        profile = self._active_calligraphy_profile()
        wet_profile = self._calligraphy_profile_with(profile, spacing=0.75, smoothing=0.58)
        total = len(self._raw_samples)
        freeze_to = max(0, total - self._wet_sample_tail)
        if freeze_to > self._wet_frozen_index:
            self._wet_frozen_index = freeze_to
            self._wet_prefix_path = QPainterPath()
            self._wet_prefix_path.setFillRule(Qt.FillRule.WindingFill)
            self._wet_prefix_bounds = QRectF()
            chunk_start = 0
            chunk_end = freeze_to
            if chunk_end > chunk_start:
                tail_samples = self._raw_samples[chunk_start:chunk_end]
                prepared = self._prepare_dry_ink_samples(tail_samples, wet_profile.spacing)
                outline = self._build_calligraphy_outline(prepared, wet_profile)
                if outline:
                    self._wet_prefix_path = outline.path
                    self._wet_prefix_bounds = outline.bounds
        wet_samples = self._raw_samples[max(self._wet_frozen_index, 0):]
        if lead is not None:
            wet_samples = wet_samples + [lead]
        if len(wet_samples) < 2:
            tail_outline = None
            if wet_samples:
                tail_outline = self._build_calligraphy_tap_outline(wet_samples[0], wet_profile)
            combined = self._wet_prefix_path
            combined_bounds = self._wet_prefix_bounds
            if tail_outline:
                combined = QPainterPath(combined)
                combined.addPath(tail_outline.path)
                combined_bounds = self._union_bounds(combined_bounds, tail_outline.bounds)
            self._wet_outline = InkOutline(combined, combined_bounds) if not combined.isEmpty() else None
            return
        prepared = self._prepare_dry_ink_samples(wet_samples, wet_profile.spacing)
        tail_outline = self._build_calligraphy_outline(prepared, wet_profile)
        combined = QPainterPath(self._wet_prefix_path)
        combined_bounds = QRectF(self._wet_prefix_bounds)
        if tail_outline and not tail_outline.path.isEmpty():
            combined.addPath(tail_outline.path)
            combined_bounds = self._union_bounds(combined_bounds, tail_outline.bounds)
        self._wet_outline = InkOutline(combined, combined_bounds) if not combined.isEmpty() else None

    def _resample_samples(self, samples, spacing):
        if len(samples) < 2:
            return list(samples)
        spacing = max(0.35, float(spacing))
        out = [samples[0]]
        distance_from_last = 0
        for idx in range(1, len(samples)):
            sx = samples[idx - 1].x
            sy = samples[idx - 1].y
            sp = samples[idx - 1].pressure
            st = samples[idx - 1].time
            ex = samples[idx].x
            ey = samples[idx].y
            ep = samples[idx].pressure
            et = samples[idx].time
            seg_len = math.hypot(ex - sx, ey - sy)
            if seg_len <= 0.001:
                continue
            while distance_from_last + seg_len >= spacing:
                ratio = (spacing - distance_from_last) / seg_len
                nx = sx + (ex - sx) * ratio
                ny = sy + (ey - sy) * ratio
                np = sp + (ep - sp) * ratio
                nt = st + (et - st) * ratio
                point = PenSample(nx, ny, np, nt)
                out.append(point)
                sx, sy, sp, st = nx, ny, np, nt
                seg_len = math.hypot(ex - sx, ey - sy)
                distance_from_last = 0
                if seg_len <= 0.001:
                    break
            distance_from_last += seg_len
        last = samples[-1]
        if math.hypot(out[-1].x - last.x, out[-1].y - last.y) > spacing * 0.35:
            out.append(last)
        return out

    def _smooth_samples(self, samples, smoothing):
        if len(samples) < 3:
            return list(samples)
        alpha = self._clamp(float(smoothing), 0, 1)
        smoothed = [samples[0]]
        for sample in samples[1:-1]:
            prev = smoothed[-1]
            smoothed.append(PenSample(
                prev.x * (1 - alpha) + sample.x * alpha,
                prev.y * (1 - alpha) + sample.y * alpha,
                sample.pressure,
                sample.time,
            ))
        smoothed.append(samples[-1])
        backward = [smoothed[-1]]
        for sample in reversed(smoothed[1:-1]):
            prev = backward[-1]
            backward.append(PenSample(
                prev.x * (1 - alpha) + sample.x * alpha,
                prev.y * (1 - alpha) + sample.y * alpha,
                sample.pressure,
                sample.time,
            ))
        backward.append(smoothed[0])
        backward.reverse()
        return backward

    def _calligraphy_width(self, theta, pressure, profile):
        delta = theta - math.radians(profile.angle_deg)
        direction_factor = abs(math.sin(delta))
        width = profile.thin_width + (profile.broad_width - profile.thin_width) * direction_factor
        width *= 1 + profile.pressure_gain * (self._clamp(pressure, 0.05, 1) - 0.5)
        return self._clamp(width, max(0.25, profile.thin_width * 0.65), profile.broad_width * 1.18)

    def _build_calligraphy_tap_outline(self, sample, profile):
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        broad = max(1, profile.broad_width * 0.55)
        thin = max(0.7, profile.thin_width * 0.65)
        local = QPainterPath()
        local.addEllipse(QRectF(-broad, -thin, broad * 2, thin * 2))
        transform = QTransform()
        transform.translate(sample.x, sample.y)
        transform.rotate(profile.angle_deg)
        path.addPath(transform.map(local))
        return InkOutline(path, path.boundingRect())

    def _chaikin_curve(self, samples, passes):
        '''Bo tròn góc gãy của input thưa bằng Chaikin corner cutting.'''
        if len(samples) < 3:
            return list(samples)
        smoothed = list(samples)
        for _ in range(max(0, int(passes))):
            out = [smoothed[0]]
            for i in range(len(smoothed) - 1):
                p0 = smoothed[i]
                p1 = smoothed[i + 1]
                if math.hypot(p1.x - p0.x, p1.y - p0.y) < 0.1:
                    out.append(p1)
                    continue
                out.append(PenSample(
                    p0.x * 0.75 + p1.x * 0.25,
                    p0.y * 0.75 + p1.y * 0.25,
                    p0.pressure * 0.75 + p1.pressure * 0.25,
                    p0.time * 0.75 + p1.time * 0.25,
                ))
                out.append(PenSample(
                    p0.x * 0.25 + p1.x * 0.75,
                    p0.y * 0.25 + p1.y * 0.75,
                    p0.pressure * 0.25 + p1.pressure * 0.75,
                    p0.time * 0.25 + p1.time * 0.75,
                ))
            out.append(smoothed[-1])
            smoothed = out
        return smoothed

    def _build_calligraphy_outline(
        self,
        samples: list[PenSample],
        profile: CalligraphyProfile,
        *,
        vector_passes: int = 1,
        width_passes: int = 1,
        cap_steps: int = 8,
        centerline_ready: bool = False,
    ) -> InkOutline | None:
        """
        Dựng viền khép kín của nét bút calligraphy dưới dạng MỘT QPainterPath
        duy nhất:
          • Cạnh trái/phải dùng cubic Bézier có control point bám theo tangent
            của đường trung tâm nét.
          • Mũ đầu/cuối là arc bán nguyệt nối trực tiếp vào cùng subpath.
          • Không làm mượt theo tangent của offset curve, vì cách đó dễ
            overshoot và tự cắt tại góc sắc.

        Control point được rút ngắn về 0 nếu tangent tại điểm không cùng hướng
        đoạn centerline kế tiếp, nhờ vậy cubic không quặp ngược và hạn chế lỗ
        trắng do self-intersection khi fill.
        """
        if not samples:
            return None
        if len(samples) == 1:
            return self._build_calligraphy_tap_outline(samples[0], profile)
        if centerline_ready:
            points = list(samples)
        else:
            curved = self._chaikin_curve(samples, passes=2)
            points = self._smooth_samples(
                self._resample_samples(curved, profile.spacing),
                profile.smoothing,
            )
        if len(points) < 2:
            return self._build_calligraphy_tap_outline(samples[-1], profile)
        n = len(points)
        raw_dx = []
        raw_dy = []
        for i in range(n):
            prev_p = points[max(0, i - 1)]
            next_p = points[min(n - 1, i + 1)]
            raw_dx.append(next_p.x - prev_p.x)
            raw_dy.append(next_p.y - prev_p.y)
        sdx = raw_dx[:]
        sdy = raw_dy[:]
        for _ in range(max(1, int(vector_passes))):
            pdx = sdx[:]
            pdy = sdy[:]
            for i in range(1, n - 1):
                sdx[i] = pdx[i - 1] * 0.25 + pdx[i] * 0.5 + pdx[i + 1] * 0.25
                sdy[i] = pdy[i - 1] * 0.25 + pdy[i] * 0.5 + pdy[i + 1] * 0.25
        widths = []
        tangents = []
        normals = []
        thetas = []
        for i, s in enumerate(points):
            dx = sdx[i]
            dy = sdy[i]
            ln = math.hypot(dx, dy)
            if ln > 0.001:
                theta = math.atan2(dy, dx)
                tx = dx / ln
                ty = dy / ln
                nx = -ty
                ny = tx
            else:
                theta = thetas[-1] if thetas else 0.0
                tx, ty = tangents[-1] if tangents else (1.0, 0.0)
                nx, ny = normals[-1] if normals else (0.0, 1.0)
            thetas.append(theta)
            tangents.append((tx, ty))
            widths.append(self._calligraphy_width(theta, s.pressure, profile))
            normals.append((nx, ny))

        sw = widths[:]
        for _ in range(max(1, int(width_passes))):
            pw = sw[:]
            for i in range(1, n - 1):
                sw[i] = pw[i - 1] * 0.25 + pw[i] * 0.5 + pw[i + 1] * 0.25
        widths = sw

        left = []
        right = []
        for i, s in enumerate(points):
            nx, ny = normals[i]
            r = widths[i] * 0.5
            left.append((s.x + nx * r, s.y + ny * r))
            right.append((s.x - nx * r, s.y - ny * r))

        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)

        def _center_seg_unit(i: int) -> tuple[float, float, float]:
            a = points[i]
            b = points[i + 1]
            dx = b.x - a.x
            dy = b.y - a.y
            ln = math.hypot(dx, dy)
            if ln <= 0.001:
                return (1.0, 0.0, 0.0)
            return (dx / ln, dy / ln, ln)

        def _aligned_handle(tangent: tuple[float, float], seg_unit: tuple[float, float], seg_len: float) -> float:
            alignment = max(0.0, tangent[0] * seg_unit[0] + tangent[1] * seg_unit[1])
            return seg_len * 0.34 * alignment

        def _cubic_forward(edge: list[tuple[float, float]], *, start_index: int, end_index: int, direction: int) -> None:
            i = start_index
            while i != end_index:
                j = i + direction
                sux, suy, seg_len = _center_seg_unit(min(i, j))
                if direction < 0:
                    sux = -sux
                    suy = -suy
                x1, y1 = edge[i]
                x2, y2 = edge[j]
                t1x, t1y = tangents[i]
                t2x, t2y = tangents[j]
                if direction < 0:
                    t1x = -t1x
                    t1y = -t1y
                    t2x = -t2x
                    t2y = -t2y
                h1 = _aligned_handle((t1x, t1y), (sux, suy), seg_len)
                h2 = _aligned_handle((t2x, t2y), (sux, suy), seg_len)
                path.cubicTo(
                    x1 + t1x * h1,
                    y1 + t1y * h1,
                    x2 - t2x * h2,
                    y2 - t2y * h2,
                    x2,
                    y2,
                )
                i = j

        def _arc_cap(cx: float, cy: float, r: float, start_angle: float, sweep: float) -> None:
            steps = max(3, int(cap_steps))
            for k in range(1, steps + 1):
                a = start_angle + sweep * (k / steps)
                path.lineTo(cx + math.cos(a) * r, cy + math.sin(a) * r)

        path.moveTo(left[0][0], left[0][1])
        _cubic_forward(left, start_index=0, end_index=n - 1, direction=1)
        _arc_cap(points[-1].x, points[-1].y, widths[-1] * 0.5, thetas[-1] + math.pi / 2, -math.pi)
        _cubic_forward(right, start_index=n - 1, end_index=0, direction=-1)
        _arc_cap(points[0].x, points[0].y, widths[0] * 0.5, thetas[0] - math.pi / 2, -math.pi)
        path.closeSubpath()

        if path.isEmpty():
            return None
        return InkOutline(path, path.boundingRect())

    # ------------------------------------------------------------------
    #  Tap path helper
    # ------------------------------------------------------------------

    def _make_tap_path(self, pos):
        eps = max(0.01, float(self.pen_width) * 0.015)
        p = QPainterPath()
        p.moveTo(pos)
        p.lineTo(QPointF(pos.x() + eps, pos.y() + eps))
        return p

    # ------------------------------------------------------------------
    #  Freehand append
    # ------------------------------------------------------------------

    def _append_freehand_point(self, pos, *, pressure=None, force=False):
        raw_distance = self._dist(self._last_raw_pos, pos)
        min_distance = self._effective_min_distance()
        if force and raw_distance < min_distance:
            return
        if not self._freehand_moved:
            self._freehand_moved = self._dist(self._stroke_start, pos) >= min_distance
        alpha = self._adaptive_alpha(raw_distance)
        filtered = self._lerp(self._smooth_anchor, pos, alpha)
        mid = self._midpoint(self._smooth_anchor, filtered)
        new_width = self._stroke_width(pressure, raw_distance)
        seg_width = (self._last_width + new_width) * 0.5
        seg_path = QPainterPath()
        seg_path.moveTo(self._path_current_pos)
        seg_path.quadTo(self._smooth_anchor, mid)
        self._segments.append(StrokeSegment(seg_path, seg_width))
        self._path.quadTo(self._smooth_anchor, mid)
        self._path_current_pos = mid
        self._smooth_anchor = filtered
        self._last_raw_pos = pos
        self._last_pressure = pressure
        self._last_width = new_width

    def _append_tail_to_anchor(self):
        if self._dist(self._path_current_pos, self._smooth_anchor) <= 0.01:
            return
        tail = QPainterPath()
        tail.moveTo(self._path_current_pos)
        tail.lineTo(self._smooth_anchor)
        self._segments.append(StrokeSegment(tail, self._last_width))
        self._path.lineTo(self._smooth_anchor)
        self._path_current_pos = self._smooth_anchor

    # ------------------------------------------------------------------
    #  Arrow / cap / diamond / dot helpers
    # ------------------------------------------------------------------

    def _add_arrow_head(self, p, tip, tail_ref, style='open'):
        dx = tip.x() - tail_ref.x()
        dy = tip.y() - tail_ref.y()
        length = math.hypot(dx, dy)
        if length <= 0.5:
            return
        angle = math.atan2(dy, dx)
        head_len = max(10, min(32, float(self.get_active_width()) * 5))
        spread = math.radians(28)
        a1 = angle + math.pi - spread
        a2 = angle + math.pi + spread
        h1 = QPointF(tip.x() + math.cos(a1) * head_len, tip.y() + math.sin(a1) * head_len)
        h2 = QPointF(tip.x() + math.cos(a2) * head_len, tip.y() + math.sin(a2) * head_len)
        if style == 'closed':
            poly = QPolygonF([tip, h1, h2, tip])
            p.addPolygon(poly)
            return
        if style == 'stealth':
            inward_len = head_len * 0.6
            inward_pt = QPointF(
                tip.x() + math.cos(angle) * inward_len,
                tip.y() + math.sin(angle) * inward_len,
            )
            poly = QPolygonF([tip, h1, inward_pt, h2, tip])
            p.addPolygon(poly)
            return
        p.moveTo(tip)
        p.lineTo(h1)
        p.moveTo(tip)
        p.lineTo(h2)

    def _add_cap(self, p, tip, tail_ref):
        dx = tip.x() - tail_ref.x()
        dy = tip.y() - tail_ref.y()
        length = math.hypot(dx, dy)
        if length <= 0.5:
            return
        angle = math.atan2(dy, dx)
        cap_len = max(8, float(self.get_active_width()) * 3)
        nx = -math.sin(angle)
        ny = math.cos(angle)
        p.moveTo(tip.x() + nx * cap_len, tip.y() + ny * cap_len)
        p.lineTo(tip.x() - nx * cap_len, tip.y() - ny * cap_len)

    def _add_diamond(self, p, tip, tail_ref):
        dx = tip.x() - tail_ref.x()
        dy = tip.y() - tail_ref.y()
        length = math.hypot(dx, dy)
        if length <= 0.5:
            return
        angle = math.atan2(dy, dx)
        head_len = max(12, min(36, float(self.get_active_width()) * 6))
        half_w = head_len * 0.4
        back = QPointF(tip.x() - math.cos(angle) * head_len, tip.y() - math.sin(angle) * head_len)
        mid = QPointF(tip.x() - math.cos(angle) * (head_len / 2), tip.y() - math.sin(angle) * (head_len / 2))
        nx = -math.sin(angle)
        ny = math.cos(angle)
        left = QPointF(mid.x() + nx * half_w, mid.y() + ny * half_w)
        right = QPointF(mid.x() - nx * half_w, mid.y() - ny * half_w)
        poly = QPolygonF([tip, left, back, right, tip])
        p.addPolygon(poly)

    def _add_dot(self, p, tip):
        r = max(4, float(self.get_active_width()) * 1.5)
        p.addEllipse(QRectF(tip.x() - r, tip.y() - r, r * 2, r * 2))

    # ------------------------------------------------------------------
    #  Shape paths
    # ------------------------------------------------------------------

    def _shape_path(self, mode=None):
        '''Tạo path preview/commit cho các hình học cơ bản.'''
        if not mode:
            mode = self.mode
        p = QPainterPath()
        if mode == DrawMode.LINE:
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            return p
        if mode == DrawMode.CUSTOM_LINE:
            return self._invoke_custom_build_path([self.p0, self.p3])
        if mode == DrawMode.ARROW:
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            self._add_arrow_head(p, self.p3, self.p0, style='open')
            return p
        if mode == DrawMode.ARROW_DOUBLE:
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            self._add_arrow_head(p, self.p3, self.p0, style='open')
            self._add_arrow_head(p, self.p0, self.p3, style='open')
            return p
        if mode == DrawMode.ARROW_CLOSED:
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            self._add_arrow_head(p, self.p3, self.p0, style='closed')
            return p
        if mode == DrawMode.ARROW_DOUBLE_CLOSED:
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            self._add_arrow_head(p, self.p3, self.p0, style='closed')
            self._add_arrow_head(p, self.p0, self.p3, style='closed')
            return p
        if mode == DrawMode.ARROW_STEALTH:
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            self._add_arrow_head(p, self.p3, self.p0, style='stealth')
            return p
        if mode == DrawMode.ARROW_DOUBLE_STEALTH:
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            self._add_arrow_head(p, self.p3, self.p0, style='stealth')
            self._add_arrow_head(p, self.p0, self.p3, style='stealth')
            return p
        if mode == DrawMode.LINE_DIMENSION:
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            self._add_cap(p, self.p0, self.p3)
            self._add_cap(p, self.p3, self.p0)
            return p
        if mode == DrawMode.LINE_BRACE:
            return _build_flat_brace_connector([self.p0, self.p3])
        if mode == DrawMode.LINE_DIAMOND:
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            self._add_diamond(p, self.p3, self.p0)
            self._add_diamond(p, self.p0, self.p3)
            return p
        if mode == DrawMode.LINE_DOT:
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            self._add_dot(p, self.p0)
            self._add_dot(p, self.p3)
            return p
        if mode == DrawMode.CIRCLE:
            r = self._dist(self.p0, self.p3)
            rect = QRectF(self.p0.x() - r, self.p0.y() - r, r * 2, r * 2)
            p.addEllipse(rect)
            return p
        if mode == DrawMode.SEMICIRCLE:
            r = self._dist(self.p0, self.p3)
            rect = QRectF(self.p0.x() - r, self.p0.y() - r, r * 2, r * 2)
            start = self._screen_angle_deg(self.p0, self.p3) - 90
            p.arcMoveTo(rect, start)
            p.arcTo(rect, start, 180)
            return p
        if mode in (DrawMode.ELLIPSE, DrawMode.HALF_ELLIPSE):
            return self._ellipse_path(mode)
        if mode == DrawMode.BEZIER:
            p.moveTo(self.p0)
            p.cubicTo(self.p1, self.p2, self.p3)
            return p
        if mode == DrawMode.PARABOLA:
            return self._parabola_path()
        if mode == DrawMode.RECTANGLE or mode == DrawMode.TRIANGLE or mode == DrawMode.PARALLELOGRAM:
            return self._polygon_path(mode)
        if mode in (DrawMode.CUSTOM_CURVE, DrawMode.CUSTOM_POLYGON, DrawMode.CUSTOM_FREE):
            return self._invoke_custom_build_path(self.custom_points)
        if mode == DrawMode.CUSTOM_GEOMETRY:
            return self._invoke_custom_build_path(self.custom_points)
        return p

    def _polygon_path(self, mode=None):
        p2 = self.p2 if self.polygon_step == 0 else self.cursor_pos
        p = QPainterPath()
        dx = self.p3.x() - self.p0.x()
        dy = self.p3.y() - self.p0.y()
        length = math.hypot(dx, dy)
        if length < 0.5:
            return p
        if mode == DrawMode.TRIANGLE:
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            p.lineTo(p2)
            p.closeSubpath()
            return p
        if mode == DrawMode.RECTANGLE:
            nx = -dy / length
            ny = dx / length
            h = (p2.x() - self.p3.x()) * nx + (p2.y() - self.p3.y()) * ny
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            p.lineTo(QPointF(self.p3.x() + h * nx, self.p3.y() + h * ny))
            p.lineTo(QPointF(self.p0.x() + h * nx, self.p0.y() + h * ny))
            p.closeSubpath()
            return p
        if mode == DrawMode.PARALLELOGRAM:
            dx2 = p2.x() - self.p3.x()
            dy2 = p2.y() - self.p3.y()
            p.moveTo(self.p0)
            p.lineTo(self.p3)
            p.lineTo(p2)
            p.lineTo(QPointF(self.p0.x() + dx2, self.p0.y() + dy2))
            p.closeSubpath()
            return p
        return p

    # ------------------------------------------------------------------
    #  Custom tool dispatch
    # ------------------------------------------------------------------

    def _current_custom_tool_entry(self):
        name = self.current_custom_tool
        if not name:
            return None
        entry = self.custom_tools.get(name)
        if entry is not None:
            return entry
        entry = self.geometry_tools.get(name)
        if entry is not None:
            return entry
        return self.free_tools.get(name)

    def _custom_n_points(self):
        '''Trả về K điểm cần thiết; -1 nghĩa là nhập tự do, 0 nếu không có.'''
        tool = self._current_custom_tool_entry()
        if not tool:
            return 0
        try:
            n = int(tool.get('n_points', 0))
            if n == -1:
                return -1
            return max(0, min(10, n))
        except (TypeError, ValueError):
            return 0

    def _custom_min_points(self):
        tool = self._current_custom_tool_entry()
        if not tool:
            return 2
        try:
            value = int(tool.get('min_points', 2))
            return max(1, min(10, value))
        except (TypeError, ValueError):
            return 2

    def _invoke_custom_build_path(self, points):
        '''Gọi hàm `build_path(points)` của công cụ AI đang active.'''
        name = self.current_custom_tool
        if not name:
            return QPainterPath()
        tool = self._current_custom_tool_entry()
        if not tool:
            return QPainterPath()
        fn = tool.get('fn')
        if not callable(fn):
            return QPainterPath()
        if len(points) < 2:
            return QPainterPath()
        closed = self.free_close_enabled
        try:
            result = fn(points, closed=closed)
        except TypeError:
            result = fn(points)
        if isinstance(result, QPainterPath):
            return result
        return QPainterPath()

    def _apply_free_close_preference(self, path, points):
        '''Áp dụng tùy chọn nối điểm đầu-cuối cho nhóm công cụ tự do.'''
        if path.isEmpty() or len(points) < 3:
            return path
        if self.free_close_enabled:
            return self._ensure_path_returns_to_start(path)
        return self._remove_terminal_return_to_start(path)

    def _ensure_path_returns_to_start(self, path):
        if path.elementCount() <= 1:
            return path
        start = path.elementAt(0)
        current = path.currentPosition()
        if abs(current.x() - start.x) <= 0.01 and abs(current.y() - start.y) <= 0.01:
            return path
        out = QPainterPath(path)
        out.lineTo(QPointF(start.x, start.y))
        return out

    def _remove_terminal_return_to_start(self, path):
        n = path.elementCount()
        if n <= 2:
            return path
        first = path.elementAt(0)
        last = path.elementAt(n - 1)
        if first.type != QPainterPath.ElementType.MoveToElement:
            return path
        if last.type != QPainterPath.ElementType.LineToElement:
            return path
        if abs(last.x - first.x) > 0.01 or abs(last.y - first.y) > 0.01:
            return path
        out = QPainterPath()
        i = 0
        limit = n - 1
        while i < limit:
            elem = path.elementAt(i)
            if elem.type == QPainterPath.ElementType.MoveToElement:
                out.moveTo(QPointF(elem.x, elem.y))
                i += 1
            elif elem.type == QPainterPath.ElementType.LineToElement:
                out.lineTo(QPointF(elem.x, elem.y))
                i += 1
            elif elem.type == QPainterPath.ElementType.CurveToElement:
                if i + 2 >= limit:
                    return out
                c2 = path.elementAt(i + 1)
                end = path.elementAt(i + 2)
                out.cubicTo(QPointF(elem.x, elem.y), QPointF(c2.x, c2.y), QPointF(end.x, end.y))
                i += 3
            else:
                i += 1
        return out

    def finish_variable_custom_tool(self):
        '''Commit tool N_POINTS=-1 bằng danh sách điểm đã click, không lấy điểm chuột phải.'''
        if self._custom_n_points() != -1:
            return (False, None)
        if len(self.custom_points) < self._custom_min_points():
            self.custom_points = []
            self.is_dragging = False
            return (False, None)
        path = self._invoke_custom_build_path(self.custom_points)
        path = self._apply_free_close_preference(path, self.custom_points)
        points = list(self.custom_points)
        self.custom_points = []
        self.is_dragging = False
        self.p0 = points[0] if points else QPointF()
        self.p3 = points[-1] if points else QPointF()
        return (True, {'path': path, 'points': points})

    # ------------------------------------------------------------------
    #  Pending / cancel
    # ------------------------------------------------------------------

    def has_pending_operation(self):
        '''True nếu đang có thao tác vẽ chưa commit xuống slide.'''
        if self.is_dragging:
            return True
        if self.bezier_step > 0:
            return True
        if self.ellipse_step > 0:
            return True
        if self.parabola_step > 0:
            return True
        if self.polygon_step > 0:
            return True
        if bool(self.custom_points):
            return True
        if not self._path.isEmpty():
            return True
        if bool(self._segments):
            return True
        if bool(self._stroke_points_buffer):
            return True
        if bool(self._raw_samples):
            return True
        if bool(self._round_samples):
            return True
        if self._wet_outline is not None:
            return True
        if self._round_wet_outline is not None:
            return True
        return False

    def cancel_pending_operation(self):
        '''Hủy thao tác đang nhập dở, giữ nguyên mode và thuộc tính công cụ.'''
        if not self.has_pending_operation():
            return False
        self.is_dragging = False
        self.cursor_pos = QPointF(-9999, -9999)
        self.bezier_step = 0
        self.ellipse_step = 0
        self.parabola_step = 0
        self.polygon_step = 0
        self.custom_points = []
        self._path = QPainterPath()
        self._segments = []
        self._stroke_points_buffer = []
        self._last_raw_point = None
        self._last_filtered_point = None
        self.one_euro.reset()
        self._committed_segments = []
        self._committed_outline = None
        self._raw_samples = []
        self._round_samples = []
        self._reset_wet_outline()
        self._reset_round_wet_outline()
        return True

    # ------------------------------------------------------------------
    #  Parabola / Ellipse paths
    # ------------------------------------------------------------------

    def _parabola_path(self):
        p2 = self.p2 if self.parabola_step == 0 else self.cursor_pos
        p = QPainterPath()
        dx = self.p3.x() - self.p0.x()
        dy = self.p3.y() - self.p0.y()
        length = math.hypot(dx, dy)
        if length < 0.5:
            return p
        mx = (self.p0.x() + self.p3.x()) / 2
        my = (self.p0.y() + self.p3.y()) / 2
        nx = -dy / length
        ny = dx / length
        dot = (p2.x() - mx) * nx + (p2.y() - my) * ny
        vx = mx + dot * nx
        vy = my + dot * ny
        cx = 2 * vx - mx
        cy = 2 * vy - my
        p.moveTo(self.p0)
        p.quadTo(QPointF(cx, cy), self.p3)
        return p

    def _ellipse_path(self, mode=None):
        '''
        Ellipse / half-ellipse xoay được từ 3 điểm:
          p0, p3 = 2 đầu mút trục chính (major axis)
          p2     = điểm xác định bán-trục phụ (minor semi-axis)
                   khoảng cách vuông góc từ p2 đến đường p0-p3 = b
        '''
        p2 = self.p2 if self.ellipse_step == 0 else self.cursor_pos
        p = QPainterPath()
        a = self._dist(self.p0, self.p3) / 2
        if a < 0.5:
            return p
        dx = self.p3.x() - self.p0.x()
        dy = self.p3.y() - self.p0.y()
        line_len = 2 * a
        signed_b = (dy * (p2.x() - self.p0.x()) - dx * (p2.y() - self.p0.y())) / line_len
        b = abs(signed_b)
        b = max(b, 0.5)
        cx = (self.p0.x() + self.p3.x()) / 2
        cy = (self.p0.y() + self.p3.y()) / 2
        angle_deg = math.degrees(math.atan2(dy, dx))
        t = QTransform()
        t.translate(cx, cy)
        t.rotate(angle_deg)
        local_rect = QRectF(-a, -b, 2 * a, 2 * b)
        if mode == DrawMode.ELLIPSE:
            local_path = QPainterPath()
            local_path.addEllipse(local_rect)
        else:
            local_path = QPainterPath()
            if signed_b >= 0:
                local_path.arcMoveTo(local_rect, 180)
                local_path.arcTo(local_rect, 180, -180)
            else:
                local_path.arcMoveTo(local_rect, 180)
                local_path.arcTo(local_rect, 180, 180)
        return t.map(local_path)

    # ------------------------------------------------------------------
    #  on_press / on_move / on_release
    # ------------------------------------------------------------------

    def on_press(self, pos, pressure=None):
        self.is_dragging = True
        self.cursor_pos = pos
        self._committed_segments = []
        self._committed_outline = None
        self._reset_wet_outline()
        self._reset_round_wet_outline()
        if self.mode in (DrawMode.FREEHAND, DrawMode.HIGHLIGHT):
            self._path = QPainterPath()
            self._path.moveTo(pos)
            self._stroke_start = pos
            self._smooth_anchor = pos
            self._last_raw_pos = pos
            self._last_raw_point = None
            self._last_filtered_point = None
            self._path_current_pos = pos
            self._freehand_points = 0
            self._freehand_moved = False
            self._segments = []
            self._stroke_points_buffer = []
            self._raw_samples = []
            self._round_samples = []
            self._last_pressure = pressure
            if self._uses_dual_ink_freehand():
                self._start_dual_ink_stroke(pos, pressure)
                return
            self._last_width = self._stroke_width(pressure, 0)
            return
        if self.mode in (DrawMode.ELLIPSE, DrawMode.HALF_ELLIPSE):
            if self.ellipse_step == 0:
                self.p0 = pos
                self.p3 = pos
                self.p2 = pos
                return
            self.p2 = pos
            return
        if self.mode == DrawMode.PARABOLA:
            if self.parabola_step == 0:
                self.p0 = pos
                self.p3 = pos
                self.p2 = pos
                return
            self.p2 = pos
            return
        if self.mode == DrawMode.PARALLELOGRAM:
            if self.polygon_step == 0:
                self.p0 = pos
                self.p3 = pos
                return
            if self.polygon_step == 1:
                self.p3 = pos
                return
            self.p2 = pos
            return
        if self._is_polygon_mode() and self.mode != DrawMode.CUSTOM_POLYGON:
            if self.polygon_step == 0:
                self.p0 = pos
                self.p3 = pos
                self.p2 = pos
                return
            self.p2 = pos
            return
        if self.mode in (
            DrawMode.CUSTOM_CURVE, DrawMode.CUSTOM_POLYGON,
            DrawMode.CUSTOM_LINE, DrawMode.CUSTOM_GEOMETRY,
            DrawMode.CUSTOM_FREE,
        ):
            n = self._custom_n_points()
            if n == -1:
                self.custom_points.append(QPointF(pos))
                return
            if n > 0:
                if len(self.custom_points) >= n:
                    self.custom_points = []
                self.custom_points.append(QPointF(pos))
                return
            return
        if self._is_simple_drag_mode():
            self.p0 = pos
            self.p3 = pos
            return
        if self.mode == DrawMode.BEZIER:
            if self.bezier_step == 0:
                self.p0 = pos
                self.p3 = pos
                self.p1 = pos
                self.p2 = pos
                return
            if self.bezier_step == 1:
                self.p1 = pos
                return
            if self.bezier_step == 2:
                self.p2 = pos
                return
            return

    def on_move(self, pos, pressure=None):
        self.cursor_pos = pos
        if not self.is_dragging:
            return
        if self.mode in (DrawMode.FREEHAND, DrawMode.HIGHLIGHT):
            if self._uses_dual_ink_freehand():
                self._append_dual_ink_point(pos, pressure=pressure)
                return
            self._freehand_points += 1
            self._append_freehand_point(pos, pressure=pressure)
            return
        if self.mode in (DrawMode.ELLIPSE, DrawMode.HALF_ELLIPSE):
            if self.ellipse_step == 0:
                self.p3 = pos
                return
            self.p2 = pos
            return
        if self.mode == DrawMode.PARABOLA:
            if self.parabola_step == 0:
                self.p3 = pos
                return
            self.p2 = pos
            return
        if self.mode == DrawMode.PARALLELOGRAM:
            if self.polygon_step == 0:
                self.p3 = pos
                return
            if self.polygon_step == 1:
                self.p3 = pos
                return
            self.p2 = pos
            return
        if self._is_polygon_mode() and self.mode != DrawMode.CUSTOM_POLYGON:
            if self.polygon_step == 0:
                self.p3 = pos
                return
            self.p2 = pos
            return
        if self._is_simple_drag_mode():
            self.p3 = pos
            return
        if self.mode == DrawMode.BEZIER:
            if self.bezier_step == 0:
                self.p3 = pos
                self.p1 = self.p0
                self.p2 = self.p3
                return
            if self.bezier_step == 1:
                self.p1 = pos
                return
            if self.bezier_step == 2:
                self.p2 = pos
                return
            return

    def on_release(self, pos, pressure=None):
        self.cursor_pos = pos
        self.is_dragging = False
        if self.mode == DrawMode.ERASER:
            return (True, None)
        if self.mode in (DrawMode.FREEHAND, DrawMode.HIGHLIGHT):
            if self._uses_dual_ink_freehand():
                self._append_dual_ink_point(pos, pressure=pressure, force=True)
                self._finish_dual_ink_stroke(pos, pressure)
                self._committed_segments = list(self._segments)
                self._segments = []
                self._stroke_points_buffer = []
                self._path = QPainterPath()
                return (True, {
                    'segments': self._committed_segments,
                    'outline': self._committed_outline,
                    'path': self._path,
                })
            self._append_freehand_point(pos, pressure=pressure, force=True)
            self._append_tail_to_anchor()
            self._committed_segments = list(self._segments)
            self._segments = []
            self._path = QPainterPath()
            return (True, {
                'segments': self._committed_segments,
                'path': self._path,
            })
        if self.mode in (DrawMode.ELLIPSE, DrawMode.HALF_ELLIPSE):
            if self.ellipse_step == 0:
                self.ellipse_step = 1
                self.is_dragging = True
                return (False, None)
            self.ellipse_step = 0
            path = self._shape_path()
            return (True, {'path': path})
        if self.mode == DrawMode.PARABOLA:
            if self.parabola_step == 0:
                self.parabola_step = 1
                self.is_dragging = True
                return (False, None)
            self.parabola_step = 0
            path = self._shape_path()
            return (True, {'path': path})
        if self.mode == DrawMode.PARALLELOGRAM:
            if self.polygon_step == 0:
                self.polygon_step = 1
                self.is_dragging = True
                return (False, None)
            if self.polygon_step == 1:
                self.polygon_step = 2
                self.is_dragging = True
                return (False, None)
            self.polygon_step = 0
            path = self._shape_path()
            return (True, {'path': path})
        if self._is_polygon_mode() and self.mode != DrawMode.CUSTOM_POLYGON:
            self.polygon_step = 0
            path = self._shape_path()
            return (True, {'path': path})
        if self.mode in (
            DrawMode.CUSTOM_CURVE, DrawMode.CUSTOM_POLYGON,
            DrawMode.CUSTOM_LINE, DrawMode.CUSTOM_GEOMETRY,
            DrawMode.CUSTOM_FREE,
        ):
            n = self._custom_n_points()
            if n == -1:
                return (False, None)
            if n > 0 and len(self.custom_points) >= n:
                path = self._invoke_custom_build_path(self.custom_points)
                path = self._apply_free_close_preference(path, self.custom_points)
                points = list(self.custom_points)
                self.custom_points = []
                self.p0 = points[0] if points else QPointF()
                self.p3 = points[-1] if points else QPointF()
                return (True, {'path': path, 'points': points})
            return (False, None)
        if self._is_simple_drag_mode():
            path = self._shape_path()
            return (True, {'path': path})
        if self.mode == DrawMode.BEZIER:
            if self.bezier_step == 0:
                self.bezier_step = 1
                self.is_dragging = True
                return (False, None)
            if self.bezier_step == 1:
                self.bezier_step = 2
                self.is_dragging = True
                return (False, None)
            self.bezier_step = 0
            path = self._shape_path()
            return (True, {'path': path})
        return (False, None)

    # ------------------------------------------------------------------
    #  Preview
    # ------------------------------------------------------------------

    def get_preview_path(self):
        if self.mode in (DrawMode.FREEHAND, DrawMode.HIGHLIGHT) and self.is_dragging:
            preview = QPainterPath(self._path)
            if self._freehand_points == 0:
                preview.lineTo(self.cursor_pos)
                return preview
            preview.lineTo(self._smooth_anchor)
            preview.lineTo(self.cursor_pos)
            return preview
        if self.mode == DrawMode.ERASER and self.is_dragging:
            p = QPainterPath()
            r = self.eraser_width / 2
            p.addEllipse(QRectF(self.cursor_pos.x() - r, self.cursor_pos.y() - r, r * 2, r * 2))
            return p
        if self._is_simple_drag_mode() and self.is_dragging:
            return self._shape_path()
        if self.mode == DrawMode.BEZIER and self.is_dragging:
            return self._shape_path()
        if self.mode == DrawMode.PARABOLA and self.is_dragging:
            return self._shape_path()
        if self._is_polygon_mode() and self.is_dragging:
            return self._shape_path()
        if self.mode in (
            DrawMode.CUSTOM_CURVE, DrawMode.CUSTOM_POLYGON,
            DrawMode.CUSTOM_LINE, DrawMode.CUSTOM_GEOMETRY,
            DrawMode.CUSTOM_FREE,
        ) and self.is_dragging:
            n = self._custom_n_points()
            if n == -1:
                if len(self.custom_points) >= 2:
                    path = self._invoke_custom_build_path(self.custom_points)
                    return self._apply_free_close_preference(path, self.custom_points)
                return QPainterPath()
            if n > 0 and len(self.custom_points) >= 1:
                return self._invoke_custom_build_path(self.custom_points)
            return QPainterPath()
        return QPainterPath()
