"""
ui/constants.py
Shared constants for toolbar / menus of MainWindow.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt

from core.drawing_engine import DrawMode

# ── Khmer font detection ─────────────────────────────────────────────
# Preferred Khmer fonts in order of preference
_KHMER_FONT_FAMILIES = [
    'Noto Sans Khmer',
    'Khmer OS Content',
    'Khmer OS Siemreap',
    'Khmer Mondulkiri-s',
    'Khmer Sangam MN',
    'Battambang',
    'Freehand',
    'Moul',
    'Bokor',
    'Dangrek',
    'Preahvihear',
    'Siemreap',
    'Kampuchea',
    'Metal',
    'Champeang',
    'Mondulkiri',
    'Pearl',
    'Tul',
    'Taktic',
    'Panhach',
    'Kantumruey',
    'Khmer',
]

# UI font families (Latin + Khmer fallback) — order matters for macOS
UI_FONT_FAMILIES = [
    'SF Pro Text',
    'Helvetica Neue',
    'Noto Sans Khmer',
    'Khmer OS Content',
    'Arial',
    'sans-serif',
]

# Font family string for CSS/stylesheet
UI_FONT_FAMILY_CSS = ', '.join(f'"{f}"' for f in UI_FONT_FAMILIES)

# ── Drawing modes ─────────────────────────────────────────────────────

LINE_MODES: list[tuple[str, DrawMode, str, str]] = [
    ("Đoạn thẳng", DrawMode.LINE, "line", "Vẽ đoạn thẳng"),
    ("Mũi tên", DrawMode.ARROW_CLOSED, "arrow_closed", "Vẽ mũi tên 1 đầu"),
    (
        "Mũi tên 2 chiều",
        DrawMode.ARROW_DOUBLE_CLOSED,
        "arrow_double_closed",
        "Vẽ mũi tên 2 chiều",
    ),
    (
        "Đoạn thẳng giới hạn",
        DrawMode.LINE_DIMENSION,
        "line_dimension",
        "Đoạn thẳng bị chặn 2 đầu (đo kích thước)",
    ),
    (
        "Ngoặc nhọn",
        DrawMode.LINE_BRACE,
        "brace",
        "Đường nối dạng ngoặc nhọn dẹt",
    ),
]

CURVE_MODES: list[tuple[str, DrawMode, str, str]] = [
    (
        "Đường Bézier",
        DrawMode.BEZIER,
        "bezier",
        "Đường Bézier: chọn điểm đầu-cuối, rồi 2 điểm điều khiển",
    ),
    (
        "Parabol",
        DrawMode.PARABOLA,
        "parabola",
        "Parabol: kéo 2 điểm đối xứng, sau đó chọn đỉnh",
    ),
    (
        "Đường tròn",
        DrawMode.CIRCLE,
        "circle",
        "Đường tròn: nhấn tâm, kéo tới điểm đi qua",
    ),
    (
        "Nửa tròn",
        DrawMode.SEMICIRCLE,
        "semicircle",
        "Nửa tròn: nhấn tâm, kéo tới điểm đi qua trên cung",
    ),
    ("Elip", DrawMode.ELLIPSE, "ellipse", "Elip theo khung kéo"),
    (
        "Nửa elip",
        DrawMode.HALF_ELLIPSE,
        "half_ellipse",
        "Nửa elip theo khung kéo",
    ),
]

POLYGON_MODES: list[tuple[str, DrawMode, str, str]] = [
    (
        "Tam giác",
        DrawMode.TRIANGLE,
        "triangle",
        "Tam giác: kéo điểm 1-2, sau đó chọn điểm 3",
    ),
    (
        "Hình chữ nhật",
        DrawMode.RECTANGLE,
        "rectangle",
        "Hình chữ nhật: kéo cạnh đáy, sau đó kéo độ cao",
    ),
    (
        "Hình bình hành",
        DrawMode.PARALLELOGRAM,
        "parallelogram",
        "Hình bình hành: kéo cạnh 1, sau đó kéo cạnh 2",
    ),
]

STROKE_STYLES: list[tuple[str, Qt.PenStyle, list[float] | None, str]] = [
    ("Liền", Qt.PenStyle.SolidLine, None, "solid"),
    ("Đứt", Qt.PenStyle.DashLine, None, "dash"),
    ("Chấm", Qt.PenStyle.DotLine, None, "dot"),
    ("Gạch-chấm", Qt.PenStyle.DashDotLine, None, "dashdot"),
    ("Gạch-2 chấm", Qt.PenStyle.DashDotDotLine, None, "dashdotdot"),
    ("Đứt ngắn", Qt.PenStyle.CustomDashLine, [4, 4], "short_dash"),
    ("Đứt dài", Qt.PenStyle.CustomDashLine, [14, 6], "long_dash"),
    ("Chấm thưa", Qt.PenStyle.CustomDashLine, [1, 7], "sparse_dot"),
]

FILL_STYLES: list[tuple[str, str]] = [
    ("Tô màu", "solid"),
    ("Kẻ ngang", "horizontal_lines"),
    ("Kẻ dọc", "vertical_lines"),
    ("Kẻ chéo lên", "north_east_lines"),
    ("Kẻ chéo xuống", "north_west_lines"),
    ("Lưới", "grid"),
    ("Gạch chéo đôi", "crosshatch"),
    ("Chấm phủ", "dots"),
    ("Gạch chéo đôi + chấm", "crosshatch_dots"),
    ("Sao 5 cánh", "fivepointed_stars"),
    ("Sao 6 cánh", "sixpointed_stars"),
    ("Gạch", "bricks"),
    ("Ô bàn cờ", "checkerboard"),
]

# ── Stylesheets ───────────────────────────────────────────────────────

MENU_STYLE = (
    "QMenu { background:#1e293b; border:1px solid #334155; border-radius:10px; padding:4px; }"
    "QMenu::item { color:#f1f5f9; padding:6px 8px 6px 8px; border-radius:7px; }"
    "QMenu::item:selected { background:#4f46e5; color:#ffffff; }"
    "QMenu::item:checked { color:#a5b4fc; }"
    "QMenu::icon { padding-left:4px; }"
)

# Global application stylesheet with Khmer font support
APP_STYLE = f"""
/* ── Global ─────────────────────────────────────────────── */
* {{
    font-family: {UI_FONT_FAMILY_CSS};
    font-size: 13px;
}}

/* ── Toolbar ────────────────────────────────────────────── */
QFrame#TopToolbar {{
    background: #ffffff;
    border-bottom: 1px solid #e2e8f0;
    padding: 2px 0px;
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 3px 5px;
    min-width: 26px;
    min-height: 26px;
    max-height: 28px;
}}
QToolButton:hover {{
    background: #f1f5f9;
    border-color: #cbd5e1;
}}
QToolButton:pressed {{
    background: #e2e8f0;
}}
QToolButton:checked {{
    background: #e0e7ff;
    border-color: #818cf8;
    color: #4f46e5;
}}

/* ── SpinBox ────────────────────────────────────────────── */
QSpinBox {{
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    padding: 2px 6px;
    min-height: 22px;
    font-size: 12px;
}}
QSpinBox:focus {{
    border-color: #818cf8;
}}

/* ── ComboBox ───────────────────────────────────────────── */
QComboBox {{
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    padding: 2px 6px;
    min-height: 22px;
    font-size: 12px;
}}
QComboBox:hover {{
    border-color: #94a3b8;
}}
QComboBox:focus {{
    border-color: #818cf8;
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}

/* ── ScrollArea (toolbar overflow) ──────────────────────── */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:horizontal {{
    height: 4px;
    background: transparent;
}}
QScrollBar::handle:horizontal {{
    background: #cbd5e1;
    border-radius: 2px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ── Label ──────────────────────────────────────────────── */
QLabel {{
    color: #334155;
}}

/* ── MainWindow ─────────────────────────────────────────── */
QMainWindow {{
    background: #ffffff;
}}
"""
