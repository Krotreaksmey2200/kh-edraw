# core/app_settings.py
# Lưu / đọc thiết lập ứng dụng qua QSettings (registry trên Windows, ~/.config trên Linux).
from __future__ import annotations
import json
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QColor

_ORG = 'eDraw'
_APP = 'eDraw'
DEFAULT_LANGUAGE = 'km'
SUPPORTED_LANGUAGES = ('km', 'vi', 'en')
DEFAULT_GEMINI_MODEL = 'gemini-pro-latest'


def normalize_language(language: str | None = None) -> str:
    value = (language or '').strip().lower()
    if value in SUPPORTED_LANGUAGES:
        return value
    return DEFAULT_LANGUAGE


def load_language() -> str:
    s = QSettings(_ORG, _APP)
    return normalize_language(str(s.value('ui/language', DEFAULT_LANGUAGE) or ''))


def save_language(language: str | None = None) -> None:
    s = QSettings(_ORG, _APP)
    s.setValue('ui/language', normalize_language(language))


def save(
    canvas,
    stroke_idx: int = 0,
    pen_slots: list | None = None,
    pen2_slots: list | None = None,
    highlight_slots: list | None = None,
    active_pen: int = 0,
    active_pen2: int = 0,
    active_pen_group: int = 1,
    active_hl: int = 0,
    toolbar_height: int | None = None,
    tool_group_height: int | None = None,
    toolbar_vertical: bool | None = None,
) -> None:
    """Ghi toàn bộ thiết lập hiện tại ra QSettings."""
    s = QSettings(_ORG, _APP)
    e = canvas.engine
    s.setValue('pen/color', e.pen_color.name(QColor.NameFormat.HexArgb))
    s.setValue('pen/width', e.pen_width)
    s.setValue('pen/opacity', e.pen_opacity)
    s.setValue('pen/stroke_idx', stroke_idx)
    s.setValue('tools/follow_pen', e.tool_attrs_follow_pen)
    s.setValue('highlight/color', e.highlight_color.name(QColor.NameFormat.HexArgb))
    s.setValue('highlight/width', e.highlight_width)
    s.setValue('highlight/opacity', e.highlight_opacity)
    s.setValue('line/color', e.line_color.name(QColor.NameFormat.HexArgb))
    s.setValue('line/width', e.line_width)
    s.setValue('line/opacity', e.line_opacity)
    s.setValue('curve/color', e.curve_color.name(QColor.NameFormat.HexArgb))
    s.setValue('curve/width', e.curve_width)
    s.setValue('curve/opacity', e.curve_opacity)
    s.setValue('curve/fill_enabled', e.curve_fill_enabled)
    s.setValue('curve/border_enabled', e.curve_border_enabled)
    s.setValue('polygon/color', e.polygon_color.name(QColor.NameFormat.HexArgb))
    s.setValue('polygon/width', e.polygon_width)
    s.setValue('polygon/opacity', e.polygon_opacity)
    s.setValue('polygon/fill_enabled', e.polygon_fill_enabled)
    s.setValue('polygon/border_enabled', e.polygon_border_enabled)
    s.setValue('polygon/fill_color', e.polygon_fill_color.name(QColor.NameFormat.HexArgb))
    s.setValue('polygon/fill_opacity', e.polygon_fill_opacity)
    s.setValue('polygon/fill_style', e.polygon_fill_style)
    s.setValue('polygon/fill_style_idx', e.polygon_fill_style_idx)
    s.setValue('markdown/font_size', e.markdown_font_size)
    s.setValue('texstudio/layout_mode', getattr(canvas, 'texstudio_layout_mode', 'inline'))
    s.setValue('texstudio/editor_font_family', getattr(canvas, 'texstudio_editor_font_family', 'Consolas'))
    s.setValue('texstudio/editable_text', bool(getattr(canvas, 'editable_text_mode', False)))
    s.setValue('texstudio/editor_font_size', int(getattr(canvas, 'texstudio_editor_font_size', 16)))
    s.setValue('texstudio/editor_color', _color_name(getattr(canvas, 'texstudio_editor_color', QColor('#111827')), '#111827'))
    s.setValue('texstudio/editor_background', _color_name(getattr(canvas, 'texstudio_editor_background', QColor('#ffffff')), '#ffffff'))
    s.setValue('texstudio/editor_rainbow', bool(getattr(canvas, 'texstudio_editor_rainbow', True)))
    s.setValue('texstudio/preview_font_family', getattr(canvas, 'texstudio_preview_font_family', 'Arial'))
    s.setValue('texstudio/preview_font_size', int(getattr(canvas, 'texstudio_preview_font_size', 16)))
    s.setValue('texstudio/preview_text_color', _color_name(getattr(canvas, 'texstudio_preview_text_color', QColor('#111827')), '#111827'))
    s.setValue('texstudio/preview_background', _color_name(getattr(canvas, 'texstudio_preview_background', QColor('#fffbeb')), '#fffbeb'))
    s.setValue('texstudio/split_percent', int(getattr(canvas, 'texstudio_split_percent', 50)))
    _save_tool_attrs(s, e.tool_attrs)
    s.setValue('board/color', canvas.board_color.name(QColor.NameFormat.HexArgb))
    s.setValue('board/grid_h', canvas.grid_h)
    s.setValue('board/grid_v', canvas.grid_v)
    s.setValue('board/grid_thickness', canvas.grid_thickness)
    s.setValue('board/grid_spacing', canvas.grid_spacing)
    if toolbar_height is not None:
        s.setValue('ui/toolbar_height', int(toolbar_height))
    if tool_group_height is not None:
        s.setValue('ui/tool_group_height', int(tool_group_height))
    if toolbar_vertical is not None:
        s.setValue('ui/toolbar_vertical', bool(toolbar_vertical))
    if pen_slots is not None:
        s.setValue('pen_slots/count', len(pen_slots))
        s.setValue('pen_slots/active', active_pen)
        s.setValue('pen_slots/active_group', active_pen_group)
        for i, slot in enumerate(pen_slots):
            g = f'pen_slots/{i}'
            s.setValue(f'{g}/color', slot['color'].name(QColor.NameFormat.HexArgb))
            s.setValue(f'{g}/width', slot['width'])
            s.setValue(f'{g}/opacity', slot['opacity'])
            s.setValue(f'{g}/style_idx', slot.get('style_idx', 0))
    if pen2_slots is not None:
        s.setValue('pen2_slots/count', len(pen2_slots))
        s.setValue('pen2_slots/active', active_pen2)
        for i, slot in enumerate(pen2_slots):
            g = f'pen2_slots/{i}'
            s.setValue(f'{g}/color', slot['color'].name(QColor.NameFormat.HexArgb))
            s.setValue(f'{g}/width', slot['width'])
            s.setValue(f'{g}/opacity', slot['opacity'])
            s.setValue(f'{g}/style_idx', slot.get('style_idx', 0))
    if highlight_slots is not None:
        s.setValue('hl_slots/count', len(highlight_slots))
        s.setValue('hl_slots/active', active_hl)
        for i, slot in enumerate(highlight_slots):
            g = f'hl_slots/{i}'
            s.setValue(f'{g}/color', slot['color'].name(QColor.NameFormat.HexArgb))
            s.setValue(f'{g}/width', slot['width'])
            s.setValue(f'{g}/opacity', slot['opacity'])
    s.setValue('engine/smoothing', float(e.freehand_smoothing))
    s.setValue('engine/min_dist', float(e.freehand_min_distance))
    s.setValue('engine/free_close_enabled', bool(e.free_close_enabled))
    s.setValue('engine/pressure', bool(e.use_pressure))
    s.setValue('engine/ink_sampling_min_distance', float(e.ink_sampling_min_distance))
    s.setValue('engine/final_stroke_smoothing_enabled', bool(e.final_stroke_smoothing_enabled))
    s.setValue('engine/one_euro_min_cutoff', float(e.one_euro.min_cutoff))
    s.setValue('engine/one_euro_beta', float(e.one_euro.beta))
    s.setValue('engine/lead_lookahead_sec', float(e._lead_lookahead_sec))
    s.setValue('engine/lead_predict_min_speed', float(e._lead_predict_min_speed))
    s.setValue('engine/pressure_width_strength', float(e.pressure_width_strength))
    s.setValue('engine/velocity_width_strength', float(e.velocity_width_strength))


def load(canvas):
    """Nạp thiết lập vào canvas + engine."""
    s = QSettings(_ORG, _APP)
    e = canvas.engine
    pen_c = QColor(str(s.value('pen/color', '#ff000000')))
    e.pen_color = pen_c if pen_c.isValid() else QColor('black')
    e.pen_width = _int(s.value('pen/width', 3), lo=1, hi=200)
    e.pen_opacity = _int(s.value('pen/opacity', 100), lo=0, hi=100)
    e.tool_attrs_follow_pen = _bool(s.value('tools/follow_pen', True))
    hl_c = QColor(str(s.value('highlight/color', '#ffeab308')))
    e.highlight_color = hl_c if hl_c.isValid() else QColor('#eab308')
    e.highlight_width = _int(s.value('highlight/width', 30), lo=1, hi=200)
    e.highlight_opacity = _int(s.value('highlight/opacity', 50), lo=0, hi=100)
    line_c = QColor(str(s.value('line/color', '#ff000000')))
    if not line_c.isValid():
        line_c = QColor(str(s.value('shape/color', '#ff000000')))
    e.line_color = line_c if line_c.isValid() else QColor('black')
    e.line_width = _int(s.value('line/width', s.value('shape/width', 3)), lo=1, hi=200)
    e.line_opacity = _int(s.value('line/opacity', 100), lo=0, hi=100)
    curve_c = QColor(str(s.value('curve/color', '#ff000000')))
    if not curve_c.isValid():
        curve_c = QColor(str(s.value('shape/color', '#ff000000')))
    e.curve_color = curve_c if curve_c.isValid() else QColor('black')
    e.curve_width = _int(s.value('curve/width', s.value('shape/width', 3)), lo=1, hi=200)
    e.curve_opacity = _int(s.value('curve/opacity', 100), lo=0, hi=100)
    e.curve_fill_enabled = _bool(s.value('curve/fill_enabled', False))
    e.curve_border_enabled = _bool(s.value('curve/border_enabled', True))
    polygon_c = QColor(str(s.value('polygon/color', '#ff000000')))
    if not polygon_c.isValid():
        polygon_c = QColor(str(s.value('shape/color', '#ff000000')))
    e.polygon_color = polygon_c if polygon_c.isValid() else QColor('black')
    e.polygon_width = _int(s.value('polygon/width', s.value('shape/width', 3)), lo=1, hi=200)
    e.polygon_opacity = _int(s.value('polygon/opacity', 100), lo=0, hi=100)
    e.polygon_border_enabled = _bool(s.value('polygon/border_enabled', True))
    polygon_fill_c = QColor(str(s.value('polygon/fill_color', '#ff94a3b8')))
    e.polygon_fill_color = polygon_fill_c if polygon_fill_c.isValid() else QColor('#94a3b8')
    e.polygon_fill_opacity = _int(s.value('polygon/fill_opacity', 0), lo=0, hi=100)
    e.polygon_fill_enabled = _bool(s.value('polygon/fill_enabled', e.polygon_fill_opacity > 0))
    e.polygon_fill_style = str(s.value('polygon/fill_style', 'solid') or 'solid')
    e.polygon_fill_style_idx = _int(s.value('polygon/fill_style_idx', 0), lo=0, hi=99)
    e.markdown_font_size = _int(s.value('markdown/font_size', 16), lo=1, hi=200)
    tex_mode = str(s.value('texstudio/layout_mode', 'inline') or 'inline').strip().lower()
    canvas.texstudio_layout_mode = 'split' if tex_mode == 'split' else 'inline'
    canvas.texstudio_editor_font_family = str(s.value('texstudio/editor_font_family', 'Consolas') or 'Consolas')
    canvas.editable_text_mode = _bool(s.value('texstudio/editable_text', False))
    canvas.texstudio_editor_font_size = _int(s.value('texstudio/editor_font_size', 16), lo=6, hi=72)
    canvas.texstudio_editor_color = _qcolor(s.value('texstudio/editor_color', '#111827'), '#111827')
    canvas.texstudio_editor_background = _qcolor(s.value('texstudio/editor_background', '#ffffff'), '#ffffff')
    canvas.texstudio_editor_rainbow = _bool(s.value('texstudio/editor_rainbow', True))
    canvas.texstudio_preview_font_family = str(s.value('texstudio/preview_font_family', 'Arial') or 'Arial')
    canvas.texstudio_preview_font_size = _int(s.value('texstudio/preview_font_size', 16), lo=1, hi=200)
    canvas.texstudio_preview_text_color = _qcolor(s.value('texstudio/preview_text_color', '#111827'), '#111827')
    canvas.texstudio_preview_background = _qcolor(s.value('texstudio/preview_background', '#fffbeb'), '#fffbeb')
    canvas.texstudio_split_percent = _int(s.value('texstudio/split_percent', 50), lo=25, hi=75)
    e.tool_attrs = _load_tool_attrs(s)
    board_c = QColor(str(s.value('board/color', '#ffffffff')))
    canvas.board_color = board_c if board_c.isValid() else QColor('white')
    canvas.grid_h = _bool(s.value('board/grid_h', True))
    canvas.grid_v = _bool(s.value('board/grid_v', True))
    canvas.grid_thickness = _int(s.value('board/grid_thickness', 1), lo=1, hi=10)
    canvas.grid_spacing = _int(s.value('board/grid_spacing', 35), lo=10, hi=300)
    toolbar_height = _int(s.value('ui/toolbar_height', 44), lo=16, hi=64)
    tool_group_height = _int(s.value('ui/tool_group_height', 36), lo=16, hi=56)
    toolbar_vertical = _bool(s.value('ui/toolbar_vertical', False))
    e.freehand_smoothing = _float(s.value('engine/smoothing', 0.52), lo=0, hi=1)
    e.freehand_min_distance = _float(s.value('engine/min_dist', 0), lo=0, hi=8)
    e.free_close_enabled = _bool(s.value('engine/free_close_enabled', True))
    e.use_pressure = _bool(s.value('engine/pressure', False))
    e.ink_sampling_min_distance = _float(s.value('engine/ink_sampling_min_distance', 0.5), lo=0.1, hi=4)
    e.final_stroke_smoothing_enabled = _bool(s.value('engine/final_stroke_smoothing_enabled', False))
    e.one_euro.set_params(
        min_cutoff=_float(s.value('engine/one_euro_min_cutoff', 2.5), lo=0.1, hi=20),
        beta=_float(s.value('engine/one_euro_beta', 0.5), lo=0, hi=1)
    )
    e._lead_lookahead_sec = _float(s.value('engine/lead_lookahead_sec', 0), lo=0, hi=0.05)
    e._lead_predict_min_speed = _float(s.value('engine/lead_predict_min_speed', 1000), lo=0, hi=2000)
    e.pressure_width_strength = _float(s.value('engine/pressure_width_strength', 1), lo=0, hi=2)
    e.velocity_width_strength = _float(s.value('engine/velocity_width_strength', 0.1), lo=0, hi=2)

    pen_slots = None
    active_pen = 0
    active_pen_group = _int(s.value('pen_slots/active_group', 1), lo=1, hi=2)
    n_pen = _int(s.value('pen_slots/count', 0), lo=0, hi=20)
    if n_pen > 0:
        active_pen = _int(s.value('pen_slots/active', 0), lo=0, hi=n_pen - 1)
        pen_slots = []
        for i in range(n_pen):
            g = f'pen_slots/{i}'
            c = QColor(str(s.value(f'{g}/color', '#ff000000')))
            if not c.isValid():
                c = QColor('black')
            pen_slots.append({
                'color': c,
                'width': _int(s.value(f'{g}/width', 3), lo=1, hi=200),
                'opacity': _int(s.value(f'{g}/opacity', 100), lo=0, hi=100),
                'style_idx': _int(s.value(f'{g}/style_idx', 0), lo=0, hi=99),
            })

    pen2_slots = None
    active_pen2 = 0
    n_pen2 = _int(s.value('pen2_slots/count', 0), lo=0, hi=20)
    if n_pen2 > 0:
        active_pen2 = _int(s.value('pen2_slots/active', 0), lo=0, hi=n_pen2 - 1)
        pen2_slots = []
        for i in range(n_pen2):
            g = f'pen2_slots/{i}'
            c = QColor(str(s.value(f'{g}/color', '#ffe11d48')))
            if not c.isValid():
                c = QColor('#e11d48')
            pen2_slots.append({
                'color': c,
                'width': _int(s.value(f'{g}/width', 3), lo=1, hi=200),
                'opacity': _int(s.value(f'{g}/opacity', 100), lo=0, hi=100),
                'style_idx': _int(s.value(f'{g}/style_idx', 0), lo=0, hi=99),
            })

    hl_slots = None
    active_hl = 0
    n_hl = _int(s.value('hl_slots/count', 0), lo=0, hi=20)
    if n_hl > 0:
        active_hl = _int(s.value('hl_slots/active', 0), lo=0, hi=n_hl - 1)
        hl_slots = []
        for i in range(n_hl):
            g = f'hl_slots/{i}'
            c = QColor(str(s.value(f'{g}/color', '#ffeab308')))
            if not c.isValid():
                c = QColor('#eab308')
            hl_slots.append({
                'color': c,
                'width': _int(s.value(f'{g}/width', 30), lo=1, hi=200),
                'opacity': _int(s.value(f'{g}/opacity', 50), lo=0, hi=100),
            })

    return {
        'stroke_idx': _int(s.value('pen/stroke_idx', 0), lo=0, hi=99),
        'pen_slots': pen_slots,
        'pen2_slots': pen2_slots,
        'hl_slots': hl_slots,
        'active_pen': active_pen,
        'active_pen2': active_pen2,
        'active_pen_group': active_pen_group,
        'active_hl': active_hl,
        'toolbar_height': toolbar_height,
        'tool_group_height': tool_group_height,
        'toolbar_vertical': toolbar_vertical,
    }


def load_gemini_api_key() -> str:
    s = QSettings(_ORG, _APP)
    return str(s.value('ai/gemini_api_key', '') or '')


def save_gemini_api_key(key: str | None = None) -> None:
    s = QSettings(_ORG, _APP)
    s.setValue('ai/gemini_api_key', str(key or ''))


def load_gemini_model() -> str:
    s = QSettings(_ORG, _APP)
    return normalize_gemini_model(str(s.value('ai/gemini_model', '') or ''))


def save_gemini_model(model: str | None = None) -> None:
    s = QSettings(_ORG, _APP)
    s.setValue('ai/gemini_model', normalize_gemini_model(model))


def normalize_gemini_model(model: str | None = None) -> str:
    val = (model or '').strip().removeprefix('models/')
    if not val or val in ('gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-2.0-pro', 'gemini-2.5-pro', 'gemini-2.5-flash'):
        return DEFAULT_GEMINI_MODEL
    return val



HANDWRITING_FONT_DEFAULT = 'playwrite_vn'
HANDWRITING_FONT_CHOICES = {
    'playwrite_vn': 'Playwrite VN',
    'patrick_hand': 'Patrick Hand',
    'ink_free': 'Ink Free',
    'segoe_print': 'Segoe Print',
    'segoe_script': 'Segoe Script',
    'lucida_handwriting': 'Lucida Handwriting',
    'mistral': 'Mistral',
    'brush_script': 'Brush Script MT',
    'freestyle_script': 'Freestyle Script',
    'script_mt_bold': 'Script MT Bold',
    'comic_sans': 'Comic Sans MS',
}


def normalize_handwriting_font(value: str | None = None) -> str:
    font_key = (value or '').strip().lower()
    if font_key in HANDWRITING_FONT_CHOICES:
        return font_key
    return HANDWRITING_FONT_DEFAULT


def load_handwriting_font() -> str:
    s = QSettings(_ORG, _APP)
    return normalize_handwriting_font(str(s.value('ai/handwriting_font', HANDWRITING_FONT_DEFAULT) or ''))


def save_handwriting_font(value: str | None = None) -> None:
    s = QSettings(_ORG, _APP)
    s.setValue('ai/handwriting_font', normalize_handwriting_font(value))


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ('true', '1', 'yes')
    return bool(v)


def _int(v, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return lo


def _float(v, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo


def _qcolor(v, default: str) -> QColor:
    color = QColor(str(v or default))
    if color.isValid():
        return color
    fallback = QColor(default)
    if fallback.isValid():
        return fallback
    return QColor('black')


def _color_name(v, default: str) -> str:
    color = QColor(v)
    if not color.isValid():
        color = QColor(default)
    return color.name(QColor.NameFormat.HexArgb)


def _save_tool_attrs(settings: QSettings, attrs: dict | None) -> None:
    """Lưu thuộc tính riêng của từng công cụ hình học."""
    out = {}
    for key, item in (attrs or {}).items():
        color = QColor(item.get('color', '#ff000000'))
        if not color.isValid():
            color = QColor('black')
        style = item.get('style', Qt.PenStyle.SolidLine)
        try:
            style_value = int(style.value)
        except AttributeError:
            style_value = int(style)

        dash_pattern = item.get('dash_pattern')
        out[str(key)] = {
            'color': color.name(QColor.NameFormat.HexArgb),
            'width': _int(item.get('width', 3), lo=1, hi=200),
            'opacity': _int(item.get('opacity', 100), lo=0, hi=100),
            'style': style_value,
            'dash_pattern': dash_pattern if dash_pattern else None,
            'style_idx': _int(item.get('style_idx', 0), lo=0, hi=99),
            'border_enabled': _bool(item.get('border_enabled', True)),
            'fill_enabled': _bool(item.get('fill_enabled', _int(item.get('fill_opacity', 0), lo=0, hi=100) > 0)),
            'fill_color': _color_name(item.get('fill_color', '#ff94a3b8'), '#94a3b8'),
            'fill_opacity': _int(item.get('fill_opacity', 0), lo=0, hi=100),
            'fill_style': str(item.get('fill_style', 'solid') or 'solid'),
            'fill_style_idx': _int(item.get('fill_style_idx', 0), lo=0, hi=99),
        }
    settings.setValue('tool_attrs/v1', json.dumps(out, ensure_ascii=False))


def _load_tool_attrs(settings: QSettings) -> dict:
    """Đọc thuộc tính riêng của từng công cụ hình học."""
    raw = settings.value('tool_attrs/v1', '')
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
        out = {}
        for key, item in data.items():
            if not isinstance(item, dict):
                continue
            color = QColor(str(item.get('color', '#ff000000')))
            if not color.isValid():
                color = QColor('black')
            try:
                style = Qt.PenStyle(int(item.get('style', Qt.PenStyle.SolidLine.value)))
            except (TypeError, ValueError):
                style = Qt.PenStyle.SolidLine

            dash_pattern = []
            for p in item.get('dash_pattern') or []:
                try:
                    dash_pattern.append(float(p))
                except (TypeError, ValueError):
                    pass
            pattern = dash_pattern if dash_pattern else None
            fill_opacity = _int(item.get('fill_opacity', 0), lo=0, hi=100)

            out[str(key)] = {
                'color': color,
                'width': _int(item.get('width', 3), lo=1, hi=200),
                'opacity': _int(item.get('opacity', 100), lo=0, hi=100),
                'style': style,
                'dash_pattern': pattern,
                'style_idx': _int(item.get('style_idx', 0), lo=0, hi=99),
                'border_enabled': _bool(item.get('border_enabled', True)),
                'fill_enabled': _bool(item.get('fill_enabled', fill_opacity > 0)),
                'fill_color': _qcolor(item.get('fill_color', '#ff94a3b8'), '#94a3b8'),
                'fill_opacity': fill_opacity,
                'fill_style': str(item.get('fill_style', 'solid') or 'solid'),
                'fill_style_idx': _int(item.get('fill_style_idx', 0), lo=0, hi=99),
            }
        return out
    except Exception:
        return {}


def save_custom_tools(tools_dict: dict) -> None:
    """Lưu danh sách công cụ AI tuỳ biến (mã nguồn và metadata) vào QSettings."""
    s = QSettings(_ORG, _APP)
    tools_list = []
    for name, tool in tools_dict.items():
        tools_list.append({
            'name': name,
            'code': tool.get('code', ''),
            'tool_type': tool.get('tool_type', 'curve'),
        })
    s.setValue('ai/custom_tools', json.dumps(tools_list))


def load_custom_tools() -> list:
    """Đọc danh sách công cụ AI tuỳ biến từ QSettings."""
    s = QSettings(_ORG, _APP)
    val = s.value('ai/custom_tools', '')
    if not val:
        return []
    try:
        return json.loads(str(val))
    except Exception:
        return []


def load_figure_templates() -> list:
    """Đọc danh sách mẫu vẽ hình do người dùng tạo."""
    s = QSettings(_ORG, _APP)
    val = s.value('figure/templates/v1', '')
    if not val:
        return []
    try:
        data = json.loads(str(val))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        backend = str(item.get('backend', '') or '').strip()
        title = str(item.get('title', '') or '').strip()
        code = str(item.get('code', '') or '')
        template_id = str(item.get('id', '') or '').strip()
        if backend not in frozenset({'tikz', 'edraw'}) or (not title and not code):
            continue
        out.append({
            'id': template_id,
            'backend': backend,
            'title': title,
            'code': code,
        })
    return out


def save_figure_templates(templates: list) -> None:
    """Lưu danh sách mẫu vẽ hình do người dùng tạo."""
    s = QSettings(_ORG, _APP)
    out = []
    for item in (templates or []):
        if not isinstance(item, dict):
            continue
        backend = str(item.get('backend', '') or '').strip()
        title = str(item.get('title', '') or '').strip()
        code = str(item.get('code', '') or '')
        template_id = str(item.get('id', '') or '').strip()
        if backend not in frozenset({'tikz', 'edraw'}) or (not title and not code):
            continue
        out.append({
            'id': template_id,
            'backend': backend,
            'title': title,
            'code': code,
        })
    s.setValue('figure/templates/v1', json.dumps(out, ensure_ascii=False))


def load_figure_template_title_overrides() -> dict:
    """Đọc tên mới của các mẫu mặc định nếu người dùng đã đổi tên."""
    s = QSettings(_ORG, _APP)
    val = s.value('figure/template_title_overrides/v1', '')
    if not val:
        return {}
    try:
        data = json.loads(str(val))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): str(value).strip()
        for key, value in data.items()
        if str(key).strip() and str(value).strip()
    }


def save_figure_template_title_overrides(overrides=None) -> None:
    """Lưu tên mới của các mẫu mặc định."""
    s = QSettings(_ORG, _APP)
    clean = {
        str(key): str(value).strip()
        for key, value in (overrides or {}).items()
        if str(key).strip() and str(value).strip()
    }
    s.setValue('figure/template_title_overrides/v1', json.dumps(clean, ensure_ascii=False))


def load_figure_template_code_overrides() -> dict:
    """Đọc mã đã chỉnh của các mẫu mặc định."""
    s = QSettings(_ORG, _APP)
    val = s.value('figure/template_code_overrides/v1', '')
    if not val:
        return {}
    try:
        data = json.loads(str(val))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in data.items()
        if str(key).strip() and str(value).strip()
    }


def save_figure_template_code_overrides(overrides=None) -> None:
    """Lưu mã đã chỉnh của các mẫu mặc định."""
    s = QSettings(_ORG, _APP)
    clean = {
        str(key): str(value)
        for key, value in (overrides or {}).items()
        if str(key).strip() and str(value).strip()
    }
    s.setValue('figure/template_code_overrides/v1', json.dumps(clean, ensure_ascii=False))


def load_figure_template_hidden_keys() -> set:
    """Đọc danh sách mẫu mặc định người dùng đã ẩn/xóa khỏi menu."""
    s = QSettings(_ORG, _APP)
    val = s.value('figure/template_hidden_keys/v1', '')
    if not val:
        return set()
    try:
        data = json.loads(str(val))
    except Exception:
        return set()
    if not isinstance(data, list):
        return set()
    return {
        str(item).strip()
        for item in data
        if str(item).strip()
    }


def save_figure_template_hidden_keys(keys=None) -> None:
    """Lưu danh sách mẫu mặc định bị ẩn/xóa khỏi menu."""
    s = QSettings(_ORG, _APP)
    clean = sorted({
        str(item).strip()
        for item in (keys or set())
        if str(item).strip()
    })
    s.setValue('figure/template_hidden_keys/v1', json.dumps(clean, ensure_ascii=False))
