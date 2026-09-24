"""
widgets/canvas.py
Main drawing widget: connects SlideModel, DrawingEngine, ImageHandler.

Key upgrades:
- Tablet/stylus event support with pressure passed to DrawingEngine.
- Preview/commit FREEHAND using StrokeSegment for dynamic width.
- Dirty repaint for preview, eraser cursor, and floating image.
- Eraser deletes from press.
- Preserves existing public API of Canvas.
"""
from __future__ import annotations

import html
import json
import math
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSizeF,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QBrush,
    QFont,
    QFontMetricsF,
    QCursor,
    QImage,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRegion,
    QSyntaxHighlighter,
    QTabletEvent,
    QTextCharFormat,
    QTextDocument,
    QTransform,
)
from PyQt6.QtWidgets import QApplication, QTextEdit, QVBoxLayout, QWidget

from core.drawing_engine import DrawMode, DrawingEngine, InkOutline, StrokeSegment
from core.image_handler import ImageHandler
from core.i18n import t
from core.rich_text_preprocessor import contains_tikz as _rich_contains_tikz, preprocess_to_html as _rich_preprocess_to_html
from models.elements import ImageElement, PythonFigureElement, StrokeElement, TextElement
from models.slide import SlideModel

try:
    import markdown as _markdown
except Exception:
    _markdown = None

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except Exception:
    QWebEngineView = None

try:
    from PyQt6.QtWebEngineCore import QWebEngineSettings
except Exception:
    QWebEngineSettings = None

_MARKDOWN_EXTENSIONS = ["extra", "tables", "fenced_code", "toc", "sane_lists"]
_MATHJAX_RENDER_DELAY_MS = 80
_MATHJAX_RENDER_ATTEMPTS = 12
_MATHJAX_READY_RETRY_MS = 100
_MATHJAX_READY_RETRY_ATTEMPTS = 90
_TYPE_LIVE_RENDER_DELAY_MS = 90
_FLOATING_PIXMAP_RENDER_SCALE = 4
_FLOATING_PIXMAP_MAX_DIM = 8192
_FLOATING_TRIM_PADDING_PX = 2
_MATHJAX_CDN = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"
_TIKZJAX_RENDER_DELAY_MS = 150
_TIKZJAX_RENDER_ATTEMPTS = 80
_SHELL_CACHE_PATH: Path | None = None
_SHELL_HAS_TIKZ: bool = False

_SHELL_HTML_TEMPLATE = (
    "<!DOCTYPE html><html><head>"
    "<meta charset='utf-8'>"
    "<style>{css}</style>"
    "<script>window.MathJax = {{tex: {{inlineMath: [['$','$'],['\\\\(','\\\\)']]}}}};</script>"
    "<script id='mathjax-script' src='{mathjax_url}' async></script>"
    "</head><body>"
    "<div id='edraw-content'></div>"
    "<script>var edrawTikzAvailable = {tikz_available_js};"
    "var edrawTikzjaxSrc = {tikzjax_src_js};</script>"
    "{tikzjax_head}"
    "</body></html>"
)

_SHELL_CSS = (
    "html, body { margin: 0; padding: 0; background: transparent; }\n"
    "body { font-family: Arial, sans-serif; font-size: 24px; line-height: 1.55; color: #000; }\n"
    ".edraw-md { box-sizing: border-box; padding: 8px; }\n"
    "h1, h2, h3 { margin: 0.55em 0 0.3em 0; padding-bottom: 0.18em; border-bottom: 1px solid #e2e8f0; }\n"
    "p { margin: 0.35em 0; }\n"
    "ul, ol { margin: 0.35em 0 0.35em 1.4em; }\n"
    "code { font-family: Consolas,Monaco,monospace; background: #f1f5f9; padding: 2px 4px; border-radius: 4px; }\n"
    "pre { font-family: Consolas,Monaco,monospace; background: #f1f5f9; padding: 10px; border-radius: 7px; white-space: pre-wrap; }\n"
    "blockquote { border-left: 4px solid #cbd5e1; margin-left: 0; padding-left: 10px; color: #475569; }\n"
    "table { border-collapse: collapse; margin: 0.45em 0; }\n"
    "th, td { border: 1px solid #cbd5e1; padding: 5px 7px; vertical-align: top; }\n"
    "th { background: #f8fafc; }\n"
)


def _alpha_content_rect_from_image(image, padding=0, alpha_threshold=0):
    """Return the smallest image rect containing non-transparent pixels."""
    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        return QRect()
    scan = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    width = scan.width()
    height = scan.height()
    threshold = max(0, min(255, int(alpha_threshold)))
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    try:
        ptr = scan.constBits()
        ptr.setsize(scan.sizeInBytes())
        data = memoryview(ptr)
        stride = scan.bytesPerLine()
        for y in range(height):
            start = y * stride + 3
            alphas = bytes(data[start:start + width * 4:4])
            if threshold <= 0:
                if max(alphas) == 0:
                    continue
                left = len(alphas) - len(alphas.lstrip(b"\x00"))
                right = len(alphas.rstrip(b"\x00")) - 1
            else:
                left, right = -1, -1
                for x, alpha in enumerate(alphas):
                    if alpha > threshold:
                        left = x
                        break
                if left < 0:
                    continue
                for x in range(width - 1, left - 1, -1):
                    if alphas[x] > threshold:
                        right = x
                        break
            min_x = min(min_x, left)
            max_x = max(max_x, right)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
    except Exception:
        for y in range(height):
            row_left, row_right = -1, -1
            for x in range(width):
                if scan.pixelColor(x, y).alpha() > threshold:
                    row_left = x
                    break
            if row_left < 0:
                continue
            for x in range(width - 1, row_left - 1, -1):
                if scan.pixelColor(x, y).alpha() > threshold:
                    row_right = x
                    break
            min_x = min(min_x, row_left)
            max_x = max(max_x, row_right)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
    if max_x < min_x or max_y < min_y:
        return QRect()
    pad = max(0, int(padding))
    return QRect(
        max(0, min_x - pad),
        max(0, min_y - pad),
        (min(width - 1, max_x + pad) - max(0, min_x - pad)) + 1,
        (min(height - 1, max_y + pad) - max(0, min_y - pad)) + 1,
    )


def _trim_transparent_pixmap(pixmap, padding=0):
    if pixmap.isNull():
        return (pixmap, QPoint(0, 0))
    content_rect = _alpha_content_rect_from_image(pixmap.toImage(), padding)
    full_rect = pixmap.rect()
    if content_rect.isNull() or content_rect == full_rect:
        return (pixmap, QPoint(0, 0))
    trimmed = pixmap.copy(content_rect)
    if trimmed.isNull():
        return (pixmap, QPoint(0, 0))
    return (trimmed, content_rect.topLeft())


def _mathjax_local_dir():
    """Directory containing tex-svg.js (MathJax) bundled with the app."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    d = base / "config" / "mathjax"
    if (d / "tex-svg.js").exists():
        return d
    return None


def _tikzjax_local_dir():
    """Directory containing tikzjax.js (+ wasm/dump) bundled with the app."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    d = base / "config" / "tikzjax"
    if not (d / "tikzjax.js").exists():
        return None
    return d


def has_tikz_renderer():
    """True if bundle has TikZJax — used to gate Python-side UI/logic."""
    return _tikzjax_local_dir() is not None


def _get_mathjax_shell_path():
    """Build (or reuse) shell HTML containing MathJax (+ TikZJax if available)."""
    global _SHELL_CACHE_PATH, _SHELL_HAS_TIKZ
    if _SHELL_CACHE_PATH and _SHELL_CACHE_PATH.exists():
        return _SHELL_CACHE_PATH
    mathjax_dir = _mathjax_local_dir()
    tikz_dir = _tikzjax_local_dir()
    mathjax_url = QUrl.fromLocalFile(str(mathjax_dir / "tex-svg.js")).toString() if mathjax_dir else _MATHJAX_CDN
    tikz_available_js = "true" if tikz_dir else "false"
    tikzjax_head = ""
    tikzjax_src_js = "null"
    if tikz_dir:
        _SHELL_HAS_TIKZ = True
        tikzjax_src_js = json.dumps(QUrl.fromLocalFile(str(tikz_dir / "tikzjax.js")).toString())
    else:
        _SHELL_HAS_TIKZ = False
    html_content = _SHELL_HTML_TEMPLATE.format(
        mathjax_url=mathjax_url,
        tikz_available_js=tikz_available_js,
        tikzjax_src_js=tikzjax_src_js,
        tikzjax_head=tikzjax_head,
        css=_SHELL_CSS,
    )
    tmp_dir = Path(tempfile.mkdtemp(prefix="edraw_math"))
    shell_path = tmp_dir / "shell.html"
    shell_path.write_text(html_content, encoding="utf-8")
    _SHELL_CACHE_PATH = shell_path
    return shell_path


def _format_inline_markdown(text):
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<em>\1</em>", escaped)
    return escaped


def _replace_latex_fractions(value):
    return re.sub(
        r"\\frac\{([^}]+)\}\{([^}]+)\}",
        r'<table class="edraw-frac"><tr><td class="edraw-frac-num">\1</td></tr><tr><td>\2</td></tr></table>',
        value,
    )


def _latex_to_html_fragment(expr):
    if not expr:
        return ""
    value = html.unescape(expr).strip()
    value = _replace_latex_fractions(value)
    value = re.sub(r"\\([a-zA-Z]+)", r"<i>\1</i>", value)
    value = re.sub(r"[{}]", "", value)
    return value


def _math_text_fallback(body):
    return f"<span class='edraw-math'>{html.escape(body)}</span>"


def _read_latex_group(value, start):
    if start >= len(value) or value[start] != "{":
        return (None, start)
    depth = 0
    chars = []
    i = start
    while i < len(value):
        ch = value[i]
        if ch == "{":
            if depth > 0:
                chars.append(ch)
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return ("".join(chars), i + 1)
            chars.append(ch)
        else:
            chars.append(ch)
        i += 1
    return (None, start)


def _read_latex_script_arg(value, start):
    if start >= len(value):
        return (None, start)
    if value[start] == "{":
        return _read_latex_group(value, start)
    return (value[start:start + 1], start + 1)


def _extract_single_latex_math(text):
    if not text:
        return None
    value = text.strip()
    match = re.fullmatch(r"\$\$(.+?)\$\$", value, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.fullmatch(r"(?<!\\)\$(.+?)(?<!\\)\$", value, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def _scaled_font(font, scale):
    scaled = QFont(font)
    point_size = scaled.pointSizeF()
    if point_size > 0:
        scaled.setPointSizeF(max(1, point_size * scale))
    else:
        scaled.setPixelSize(max(1, int(scaled.pixelSize() * scale)))
    return scaled


class _LatexBox:
    width: float = 0
    ascent: float = 0
    descent: float = 0

    @property
    def height(self):
        return self.ascent + self.descent

    def draw(self, painter, x, baseline_y):
        raise NotImplementedError


class _LatexTextBox(_LatexBox):
    def __init__(self, text, font):
        self.text = text
        self.font = QFont(font)
        metrics = QFontMetricsF(self.font)
        self.width = max(0, metrics.horizontalAdvance(text))
        self.ascent = metrics.ascent()
        self.descent = metrics.descent()

    def draw(self, painter, x, baseline_y):
        painter.setFont(self.font)
        painter.drawText(QPointF(x, baseline_y), self.text)


class _LatexHBox(_LatexBox):
    def __init__(self, boxes, font):
        self.boxes = boxes or [_LatexTextBox("", font)]
        self.width = sum(b.width for b in self.boxes)
        self.ascent = max((b.ascent for b in self.boxes), default=0)
        self.descent = max((b.descent for b in self.boxes), default=0)

    def draw(self, painter, x, baseline_y):
        cursor = x
        for box in self.boxes:
            box.draw(painter, cursor, baseline_y)
            cursor += box.width


class _LatexFracBox(_LatexBox):
    def __init__(self, numerator, denominator, font_size):
        self.numerator = numerator
        self.denominator = denominator
        self.pad = max(3, font_size * 0.12)
        self.gap = max(2, font_size * 0.1)
        self.line_width = max(1, font_size * 0.045)
        self.width = max(numerator.width, denominator.width) + self.pad * 2
        self.ascent = numerator.height + self.gap + self.line_width * 0.5
        self.descent = denominator.height + self.gap + self.line_width * 0.5

    def draw(self, painter, x, baseline_y):
        old_pen = painter.pen()
        pen = QPen(old_pen)
        pen.setWidthF(self.line_width)
        painter.setPen(pen)
        painter.drawLine(QPointF(x, baseline_y), QPointF(x + self.width, baseline_y))
        painter.setPen(old_pen)
        num_x = x + (self.width - self.numerator.width) / 2
        den_x = x + (self.width - self.denominator.width) / 2
        num_baseline = baseline_y - self.gap - self.line_width * 0.5 - self.numerator.descent
        den_baseline = baseline_y + self.gap + self.line_width * 0.5 + self.denominator.ascent
        self.numerator.draw(painter, num_x, num_baseline)
        self.denominator.draw(painter, den_x, den_baseline)


class _LatexScriptBox(_LatexBox):
    def __init__(self, base, *, superscript=None, subscript=None):
        self.base = base
        self.superscript = superscript
        self.subscript = subscript
        self.script_gap = max(1, base.width * 0.03)
        self._recalc()

    def _recalc(self):
        self.width = self.base.width + self.script_gap
        if self.superscript:
            self.width += self.superscript.width
        if self.subscript:
            self.width += self.subscript.width
        self.ascent = self.base.ascent
        if self.superscript:
            self.ascent = max(self.ascent, self.base.ascent * 0.5 + self.superscript.ascent)
        self.descent = self.base.descent
        if self.subscript:
            self.descent = max(self.descent, self.base.descent * 0.5 + self.subscript.descent)

    def with_script(self, *, superscript=None, subscript=None):
        new = _LatexScriptBox(self.base, superscript=superscript or self.superscript, subscript=subscript or self.subscript)
        return new

    def draw(self, painter, x, baseline_y):
        self.base.draw(painter, x, baseline_y)
        script_x = x + self.base.width + self.script_gap
        if self.superscript:
            self.superscript.draw(painter, script_x, baseline_y - self.base.ascent * 0.3)
        if self.subscript:
            self.subscript.draw(painter, script_x, baseline_y + self.base.descent * 0.5)


def _latex_math_command_text(name):
    mapping = {
        "alpha": "\u03b1", "beta": "\u03b2", "gamma": "\u03b3",
        "delta": "\u03b4", "epsilon": "\u03b5", "theta": "\u03b8",
        "lambda": "\u03bb", "mu": "\u03bc", "pi": "\u03c0",
        "sigma": "\u03c3", "omega": "\u03c0",
        "infty": "\u221e", "partial": "\u2202", "nabla": "\u2207",
        "pm": "\u00b1", "times": "\u00d7", "div": "\u00f7",
        "leq": "\u2264", "geq": "\u2265", "neq": "\u2260",
        "approx": "\u2248", "equiv": "\u2261",
        "leftarrow": "\u2190", "rightarrow": "\u2192",
        "leftrightarrow": "\u2194",
        "sin": "sin", "cos": "cos", "tan": "tan",
        "log": "log", "ln": "ln", "exp": "exp",
    }
    return mapping.get(name, name)


class _LatexMathParser:
    _skip_commands = {"Big", "big", "Bigg", "bigg", "left", "quad", "qquad", "right"}

    def __init__(self, expr, font):
        self.expr = expr
        self.font = QFont(font)
        self.i = 0

    def parse(self):
        boxes = []
        while self.i < len(self.expr):
            ch = self.expr[self.i]
            if ch in ("}", ")", "]"):
                self.i += 1
                continue
            if ch == "{":
                content, end = _read_latex_group(self.expr, self.i)
                if content is not None:
                    sub = _LatexMathParser(content, self.font).parse()
                    boxes.append(sub)
                    self.i = end
                    continue
            if ch == "\\":
                cmd_box = self._read_command()
                if cmd_box:
                    boxes.append(cmd_box)
                continue
            if ch in ("^", "_"):
                arg_text, after = _read_latex_script_arg(self.expr, self.i + 1)
                self.i = after
                if arg_text:
                    script = _LatexMathParser(arg_text, _scaled_font(self.font, 0.62)).parse()
                    base = boxes.pop() if boxes else _LatexTextBox("", self.font)
                    if isinstance(base, _LatexScriptBox):
                        boxes.append(base.with_script(
                            superscript=script if ch == "^" else None,
                            subscript=script if ch == "_" else None,
                        ))
                    else:
                        boxes.append(_LatexScriptBox(
                            base,
                            superscript=script if ch == "^" else None,
                            subscript=script if ch == "_" else None,
                        ))
                continue
            if ch == " ":
                self.i += 1
                continue
            start = self.i
            while self.i < len(self.expr) and self.expr[self.i] not in "\\{}^_":
                self.i += 1
            text = self.expr[start:self.i]
            if text:
                boxes.append(_LatexTextBox(text, self.font))
        if not boxes:
            return _LatexTextBox("", self.font)
        if len(boxes) == 1:
            return boxes[0]
        return _LatexHBox(boxes, self.font)

    def _read_command(self):
        start = self.i
        j = start + 1
        while j < len(self.expr) and self.expr[j].isalpha():
            j += 1
        name = self.expr[start + 1:j]
        self.i = j
        if not name:
            self.i = min(len(self.expr), start + 2)
            return _LatexTextBox(self.expr[start + 1:self.i], self.font)
        if name in self._skip_commands:
            self.i = j
            return None
        if name == "frac":
            num_text, after = _read_latex_group(self.expr, self.i)
            self.i = after
            den_text, after = _read_latex_group(self.expr, self.i)
            self.i = after
            num = _LatexMathParser(num_text or "", self.font).parse()
            den = _LatexMathParser(den_text or "", self.font).parse()
            return _LatexFracBox(num, den, self.font.pointSizeF() or 12)
        if name == "sqrt":
            arg_text, after = _read_latex_group(self.expr, self.i)
            self.i = after
            inner = _LatexMathParser(arg_text or "", self.font).parse()
            return _LatexTextBox(f"\u221a({arg_text or ''})", self.font)
        text = _latex_math_command_text(name)
        return _LatexTextBox(text, self.font)


def _parse_latex_math_box(expr, font):
    return _LatexMathParser(expr, font).parse()


def _is_table_separator(line):
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    parts = [c.strip() for c in stripped.split("|")]
    return all(re.match(r"^:?-+:?$", p) for p in parts if p)


def _split_markdown_table_row(line):
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    cells = []
    current = []
    in_math = False
    math_delim = ""
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\":
            current.append(ch)
            if i + 1 < len(value):
                current.append(value[i + 1])
                i += 2
                continue
        if ch == "$":
            delim = "$$" if value.startswith("$$", i) else "$"
            if in_math and delim == math_delim:
                in_math = False
                math_delim = ""
            elif not in_math:
                in_math = True
                math_delim = delim
            current.append(delim)
            i += len(delim)
            continue
        if ch == "|" and not in_math:
            cells.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    cells.append("".join(current).strip())
    return cells


def _basic_markdown_to_html(text):
    """Simple markdown to HTML conversion without external dependencies."""
    lines = text.split("\n")
    html_parts = []
    in_code = False
    in_list = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                html_parts.append("</code></pre>")
                in_code = False
            else:
                html_parts.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            html_parts.append(html.escape(line))
            continue
        if stripped.startswith("# "):
            html_parts.append(f"<h1>{_format_inline_markdown(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            html_parts.append(f"<h2>{_format_inline_markdown(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            html_parts.append(f"<h3>{_format_inline_markdown(stripped[4:])}</h3>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{_format_inline_markdown(stripped[2:])}</li>")
        elif stripped.startswith("> "):
            html_parts.append(f"<blockquote>{_format_inline_markdown(stripped[2:])}</blockquote>")
        elif _is_table_separator(stripped):
            continue
        elif "|" in stripped:
            cells = _split_markdown_table_row(stripped)
            if cells:
                html_parts.append("<tr>" + "".join(f"<td>{_format_inline_markdown(c)}</td>" for c in cells) + "</tr>")
        elif stripped == "":
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append("<br>")
        else:
            html_parts.append(f"<p>{_format_inline_markdown(stripped)}</p>")
    if in_list:
        html_parts.append("</ul>")
    return "\n".join(html_parts)


class _RainbowHighlighter(QSyntaxHighlighter):
    """Rainbow coloring for each character in the editor."""
    _COLORS: list[QColor] = [
        QColor("#e11d48"), QColor("#f97316"), QColor("#ca8a04"),
        QColor("#16a34a"), QColor("#0284c7"), QColor("#4f46e5"),
        QColor("#9333ea"),
    ]

    def highlightBlock(self, text):
        fmt = QTextCharFormat()
        n = len(self._COLORS)
        for i in range(len(text)):
            fmt.setForeground(self._COLORS[i % n])
            self.setFormat(i, 1, fmt)


class MarkdownTypeEditor(QTextEdit):
    """Rich text editor for typing markdown content."""
    content_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setFont(QFont("Arial", 14))
        self.setStyleSheet("QTextEdit { background:#1e293b; color:#f1f5f9; border:none; padding:8px; }")
        self._rainbow = _RainbowHighlighter(self.document())

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        self.content_changed.emit(self.toPlainText())


class MarkdownLivePreview(QWidget):
    """Live preview of markdown text using QWebEngineView."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if QWebEngineView is not None:
            self._web = QWebEngineView()
        else:
            self._web = None
        if self._web is not None:
            layout.addWidget(self._web)
            self._web.setHtml("<html><body style='background:#1e293b;'></body></html>")

    def update_content(self, html_body):
        if self._web is not None:
            self._web.setHtml(f"<html><body style='background:#1e293b;'>{html_body}</body></html>")


class FloatingMarkdown:
    """Markdown block kept as draw instructions until it is stamped."""

    def __init__(self, markdown, html_body, text_width, *, font_family="", font_size=24, color="black", css_color="#000000", opacity=100):
        self.markdown = markdown
        self.html_body = html_body
        self.text_width = max(120, int(text_width))
        self.font_family = font_family or "Arial"
        self.font_size = max(1, min(200, int(font_size)))
        self.color = QColor(color)
        self.css_color = css_color
        self.opacity = max(0, min(100, int(opacity)))
        self.pos = QPointF(50, 50)
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.rotation = 0.0
        self._dragging = False
        self._drag_offset = QPointF()
        self._doc = None
        self._content_rect = None

    @property
    def active(self):
        return bool(self.markdown.strip())

    def clear(self):
        self.markdown = ""
        self.html_body = ""
        self._doc = None
        self._content_rect = None
        self._dragging = False
        self._drag_offset = QPointF()

    def _document_css(self):
        css_font_family = self.font_family.replace("\\", "").replace("'", "") or "Arial"
        return (
            f"body {{ font-family: '{css_font_family}', Arial, sans-serif; font-size: {self.font_size}px; "
            f"line-height: 1.55; color: {self.css_color}; margin: 0; }}"
        )

    def _ensure_document(self):
        if self._doc is None:
            self._doc = QTextDocument()
            body_html = _basic_markdown_to_html(self.markdown) if self.html_body == self.markdown else self.html_body
            full_html = f"<html><head><style>{self._document_css()}</style></head><body>{body_html}</body></html>"
            self._doc.setHtml(full_html)
        return self._doc

    def _local_size(self):
        if not self.active:
            return (0, 0)
        doc = self._ensure_document()
        return (doc.size().width(), doc.size().height())

    def trim_to_content(self, padding=0):
        if not self.active:
            return
        doc = self._ensure_document()
        size = doc.size()
        image_w = max(1, math.ceil(size.width()))
        image_h = max(1, math.ceil(size.height()))
        image = QImage(image_w, image_h, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        doc.drawContents(painter)
        painter.end()
        content_rect = _alpha_content_rect_from_image(image, padding)
        if content_rect.isNull() or content_rect == QRect(0, 0, image_w, image_h):
            self._content_rect = None
            return
        self._content_rect = QRectF(content_rect)
        self.pos = QPointF(
            max(0, self.pos.x() + content_rect.x() * self.scale_x),
            max(0, self.pos.y() + content_rect.y() * self.scale_y),
        )

    def _transform(self):
        if not self.active:
            return QTransform()
        local_w, local_h = self._local_size()
        w = local_w * self.scale_x
        h = local_h * self.scale_y
        t = QTransform()
        t.translate(self.pos.x(), self.pos.y())
        t.translate(w / 2, h / 2)
        t.rotate(self.rotation)
        t.translate(-w / 2, -h / 2)
        t.scale(self.scale_x, self.scale_y)
        return t

    def bounding_rect(self):
        if not self.active:
            return QRectF()
        local_w, local_h = self._local_size()
        return self._transform().mapRect(QRectF(0, 0, local_w, local_h))

    def _center(self):
        local_w, local_h = self._local_size()
        return self._transform().map(QPointF(local_w / 2, local_h / 2))

    def _set_center(self, center):
        self.pos = QPointF(0, 0)
        relative_center = self._center()
        self.pos = QPointF(center.x() - relative_center.x(), center.y() - relative_center.y())

    def rotate_around(self, anchor, angle_delta):
        old_center = self._center()
        rad = math.radians(angle_delta)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        dx, dy = old_center.x() - anchor.x(), old_center.y() - anchor.y()
        new_center = QPointF(
            anchor.x() + dx * cos_a - dy * sin_a,
            anchor.y() + dx * sin_a + dy * cos_a,
        )
        self.rotation = (self.rotation + angle_delta) % 360
        self._set_center(new_center)

    def scale_around(self, anchor, factor):
        if not self.active or factor <= 0:
            return
        old_center = self._center()
        min_scale, max_scale = 0.05, 8.0
        if factor > 1:
            actual_factor = min(factor, max_scale / max(abs(self.scale_x), 0.001), max_scale / max(abs(self.scale_y), 0.001))
        else:
            actual_factor = max(factor, min_scale / max(abs(self.scale_x), 0.001), min_scale / max(abs(self.scale_y), 0.001))
        self.scale_x = max(min_scale, min(max_scale, self.scale_x * actual_factor))
        self.scale_y = max(min_scale, min(max_scale, self.scale_y * actual_factor))
        new_center = QPointF(
            anchor.x() + (old_center.x() - anchor.x()) * actual_factor,
            anchor.y() + (old_center.y() - anchor.y()) * actual_factor,
        )
        self._set_center(new_center)

    def contains(self, pos):
        if not self.active:
            return False
        try:
            inv, ok = self._transform().inverted()
            if not ok:
                return self.bounding_rect().contains(pos)
            local = inv.map(pos)
            local_w, local_h = self._local_size()
            return QRectF(0, 0, local_w, local_h).contains(local)
        except Exception:
            return False

    def on_press(self, pos, button, alt_held=False, shift_held=False):
        if not self.active or button != Qt.MouseButton.LeftButton:
            return False
        if not self.contains(pos):
            return False
        self._dragging = True
        self._drag_offset = QPointF(pos.x() - self.pos.x(), pos.y() - self.pos.y())
        return True

    def on_move(self, pos, alt_held=False, shift_held=False):
        if not self.active or not self._dragging:
            return False
        self.pos = QPointF(pos.x() - self._drag_offset.x(), pos.y() - self._drag_offset.y())
        return True

    def on_release(self, button, alt_held=False, shift_held=False):
        if not self.active or button != Qt.MouseButton.LeftButton:
            return False
        self._dragging = False
        return True

    def on_wheel(self, delta, shift_held=False, anchor=None):
        if not self.active or delta == 0:
            return False
        factor = 1.1 if delta > 0 else 0.9
        if anchor is None:
            anchor = self._center()
        self.scale_around(anchor, factor)
        return True

    def draw(self, painter, *, show_box=False):
        if not self.active:
            return
        doc = self._ensure_document()
        local_w, local_h = self._local_size()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setTransform(self._transform(), combine=True)
        if self.opacity < 100:
            painter.setOpacity(self.opacity / 100)
        doc.drawContents(painter)
        painter.restore()
        if show_box:
            painter.setPen(QPen(QColor("#6366f1"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(0, 0, local_w, local_h))

    def to_transformed_pixmap(self):
        if not self.active:
            return None
        br = self.bounding_rect().toAlignedRect()
        if br.isEmpty():
            return None
        pixmap = QPixmap(max(1, br.width()), max(1, br.height()))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.translate(-br.x(), -br.y())
        self.draw(painter, show_box=False)
        painter.end()
        return (pixmap, QPointF(float(br.x()), float(br.y())))

    def stamp(self, target_pixmap):
        if not self.active:
            return
        painter = QPainter(target_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.draw(painter, show_box=False)
        painter.end()
        self.clear()


class Canvas(QWidget):
    """Main drawing surface widget."""

    mode_changed = pyqtSignal(object)
    python_figure_selected = pyqtSignal(object)
    zoom_changed = pyqtSignal(float)
    slide_changed = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._slides: list[SlideModel] = [SlideModel()]
        self._slide_idx = 0
        self._last_page_scroll_time = 0.0
        self.engine = DrawingEngine()
        self.image_handler = ImageHandler()
        self.mode = DrawMode.FREEHAND
        self._zoom = 1.0
        self._scroll_x = 0.0
        self._scroll_y = 0.0
        self._pen_color = QColor("black")
        self._current_path = QPainterPath()
        self._is_drawing = False
        self._last_point = QPointF()
        self._floating_image: QPixmap | None = None
        self._floating_pos = QPointF()
        self._floating_scale = 1.0
        self._floating_rotation = 0.0
        self._floating_markdown: FloatingMarkdown | None = None
        self._selection_rect: QRectF | None = None
        self._selection_start: QPointF | None = None
        self._is_selecting = False
        self._selection_mode = "rect"
        self._selected_elements: list = []
        self._is_moving_selection: bool = False
        self._is_resizing_selection: bool = False
        self._resize_corner: str = ""
        self._move_start_pos: QPointF = QPointF()
        self._elements_clipboard: list = []
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self._eraser_width = 20
        self._type_live_timer = QTimer(self)
        self._type_live_timer.setSingleShot(True)
        self._type_live_timer.timeout.connect(self._type_live_render)
        self.show_grid = True
        self.grid_h = True
        self.grid_v = True
        self.grid_size = 35
        self.grid_spacing = 35
        self.grid_thickness = 1
        self.snap_to_grid = False
        self.texstudio_layout_mode = "inline"
        self.editable_text_mode = False
        self._current_free_tool_name = ""
        self._current_custom_tool_name = ""
        self._type_render_view = None
        self._markdown_prewarm_started = False
        self._current_line_mode = None
        self._current_curve_mode = None
        self._current_polygon_mode = None
        # Shape drawing state (two-point drag)
        self._shape_start: QPointF | None = None
        self._shape_end: QPointF | None = None
        self._is_shape_drawing = False
        # Free selection path
        self._free_select_path: QPainterPath | None = None
        self._is_free_selecting = False
        # Multi-point click state for geometry/free tools
        self._multi_click_points: list[QPointF] = []
        self._is_multi_clicking = False

    @property
    def _slide(self):
        return self._slides[self._slide_idx]

    @property
    def slide_count(self) -> int:
        return len(self._slides)

    @property
    def current_slide_number(self) -> int:
        return self._slide_idx + 1

    @property
    def _current_slide(self) -> SlideModel:
        return self._slides[self._slide_idx]

    @property
    def pen_color(self):
        return self._pen_color

    @pen_color.setter
    def pen_color(self, color):
        self._pen_color = QColor(color)

    @property
    def eraser_width(self):
        return self._eraser_width

    @eraser_width.setter
    def eraser_width(self, val):
        self._eraser_width = max(1, int(val))

    @property
    def _zoom(self):
        return self.__zoom

    @_zoom.setter
    def _zoom(self, val):
        new_val = max(0.1, min(10.0, float(val)))
        if getattr(self, "_Canvas__zoom", None) != new_val:
            self.__zoom = new_val
            if hasattr(self, "zoom_changed"):
                self.zoom_changed.emit(new_val)

    def _horizontal_offset(self) -> float:
        """Return horizontal pixel offset to center the slide when it fits in window."""
        slide = getattr(self, "_current_slide", None)
        if slide is None:
            return 0.0
        sw = getattr(slide, "width", 1080)
        rendered_w = sw * self._zoom
        if self.width() >= rendered_w:
            return (self.width() - rendered_w) / 2.0
        return 0.0

    def _max_scroll_x(self) -> float:
        """Return max allowed scroll_x. If slide fits in window width, return 0.0."""
        slide = getattr(self, "_current_slide", None)
        if slide is None:
            return 0.0
        sw = getattr(slide, "width", 1080)
        vw = self.width() / self._zoom
        return max(0.0, sw - vw)

    def _next_page_banner_rect(self) -> QRectF:
        """Return the bounding rect of the Next Page / New Page link banner below the slide."""
        slide = getattr(self, "_current_slide", None)
        sw = getattr(slide, "width", 1080) if slide else 1080
        sh = getattr(slide, "height", 1528) if slide else 1528
        bw = min(sw * 0.75, 780.0)
        bh = 60.0
        bx = (sw - bw) / 2.0
        by = sh + 28.0
        return QRectF(bx, by, bw, bh)

    @property
    def _scroll_x(self):
        return self.__scroll_x

    @_scroll_x.setter
    def _scroll_x(self, val):
        max_x = self._max_scroll_x()
        if max_x <= 0.0:
            self.__scroll_x = 0.0
        else:
            self.__scroll_x = max(0.0, min(max_x, float(val)))

    @property
    def _scroll_y(self):
        return self.__scroll_y

    @_scroll_y.setter
    def _scroll_y(self, val):
        self.__scroll_y = max(0.0, float(val))

    def pan_by(self, dx: float, dy: float) -> None:
        max_x = self._max_scroll_x()
        if max_x > 0:
            self._scroll_x = max(0.0, min(max_x, self._scroll_x + float(dx) / self._zoom))
        else:
            self._scroll_x = 0.0
        self._scroll_y = max(0.0, self._scroll_y + float(dy) / self._zoom)
        self.update()

    def zoom_in(self, factor: float = 1.25) -> None:
        """Zoom in centered on viewport center."""
        vw = self.width() / self._zoom
        vh = self.height() / self._zoom
        cx = self._scroll_x + vw / 2.0
        cy = self._scroll_y + vh / 2.0
        new_zoom = max(0.1, min(10.0, self._zoom * factor))
        self._zoom = new_zoom
        new_vw = self.width() / new_zoom
        new_vh = self.height() / new_zoom
        self._scroll_x = max(0.0, cx - new_vw / 2.0)
        self._scroll_y = max(0.0, cy - new_vh / 2.0)
        self.update()

    def zoom_out(self, factor: float = 1.25) -> None:
        """Zoom out centered on viewport center."""
        vw = self.width() / self._zoom
        vh = self.height() / self._zoom
        cx = self._scroll_x + vw / 2.0
        cy = self._scroll_y + vh / 2.0
        new_zoom = max(0.1, min(10.0, self._zoom / factor))
        self._zoom = new_zoom
        new_vw = self.width() / new_zoom
        new_vh = self.height() / new_zoom
        self._scroll_x = max(0.0, cx - new_vw / 2.0)
        self._scroll_y = max(0.0, cy - new_vh / 2.0)
        self.update()

    def set_zoom_level(self, zoom: float) -> None:
        """Set an exact zoom level (e.g. 1.0 for 100%)."""
        self._zoom = max(0.1, min(10.0, float(zoom)))
        self.update()

    def zoom_reset(self) -> None:
        """Reset zoom to 100% (1.0)."""
        self._zoom = 1.0
        self._scroll_x = 0.0
        self._scroll_y = 0.0
        self.update()

    def fit_to_window(self) -> None:
        """Fit the whole slide inside the current canvas window (Fit to Screen) with zero horizontal shift."""
        slide = self._current_slide
        sw = getattr(slide, "width", 1080)
        sh = getattr(slide, "height", 1528)
        cw = max(100, self.width() - 32)
        ch = max(100, self.height() - 32)
        fit_zoom = min(cw / sw, ch / sh)
        self._zoom = max(0.1, min(10.0, fit_zoom))
        self._scroll_x = 0.0
        self._scroll_y = 0.0
        self.update()

    def fit_to_width(self) -> None:
        """Fit the slide width to the canvas window width."""
        slide = self._current_slide
        sw = getattr(slide, "width", 1080)
        cw = max(100, self.width() - 24)
        fit_zoom = cw / sw
        self._zoom = max(0.1, min(10.0, fit_zoom))
        self._scroll_x = 0.0
        self.update()

    def fit_to_height(self) -> None:
        """Fit the slide height to the canvas window height."""
        slide = self._current_slide
        sh = getattr(slide, "height", 1528)
        ch = max(100, self.height() - 24)
        fit_zoom = ch / sh
        self._zoom = max(0.1, min(10.0, fit_zoom))
        self._scroll_y = 0.0
        self.update()

    def set_slide_dimensions(self, width: int, height: int, apply_all: bool = True) -> None:
        """Set slide dimensions for the current slide or all slides."""
        w = max(200, int(width))
        h = max(200, int(height))
        targets = self._slides if apply_all else [self._current_slide]
        for s in targets:
            if hasattr(s, "resize"):
                s.resize(w, h)
            else:
                s.width = w
                s.height = h
        self.update()

    def undo(self):
        cancel_pending = getattr(self, '_cancel_pending_interaction', None)
        if callable(cancel_pending) and cancel_pending():
            return
        if hasattr(self, '_floating_markdown_active') and self._floating_markdown_active():
            if getattr(self, '_floating_markdown', None) is not None:
                self._floating_markdown.clear()
            self._floating_markdown = None
            if hasattr(self, '_clear_transient_dirty'):
                self._clear_transient_dirty()
            self.update()
            return
        if getattr(self, 'image_handler', None) and getattr(self.image_handler, 'active', False):
            was_lifted_selection = getattr(self, '_floating_commit_on_left_release', False)
            was_pending_python_figure = getattr(self, '_pending_python_figure_element', None) is not None
            self.image_handler.clear()
            self._pending_text_markdown = None
            self._pending_python_figure_element = None
            self._floating_commit_on_left_release = False
            self._floating_commit_right_click_only = False
            if hasattr(self, '_clear_transient_dirty'):
                self._clear_transient_dirty()
            if was_lifted_selection and not was_pending_python_figure:
                self._slide.undo()
                if hasattr(self._slide, 'expand_if_needed'):
                    self._slide.expand_if_needed(self.width(), self.height())
            self.update()
            return
        if hasattr(self, '_slide') and self._slide.undo():
            if hasattr(self._slide, 'expand_if_needed'):
                self._slide.expand_if_needed(self.width(), self.height())
            if hasattr(self, '_clear_transient_dirty'):
                self._clear_transient_dirty()
            self.update()

    def redo(self):
        if hasattr(self, '_cancel_type_editor'):
            self._cancel_type_editor()
        if hasattr(self, '_cancel_type_render'):
            self._cancel_type_render()
        if hasattr(self, '_slide') and self._slide.redo():
            if hasattr(self._slide, 'expand_if_needed'):
                self._slide.expand_if_needed(self.width(), self.height())
            if hasattr(self, '_clear_transient_dirty'):
                self._clear_transient_dirty()
            self.update()

    def has_selection(self):
        r = self._selection_rect
        if r is not None and not r.isEmpty() and r.width() >= 5 and r.height() >= 5:
            return True
        if getattr(self, "_sel_path", None) is not None and not self._sel_path.isEmpty():
            return True
        return False

    def has_ai_selection_source(self):
        if self.has_selection():
            return True
        slide = getattr(self, "_slide", getattr(self, "_current_slide", None))
        if slide:
            if getattr(slide, "elements", []):
                return True
            if hasattr(slide, "pixmap") and not slide.pixmap.isNull():
                return True
        if getattr(self, "_floating_image", None) and not self._floating_image.isNull():
            return True
        return False


    def clear_selection(self):
        self._selection_rect = None
        self._selection_start = None
        self._sel_path = None
        self._selected_elements = []
        self._is_selecting = False
        self._is_moving_selection = False
        self._is_resizing_selection = False
        self._resize_corner = ""
        self.unsetCursor()
        self.update()

    def delete_selection(self):
        r = self._selection_rect
        if r is None and getattr(self, "_sel_path", None) is not None:
            r = self._sel_path.boundingRect()
        if r is None:
            return
        slide = getattr(self, "_slide", getattr(self, "_current_slide", None))
        if slide:
            if hasattr(slide, "pixmap") and not slide.pixmap.isNull():
                p = QPainter(slide.pixmap)
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                p.fillRect(r.toRect(), QColor(0, 0, 0, 255))
                p.end()
            if hasattr(slide, "elements"):
                new_elements = []
                for el in slide.elements:
                    if getattr(el, "kind", "") == "stroke" and hasattr(el, "path"):
                        if el.path.boundingRect().intersects(r):
                            continue
                    new_elements.append(el)
                slide.elements = new_elements
            if hasattr(slide, "save_state"):
                slide.save_state()
        self.clear_selection()
        self.update()

    def delete_active_selection(self) -> bool:
        if self._selected_elements:
            to_remove = set(id(el) for el in self._selected_elements)
            self._current_slide.elements = [
                el for el in self._current_slide.elements if id(el) not in to_remove
            ]
            self._selected_elements.clear()
            if hasattr(self._current_slide, "_stroke_pixmap"):
                self._current_slide._stroke_pixmap.fill(Qt.GlobalColor.transparent)
            self._current_slide.save_state()
            self.clear_selection()
            self.update()
            return True
        if self.has_selection():
            self.delete_selection()
            return True
        if getattr(self, "_floating_image", None) is not None:
            self._floating_image = None
            self.update()
            return True
        return False

    def escape_action(self) -> bool:
        """Handle Escape key: clear active selection or deselect."""
        if self.has_selection() or self._selected_elements:
            self.clear_selection()
            return True
        return False

    def copy_selection(self):
        """Copy selected elements to internal clipboard."""
        if not self._selected_elements:
            return
        from models.elements import deep_copy_elements
        self._elements_clipboard = deep_copy_elements(self._selected_elements)

    def paste_selection(self, offset: QPointF = QPointF(30, 30)):
        """Paste elements from internal clipboard or image from OS clipboard."""
        # 1. First check if system clipboard contains an image
        clip = QApplication.clipboard()
        img = clip.image()
        if not img.isNull():
            self.insert_image_pixmap(QPixmap.fromImage(img))
            return

        # 2. Check internal element clipboard
        if not getattr(self, "_elements_clipboard", None):
            return
        from models.elements import deep_copy_elements
        pasted = deep_copy_elements(self._elements_clipboard)
        t = QTransform()
        t.translate(offset.x(), offset.y())
        for el in pasted:
            el.id = str(uuid.uuid4())
            if getattr(el, "kind", "") == "stroke":
                el.path = t.map(el.path)
            elif getattr(el, "kind", "") == "text":
                el.anchor = QPointF(el.anchor.x() + offset.x(), el.anchor.y() + offset.y())
            elif getattr(el, "kind", "") == "image":
                el.pos = QPointF(el.pos.x() + offset.x(), el.pos.y() + offset.y())
            elif getattr(el, "kind", "") == "python_figure":
                el.pos = QPointF(el.pos.x() + offset.x(), el.pos.y() + offset.y())
            self._current_slide.add_element(el)

        self._selected_elements = pasted
        if pasted:
            union_rect = QRectF()
            for el in pasted:
                eb = self._element_bounds(el)
                union_rect = union_rect.united(eb) if not union_rect.isEmpty() else eb
            self._selection_rect = union_rect.adjusted(-6, -6, 6, 6)
        self._current_slide.save_state()
        self.update()

    def duplicate_selection(self):
        """Duplicate currently selected elements with slight offset."""
        if not self._selected_elements:
            return
        self.copy_selection()
        self.paste_selection(QPointF(25, 25))

    def apply_color_to_selection(self, color: QColor) -> bool:
        """Apply newly chosen color to selected strokes or text."""
        if not self._selected_elements:
            return False
        for el in self._selected_elements:
            if getattr(el, "kind", "") == "stroke":
                el.color = QColor(color)
            elif getattr(el, "kind", "") == "text":
                el.color = QColor(color)
                if hasattr(el, "invalidate_cache"):
                    el.invalidate_cache()
        self._current_slide.save_state()
        self.update()
        return True

    def apply_width_to_selection(self, width: float) -> bool:
        """Apply newly chosen stroke width to selected strokes."""
        if not self._selected_elements:
            return False
        for el in self._selected_elements:
            if getattr(el, "kind", "") == "stroke":
                el.width = float(width)
        self._current_slide.save_state()
        self.update()
        return True

    def insert_image_pixmap(self, pix: QPixmap, center_pos: QPointF | None = None):
        """Insert or replace an editable ImageElement directly on the slide."""
        if pix.isNull():
            return

        # If an existing ImageElement is currently selected, modify it in-place!
        selected_img = next((el for el in self._selected_elements if getattr(el, "kind", "") == "image"), None)
        if selected_img is not None:
            selected_img.source = pix
            self._current_slide.save_state()
            eb = self._element_bounds(selected_img)
            self._selection_rect = eb.adjusted(-4, -4, 4, 4)
            self.update()
            return selected_img

        sw = getattr(self._current_slide, "width", 1080)
        sh = getattr(self._current_slide, "height", 1528)
        max_w = sw * 0.8
        max_h = sh * 0.8
        scale = 1.0
        if pix.width() > max_w or pix.height() > max_h:
            scale = min(max_w / max(1, pix.width()), max_h / max(1, pix.height()))

        target_w = pix.width() * scale
        target_h = pix.height() * scale

        if center_pos is None:
            view_cx = self._scroll_x + (self.width() / max(0.1, self._zoom)) / 2
            view_cy = self._scroll_y + (self.height() / max(0.1, self._zoom)) / 2
            px = max(20.0, view_cx - target_w / 2)
            py = max(20.0, view_cy - target_h / 2)
        else:
            px = center_pos.x() - target_w / 2
            py = center_pos.y() - target_h / 2

        el = ImageElement.make(
            source=pix,
            pos=QPointF(px, py),
            scale_x=scale,
            scale_y=scale,
            rotation=0.0,
        )
        self._current_slide.add_element(el)
        self._current_slide.save_state()

        # Automatically select the new image so user can drag or resize it
        self.mode = DrawMode.SELECT_RECT
        self._selected_elements = [el]
        self._selection_rect = QRectF(px, py, target_w, target_h).adjusted(-4, -4, 4, 4)
        self.update()
        return el

    def _element_bounds(self, el) -> QRectF:
        """Calculate tight bounding box of any CanvasElement."""
        if getattr(el, "kind", "") == "stroke":
            w = max(2.0, getattr(el, "width", 3.0) or 3.0)
            return el.path.boundingRect().adjusted(-w, -w, w, w)
        elif getattr(el, "kind", "") == "text":
            anchor = getattr(el, "anchor", QPointF(0, 0))
            if getattr(el, "_pixmap_cache", None) and not el._pixmap_cache.isNull():
                return QRectF(anchor.x(), anchor.y(), el._pixmap_cache.width(), el._pixmap_cache.height())
            return QRectF(anchor.x(), anchor.y(), 120, 40)
        elif getattr(el, "kind", "") == "image":
            pos = getattr(el, "pos", QPointF(0, 0))
            if getattr(el, "source", None) and not el.source.isNull():
                sx = getattr(el, "scale_x", 1.0) or 1.0
                sy = getattr(el, "scale_y", 1.0) or 1.0
                return QRectF(pos.x(), pos.y(), el.source.width() * sx, el.source.height() * sy)
            return QRectF(pos.x(), pos.y(), 60, 60)
        elif getattr(el, "kind", "") == "python_figure":
            pos = getattr(el, "pos", QPointF(0, 0))
            if getattr(el, "_pixmap_cache", None) and not el._pixmap_cache.isNull():
                return QRectF(pos.x(), pos.y(), el._pixmap_cache.width(), el._pixmap_cache.height())
            return QRectF(pos.x(), pos.y(), 200, 150)
        return QRectF()

    def _hit_test_corner_handle(self, pos: QPointF, rect: QRectF) -> str | None:
        tol = max(8.0, 12.0 / max(0.1, self._zoom))
        corners = {
            "tl": rect.topLeft(),
            "tr": rect.topRight(),
            "bl": rect.bottomLeft(),
            "br": rect.bottomRight(),
        }
        for corner_name, pt in corners.items():
            if math.hypot(pos.x() - pt.x(), pos.y() - pt.y()) <= tol:
                return corner_name
        return None

    def _translate_selected_elements(self, dx: float, dy: float):
        if hasattr(self._current_slide, "_stroke_pixmap"):
            self._current_slide._stroke_pixmap.fill(Qt.GlobalColor.transparent)
        t = QTransform()
        t.translate(dx, dy)
        for el in self._selected_elements:
            if getattr(el, "kind", "") == "stroke":
                el.path = t.map(el.path)
            elif getattr(el, "kind", "") == "text":
                el.anchor = QPointF(el.anchor.x() + dx, el.anchor.y() + dy)
            elif getattr(el, "kind", "") == "image":
                el.pos = QPointF(el.pos.x() + dx, el.pos.y() + dy)
            elif getattr(el, "kind", "") == "python_figure":
                el.pos = QPointF(el.pos.x() + dx, el.pos.y() + dy)

    def _scale_selected_elements(self, sx: float, sy: float, center: QPointF):
        if hasattr(self._current_slide, "_stroke_pixmap"):
            self._current_slide._stroke_pixmap.fill(Qt.GlobalColor.transparent)
        t = QTransform()
        t.translate(center.x(), center.y())
        t.scale(sx, sy)
        t.translate(-center.x(), -center.y())
        for el in self._selected_elements:
            if getattr(el, "kind", "") == "stroke":
                el.path = t.map(el.path)
            elif getattr(el, "kind", "") == "text":
                el.anchor = t.map(el.anchor)
                el.font_size = max(8, int(el.font_size * ((abs(sx) + abs(sy)) / 2)))
                if hasattr(el, "invalidate_cache"):
                    el.invalidate_cache()
            elif getattr(el, "kind", "") == "image":
                el.pos = t.map(el.pos)
                el.scale_x *= sx
                el.scale_y *= sy
            elif getattr(el, "kind", "") == "python_figure":
                el.pos = t.map(el.pos)
                el.scale_x *= sx
                el.scale_y *= sy

    def _find_selected_elements(self):
        if not self._selection_rect or self._selection_rect.isEmpty():
            self._selected_elements = []
            return
        r = self._selection_rect
        matched = []
        for el in self._current_slide.elements:
            eb = self._element_bounds(el)
            if eb.intersects(r):
                matched.append(el)
        self._selected_elements = matched
        if matched:
            union_rect = QRectF()
            for el in matched:
                eb = self._element_bounds(el)
                union_rect = union_rect.united(eb) if not union_rect.isEmpty() else eb
            if not union_rect.isEmpty():
                self._selection_rect = union_rect.adjusted(-6, -6, 6, 6)

    def _handle_resize_selection(self, pos: QPointF):
        if not self._selection_rect or self._selection_rect.isEmpty():
            return
        old_r = QRectF(self._selection_rect)
        c = self._resize_corner

        left = pos.x() if "l" in c else old_r.left()
        right = pos.x() if "r" in c else old_r.right()
        top = pos.y() if "t" in c else old_r.top()
        bottom = pos.y() if "b" in c else old_r.bottom()

        if right - left < 10 or bottom - top < 10:
            return

        new_r = QRectF(left, top, right - left, bottom - top)
        sx = new_r.width() / max(1.0, old_r.width())
        sy = new_r.height() / max(1.0, old_r.height())

        fixed_x = old_r.right() if "l" in c else old_r.left()
        fixed_y = old_r.bottom() if "t" in c else old_r.top()
        fixed_pt = QPointF(fixed_x, fixed_y)

        self._scale_selected_elements(sx, sy, fixed_pt)
        self._selection_rect = new_r

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        pos = self._canvas_pos(event.position())
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                file_path = url.toLocalFile()
                if file_path:
                    ext = Path(file_path).suffix.lower()
                    if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.gif', '.tif', '.tiff'):
                        reader = QImageReader(file_path)
                        reader.setAutoTransform(True)
                        img = reader.read()
                        if not img.isNull():
                            self.insert_image_pixmap(QPixmap.fromImage(img), center_pos=pos)
                            event.acceptProposedAction()
                            return
        if mime.hasImage():
            img = mime.imageData()
            if img:
                pix = QPixmap.fromImage(img) if isinstance(img, QImage) else img
                if not pix.isNull():
                    self.insert_image_pixmap(pix, center_pos=pos)
                    event.acceptProposedAction()
                    return
        super().dropEvent(event)

    def sel_pixmap_for_export(self):
        r = self._selection_rect
        if r is None and getattr(self, "_sel_path", None) is not None:
            r = self._sel_path.boundingRect()
        if r is None or r.isEmpty() or r.width() < 2 or r.height() < 2:
            return QPixmap()
        aligned = r.toAlignedRect()
        pix = QPixmap(aligned.size())
        pix.fill(Qt.GlobalColor.white)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.translate(-aligned.x(), -aligned.y())
        slide = getattr(self, "_slide", getattr(self, "_current_slide", None))
        if slide:
            if hasattr(slide, "pixmap") and not slide.pixmap.isNull():
                p.drawPixmap(0, 0, slide.pixmap)
            for el in getattr(slide, "elements", []):
                self._draw_element(p, el)
        if getattr(self, "_floating_image", None) and not self._floating_image.isNull():
            p.save()
            p.translate(self._floating_pos)
            p.rotate(self._floating_rotation)
            p.scale(self._floating_scale, self._floating_scale)
            p.drawPixmap(0, 0, self._floating_image)
            p.restore()
        p.end()
        return pix

    def ai_selection_source_pixmap(self):
        # 1. Explicit selection exists
        pix = self.sel_pixmap_for_export()
        if pix and not pix.isNull() and pix.width() >= 5 and pix.height() >= 5:
            return pix

        # 2. No selection box drawn: auto-detect bounding box of drawn elements
        slide = getattr(self, "_slide", getattr(self, "_current_slide", None))
        rect = QRectF()
        if slide and getattr(slide, "elements", []):
            for el in slide.elements:
                if hasattr(el, "path") and not el.path.isEmpty():
                    rect = rect.united(el.path.boundingRect())

        if not rect.isEmpty() and rect.width() >= 5 and rect.height() >= 5:
            padded = rect.adjusted(-24, -24, 24, 24)
            aligned = padded.toAlignedRect()
            out_pix = QPixmap(aligned.size())
            out_pix.fill(Qt.GlobalColor.white)
            p = QPainter(out_pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.translate(-aligned.x(), -aligned.y())
            if hasattr(slide, "pixmap") and not slide.pixmap.isNull():
                p.drawPixmap(0, 0, slide.pixmap)
            for el in getattr(slide, "elements", []):
                self._draw_element(p, el)
            p.end()
            return out_pix

        # 3. Fallback: render entire visible canvas viewport
        w = max(100, self.width())
        h = max(100, self.height())
        viewport_pix = QPixmap(w, h)
        viewport_pix.fill(Qt.GlobalColor.white)
        p = QPainter(viewport_pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if slide:
            if hasattr(slide, "pixmap") and not slide.pixmap.isNull():
                p.drawPixmap(0, 0, slide.pixmap)
            for el in getattr(slide, "elements", []):
                self._draw_element(p, el)
        if getattr(self, "_floating_image", None) and not self._floating_image.isNull():
            p.save()
            p.translate(self._floating_pos)
            p.rotate(self._floating_rotation)
            p.scale(self._floating_scale, self._floating_scale)
            p.drawPixmap(0, 0, self._floating_image)
            p.restore()
        p.end()
        return viewport_pix



    def set_floating_image(self, pixmap):
        self._floating_image = pixmap
        self._floating_pos = QPointF(self._scroll_x + 50, self._scroll_y + 50)
        self._floating_scale = 1.0
        self._floating_rotation = 0.0
        self.update()

    def set_pen_style(self, style, pattern=None, idx=0):
        self.engine.pen_style = style
        self.engine.pen_dash_pattern = list(pattern) if pattern else None
        self.engine.pen_style_idx = idx

    def add_slide_after_current(self):
        new_slide = SlideModel(width=getattr(self._current_slide, "width", 1080), height=getattr(self._current_slide, "height", 1528))
        self._slides.insert(self._slide_idx + 1, new_slide)
        self._slide_idx += 1
        self.update()

    def append_slide_with_pixmap(
        self,
        pix: "QPixmap",
        *,
        top_fill_width: bool = False,
        insert_at: "int | None" = None,
    ) -> int:
        """Append (or insert) a new slide pre-loaded with *pix*.

        Returns the index of the newly created slide.
        """
        slide_w = getattr(self._current_slide, "width", 1080)
        slide_h = getattr(self._current_slide, "height", 1528)
        new_slide = SlideModel(width=slide_w, height=slide_h)
        if pix and not pix.isNull():
            dest = QPixmap(slide_w, slide_h)
            dest.fill(Qt.GlobalColor.white)
            from PyQt6.QtGui import QPainter as _P
            pp = _P(dest)

            margin_x = 40
            margin_y = 40
            avail_w = slide_w - (margin_x * 2)

            draw_pix = pix
            if draw_pix.width() > avail_w:
                draw_pix = draw_pix.scaledToWidth(avail_w, Qt.TransformationMode.SmoothTransformation)
            elif top_fill_width and draw_pix.width() < avail_w * 0.75:
                target_w = min(int(avail_w * 0.85), draw_pix.width() * 2)
                draw_pix = draw_pix.scaledToWidth(target_w, Qt.TransformationMode.SmoothTransformation)

            draw_x = max(margin_x, (slide_w - draw_pix.width()) // 2)
            draw_y = margin_y
            pp.drawPixmap(draw_x, draw_y, draw_pix)
            pp.end()
            new_slide.pixmap = dest
            new_slide.save_state()

        if insert_at is not None and 0 <= insert_at <= len(self._slides):
            self._slides.insert(insert_at, new_slide)
            idx = insert_at
        else:
            self._slides.append(new_slide)
            idx = len(self._slides) - 1
        self.update()
        return idx

    def go_to_slide(self, index: int) -> bool:
        if 0 <= index < len(self._slides):
            self._cancel_type_editor() if hasattr(self, '_cancel_type_editor') else None
            self._cancel_type_render() if hasattr(self, '_cancel_type_render') else None
            self._stamp_and_save_current() if hasattr(self, '_stamp_and_save_current') else None
            self._clear_transient_dirty() if hasattr(self, '_clear_transient_dirty') else None
            self._slide_idx = index
            self._scroll_y = 0
            self._scroll_x = 0
            if hasattr(self, "slide_changed"):
                self.slide_changed.emit(self.current_slide_number, self.slide_count)
            self.update()
            return True
        return False

    def go_next(self):
        self._cancel_type_editor() if hasattr(self, '_cancel_type_editor') else None
        self._cancel_type_render() if hasattr(self, '_cancel_type_render') else None
        self._stamp_and_save_current() if hasattr(self, '_stamp_and_save_current') else None
        self._clear_transient_dirty() if hasattr(self, '_clear_transient_dirty') else None
        if self._slide_idx < len(self._slides) - 1:
            self._slide_idx += 1
        else:
            self._add_slide() if hasattr(self, '_add_slide') else self.add_slide_after_current()
        self._scroll_y = 0
        self._scroll_x = 0
        if hasattr(self, "slide_changed"):
            self.slide_changed.emit(self.current_slide_number, self.slide_count)
        self.update()

    def go_prev(self):
        if self._slide_idx == 0:
            return False
        self._cancel_type_editor() if hasattr(self, '_cancel_type_editor') else None
        self._cancel_type_render() if hasattr(self, '_cancel_type_render') else None
        self._stamp_and_save_current() if hasattr(self, '_stamp_and_save_current') else None
        self._clear_transient_dirty() if hasattr(self, '_clear_transient_dirty') else None
        self._slide_idx -= 1
        self._scroll_y = 0
        self._scroll_x = 0
        if hasattr(self, "slide_changed"):
            self.slide_changed.emit(self.current_slide_number, self.slide_count)
        self.update()
        return True

    def go_first(self):
        if self._slide_idx == 0:
            return False
        self._cancel_type_editor() if hasattr(self, '_cancel_type_editor') else None
        self._cancel_type_render() if hasattr(self, '_cancel_type_render') else None
        self._stamp_and_save_current() if hasattr(self, '_stamp_and_save_current') else None
        self._clear_transient_dirty() if hasattr(self, '_clear_transient_dirty') else None
        self._slide_idx = 0
        self._scroll_y = 0
        self._scroll_x = 0
        if hasattr(self, "slide_changed"):
            self.slide_changed.emit(self.current_slide_number, self.slide_count)
        self.update()
        return True

    def go_last(self):
        last_idx = len(self._slides) - 1
        if self._slide_idx == last_idx:
            return False
        self._cancel_type_editor() if hasattr(self, '_cancel_type_editor') else None
        self._cancel_type_render() if hasattr(self, '_cancel_type_render') else None
        self._stamp_and_save_current() if hasattr(self, '_stamp_and_save_current') else None
        self._clear_transient_dirty() if hasattr(self, '_clear_transient_dirty') else None
        self._slide_idx = last_idx
        self._scroll_y = 0
        self._scroll_x = 0
        if hasattr(self, "slide_changed"):
            self.slide_changed.emit(self.current_slide_number, self.slide_count)
        self.update()
        return True

    def delete_current_slide(self):
        self._cancel_type_editor() if hasattr(self, '_cancel_type_editor') else None
        self._cancel_type_render() if hasattr(self, '_cancel_type_render') else None
        if len(self._slides) <= 1:
            self.clear_board() if hasattr(self, 'clear_board') else None
            return False
        if hasattr(self, 'image_handler') and self.image_handler.active:
            self.image_handler.clear()
            self._pending_text_markdown = None
            self._pending_python_figure_element = None
            self._floating_commit_right_click_only = False
        if hasattr(self, '_floating_markdown_active') and self._floating_markdown_active():
            if getattr(self, '_floating_markdown', None) is not None:
                self._floating_markdown.clear()
            self._floating_markdown = None
        del self._slides[self._slide_idx]
        if self._slide_idx >= len(self._slides):
            self._slide_idx = len(self._slides) - 1
        self._clear_transient_dirty() if hasattr(self, '_clear_transient_dirty') else None
        self._scroll_y = 0
        self._scroll_x = 0
        if hasattr(self, "slide_changed"):
            self.slide_changed.emit(self.current_slide_number, self.slide_count)
        self.update()
        return True

    def render_slide(self, painter, rect, slide):
        """Render a slide onto a QPainter for export."""
        painter.drawPixmap(int(rect.x()), int(rect.y()), slide.pixmap)

    def commit_floating_for_selection_mode(self):
        if self._floating_markdown and self._floating_markdown.active:
            self._stamp_floating_markdown()
        if self._floating_image and not self._floating_image.isNull():
            self._stamp_floating_image()

    def replace_ai_selection_with_pixmap(self, pixmap):
        if pixmap.isNull():
            return False
        self.set_floating_image(pixmap)
        return True

    def replace_ai_selection_target_with_floating_pixmap(self, pixmap, target=None):
        return self.replace_ai_selection_with_pixmap(pixmap)

    def replace_ai_selection_target_with_pixmap(self, pixmap, target=None):
        return self.replace_ai_selection_with_pixmap(pixmap)

    def apply_texstudio_type_settings(self):
        pass

    def _stamp_floating_image(self):
        if self._floating_image and not self._floating_image.isNull():
            slide = self._current_slide
            el = ImageElement(
                pos=QPointF(self._floating_pos),
                scale_x=self._floating_scale,
                scale_y=self._floating_scale,
                rotation=self._floating_rotation,
            )
            slide.add_element(el)
            slide.save_state()
            self._floating_image = None
            self.update()

    def _stamp_floating_markdown(self):
        if self._floating_markdown and self._floating_markdown.active:
            slide = self._current_slide
            el = TextElement(
                markdown=self._floating_markdown.markdown,
                anchor=QPointF(self._floating_markdown.pos),
                font_size=self._floating_markdown.font_size,
                color=QColor(self._floating_markdown.color),
                opacity=self._floating_markdown.opacity,
            )
            slide.add_element(el)
            slide.save_state()
            self._floating_markdown.clear()
            self.update()

    def _type_live_render(self):
        pass

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        board_color = getattr(self, "board_color", None)
        if not board_color or not isinstance(board_color, QColor) or not board_color.isValid():
            board_color = QColor("#ffffff")

        # Workspace background outside the slide paper
        is_dark = board_color.lightness() < 128
        workspace_bg = QColor("#1e1e24") if is_dark else QColor("#f1f5f9")
        p.fillRect(self.rect(), workspace_bg)

        offset_x = self._horizontal_offset()
        p.save()
        p.translate(offset_x - self._scroll_x * self._zoom, -self._scroll_y * self._zoom)
        p.scale(self._zoom, self._zoom)
        slide = self._current_slide
        sw = getattr(slide, "width", 1080)
        sh = getattr(slide, "height", 1528)

        # Slide card drop shadow and boundary
        p.fillRect(QRectF(3, 4, sw, sh), QColor(0, 0, 0, 18))
        p.fillRect(QRectF(6, 8, sw, sh), QColor(0, 0, 0, 8))
        p.setPen(QPen(QColor("#cbd5e1" if not is_dark else "#475569"), 1.2 / self._zoom))
        p.setBrush(board_color)
        p.drawRect(QRectF(0, 0, sw, sh))
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Writing grid (ក្រឡាការ៉ូ) directly on the slide surface
        if getattr(self, "show_grid", True) and (getattr(self, "grid_h", True) or getattr(self, "grid_v", True)):
            self._draw_grid_on_slide(p, sw, sh, board_color)

        p.setBrush(Qt.BrushStyle.NoBrush)

        if not slide.pixmap.isNull():
            p.drawPixmap(0, 0, slide.pixmap)
        for el in slide.elements:
            self._draw_element(p, el)
        if self._is_drawing and not self._current_path.isEmpty():
            p.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(self._pen_color, self.engine.pen_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPath(self._current_path)
        if self._floating_image and not self._floating_image.isNull():
            p.save()
            p.translate(self._floating_pos)
            p.rotate(self._floating_rotation)
            p.scale(self._floating_scale, self._floating_scale)
            p.drawPixmap(0, 0, self._floating_image)
            p.restore()
        if self._floating_markdown and self._floating_markdown.active:
            self._floating_markdown.draw(p, show_box=True)
        if self._selection_rect and not self._selection_rect.isEmpty():
            p.setPen(QPen(QColor("#4f46e5"), 1.8 / self._zoom, Qt.PenStyle.DashLine))
            p.setBrush(QBrush(QColor(79, 70, 229, 20)))
            p.drawRect(self._selection_rect)
            hs = max(6.0, 8.0 / self._zoom)
            half = hs / 2.0
            p.setBrush(QBrush(QColor("#ffffff")))
            p.setPen(QPen(QColor("#4f46e5"), 1.5 / self._zoom))
            for pt in (
                self._selection_rect.topLeft(),
                self._selection_rect.topRight(),
                self._selection_rect.bottomLeft(),
                self._selection_rect.bottomRight(),
                QPointF(self._selection_rect.center().x(), self._selection_rect.top()),
                QPointF(self._selection_rect.center().x(), self._selection_rect.bottom()),
                QPointF(self._selection_rect.left(), self._selection_rect.center().y()),
                QPointF(self._selection_rect.right(), self._selection_rect.center().y()),
            ):
                p.drawRect(QRectF(pt.x() - half, pt.y() - half, hs, hs))
        if self._is_free_selecting and self._free_select_path:
            p.setPen(QPen(QColor("#6366f1"), 2 / self._zoom, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(self._free_select_path)
        # Shape preview while dragging
        if self._is_shape_drawing and self._shape_start and self._shape_end:
            preview_path = self._build_shape_path(self._shape_start, self._shape_end)
            if not preview_path.isEmpty():
                preview_pen = QPen(self._pen_color, self.engine.pen_width)
                preview_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                preview_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                preview_pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(preview_pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(preview_path)
        # Multi-point click preview (geometry/free tools)
        if self._is_multi_clicking and self._multi_click_points:
            point_pen = QPen(QColor("#f43f5e"), 2 / self._zoom)
            p.setPen(point_pen)
            p.setBrush(QBrush(QColor(244, 63, 94, 120)))
            for pt in self._multi_click_points:
                p.drawEllipse(pt, 5 / self._zoom, 5 / self._zoom)
            if len(self._multi_click_points) >= 2:
                line_pen = QPen(QColor("#6366f1"), 1.5 / self._zoom, Qt.PenStyle.DashLine)
                p.setPen(line_pen)
                for i in range(len(self._multi_click_points) - 1):
                    p.drawLine(self._multi_click_points[i], self._multi_click_points[i + 1])

        # ── Link / Divider to Next Page ("កន្លែងតំណទៅទំព័រថ្មី") ──
        has_next = self._slide_idx < len(self._slides) - 1
        banner_rect = self._next_page_banner_rect()

        p.save()
        # Dashed page separator line
        p.setPen(QPen(QColor("#94a3b8"), 1.5, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(40, sh + 14), QPointF(sw - 40, sh + 14))

        # Link banner card
        border_color = QColor("#2563eb") if has_next else QColor("#059669")
        bg_color = QColor("#eff6ff") if has_next else QColor("#ecfdf5")
        p.setPen(QPen(border_color, 2.0))
        p.setBrush(bg_color)
        p.drawRoundedRect(banner_rect, 10, 10)

        font = QFont("Khmer OS", 13, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor("#1e40af") if has_next else QColor("#047857"))

        curr_num = self._slide_idx + 1
        total = len(self._slides)
        if has_next:
            label_text = f"⬇  ទំព័របន្ទាប់ (ទំព័រ {curr_num + 1} / {total}) — ចុច ឬអូសចុះក្រោមដើម្បីបើក  ⬇"
        else:
            label_text = f"➕  តំណទៅទំព័រថ្មី (ទំព័រ {curr_num + 1}) — ចុច ឬអូសចុះក្រោមដើម្បីបន្ថែមទំព័រថ្មី  ➕"
        p.drawText(banner_rect, Qt.AlignmentFlag.AlignCenter, label_text)

        if has_next:
            next_slide = self._slides[self._slide_idx + 1]
            next_y = banner_rect.bottom() + 20
            p.setPen(QPen(QColor("#cbd5e1"), 1.2))
            p.setBrush(QColor("#ffffff"))
            p.drawRect(QRectF(0, next_y, sw, 300))
            if not next_slide.pixmap.isNull():
                p.drawPixmap(0, int(next_y), next_slide.pixmap, 0, 0, sw, 300)
            p.setPen(QPen(QColor("#475569"), 1.0))
            p.setFont(QFont("Khmer OS", 11, QFont.Weight.Bold))
            p.drawText(QRectF(20, next_y + 12, 300, 26), Qt.AlignmentFlag.AlignLeft, f"ទំព័រទី {curr_num + 1}")

        p.restore()

        p.restore()
        p.end()

    def _ensure_markdown_render_view(self):
        if QWebEngineView is None:
            return None
        view = self._type_render_view
        if view is not None:
            return view
        view = QWebEngineView(self)
        view.setWindowFlags(Qt.WindowType.Widget)
        view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        view.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        view.setGeometry(-100000, -100000, 1, 1)
        try:
            view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        except Exception:
            pass
        if QWebEngineSettings is not None:
            try:
                settings = view.settings()
                settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
                settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            except Exception:
                pass
        view.show()
        self._type_render_view = view
        return view

    def _prewarm_markdown_renderer(self) -> None:
        self._markdown_prewarm_started = True
        if not self.isVisible():
            QTimer.singleShot(500, self._prewarm_markdown_renderer)
            return
        view = self._ensure_markdown_render_view()
        if view is None:
            return
        shell_path = _get_mathjax_shell_path() if '_get_mathjax_shell_path' in globals() else None
        if shell_path is None:
            return

        def on_loaded(ok: bool) -> None:
            if view is not self._type_render_view:
                return
            if ok and hasattr(self, '_poll_shell_ready'):
                self._poll_shell_ready(0)

        try:
            view.loadFinished.disconnect()
        except TypeError:
            pass
        view.loadFinished.connect(on_loaded)
        try:
            view.load(QUrl.fromLocalFile(str(shell_path)))
        except RuntimeError:
            self._type_render_view = None

    def _draw_grid_on_slide(self, p: QPainter, sw: int, sh: int, board_color: QColor) -> None:
        """Draw school notebook / graph writing grid (ក្រឡាការ៉ូ) on slide surface."""
        if not getattr(self, "show_grid", True):
            return
        if not getattr(self, "grid_h", True) and not getattr(self, "grid_v", True):
            return

        spacing = max(10, getattr(self, "grid_spacing", 35) or 35)
        thickness = max(1.0, float(getattr(self, "grid_thickness", 1) or 1))

        is_dark = board_color.lightness() < 128
        if is_dark:
            # White translucent chalk lines for dark chalkboard
            grid_pen = QPen(QColor(255, 255, 255, 55), thickness / self._zoom)
        else:
            # High-visibility, crisp graph-paper cyan-blue lines for white/light paper
            grid_pen = QPen(QColor(180, 208, 235, 185), thickness / self._zoom)

        p.setPen(grid_pen)

        # Vertical grid lines
        if getattr(self, "grid_v", True) or getattr(self, "show_grid", True):
            x = spacing
            while x < sw:
                p.drawLine(QPointF(x, 0), QPointF(x, sh))
                x += spacing

        # Horizontal grid lines
        if getattr(self, "grid_h", True) or getattr(self, "show_grid", True):
            y = spacing
            while y < sh:
                p.drawLine(QPointF(0, y), QPointF(sw, y))
                y += spacing

    def _draw_grid(self, p, rect=None):
        slide = getattr(self, "_current_slide", None)
        sw = getattr(slide, "width", 1920) if slide else 1920
        sh = getattr(slide, "height", 1080) if slide else 1080
        board_color = getattr(self, "board_color", QColor("#ffffff"))
        self._draw_grid_on_slide(p, sw, sh, board_color)

    def _draw_element(self, p, el):
        if el.kind == "stroke":
            p.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(QColor(el.color), el.width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setOpacity(el.opacity / 100 if hasattr(el, "opacity") else 1.0)
            p.drawPath(el.path)
            p.setOpacity(1.0)
        elif el.kind == "text":
            if el._pixmap_cache and not el._pixmap_cache.isNull():
                p.drawPixmap(int(el.anchor.x()), int(el.anchor.y()), el._pixmap_cache)
        elif el.kind == "image":
            if hasattr(el, "source") and el.source and not el.source.isNull():
                p.save()
                p.translate(el.pos.x(), el.pos.y())
                if getattr(el, "rotation", 0.0):
                    p.rotate(el.rotation)
                sx = getattr(el, "scale_x", 1.0) or 1.0
                sy = getattr(el, "scale_y", 1.0) or 1.0
                p.scale(sx, sy)
                p.drawPixmap(0, 0, el.source)
                p.restore()
        elif el.kind == "python_figure":
            if hasattr(el, "_pixmap_cache") and el._pixmap_cache and not el._pixmap_cache.isNull():
                p.save()
                p.translate(el.pos.x(), el.pos.y())
                p.drawPixmap(0, 0, el._pixmap_cache)
                p.restore()

    # ── Shape mode helpers ─────────────────────────────────────────────

    _TWO_POINT_MODES = {
        DrawMode.LINE, DrawMode.ARROW, DrawMode.ARROW_DOUBLE,
        DrawMode.ARROW_CLOSED, DrawMode.BEZIER,
        DrawMode.CIRCLE, DrawMode.SEMICIRCLE, DrawMode.ELLIPSE,
        DrawMode.RECTANGLE, DrawMode.TRIANGLE, DrawMode.PARALLELOGRAM,
    }

    def _is_two_point_mode(self) -> bool:
        return self.mode in self._TWO_POINT_MODES

    def _build_shape_path(self, p1: QPointF, p2: QPointF) -> QPainterPath:
        """Build a QPainterPath for the current shape mode from two points."""
        import math
        path = QPainterPath()
        mode = self.mode

        if mode == DrawMode.LINE:
            path.moveTo(p1)
            path.lineTo(p2)

        elif mode in (DrawMode.ARROW, DrawMode.ARROW_DOUBLE,
                      DrawMode.ARROW_CLOSED):
            path.moveTo(p1)
            path.lineTo(p2)
            # Draw arrowhead
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()
            length = math.hypot(dx, dy)
            if length > 0:
                arrow_size = min(15, length * 0.3)
                angle = math.atan2(dy, dx)
                a1 = angle + math.radians(150)
                a2 = angle - math.radians(150)
                tip1 = QPointF(p2.x() + arrow_size * math.cos(a1),
                               p2.y() + arrow_size * math.sin(a1))
                tip2 = QPointF(p2.x() + arrow_size * math.cos(a2),
                               p2.y() + arrow_size * math.sin(a2))
                path.moveTo(tip1)
                path.lineTo(p2)
                path.lineTo(tip2)
                if mode in (DrawMode.ARROW_DOUBLE,):
                    # Second arrowhead at p1
                    a3 = angle + math.radians(30)
                    a4 = angle - math.radians(30)
                    tip3 = QPointF(p1.x() + arrow_size * math.cos(a3),
                                   p1.y() + arrow_size * math.sin(a3))
                    tip4 = QPointF(p1.x() + arrow_size * math.cos(a4),
                                   p1.y() + arrow_size * math.sin(a4))
                    path.moveTo(tip3)
                    path.lineTo(p1)
                    path.lineTo(tip4)

        elif mode == DrawMode.RECTANGLE:
            rect = QRectF(p1, p2).normalized()
            path.addRect(rect)

        elif mode == DrawMode.CIRCLE:
            cx = (p1.x() + p2.x()) / 2
            cy = (p1.y() + p2.y()) / 2
            radius = math.hypot(p2.x() - p1.x(), p2.y() - p1.y()) / 2
            path.addEllipse(QPointF(cx, cy), radius, radius)

        elif mode == DrawMode.ELLIPSE:
            rect = QRectF(p1, p2).normalized()
            path.addEllipse(rect)

        elif mode == DrawMode.SEMICIRCLE:
            rect = QRectF(p1, p2).normalized()
            path.arcMoveTo(rect, 0)
            path.arcTo(rect, 0, 180)

        elif mode == DrawMode.TRIANGLE:
            rect = QRectF(p1, p2).normalized()
            top = QPointF(rect.center().x(), rect.top())
            bl = QPointF(rect.left(), rect.bottom())
            br = QPointF(rect.right(), rect.bottom())
            path.moveTo(top)
            path.lineTo(br)
            path.lineTo(bl)
            path.closeSubpath()

        elif mode == DrawMode.PARALLELOGRAM:
            rect = QRectF(p1, p2).normalized()
            offset = rect.width() * 0.2
            tl = QPointF(rect.left() + offset, rect.top())
            tr = QPointF(rect.right(), rect.top())
            br = QPointF(rect.right() - offset, rect.bottom())
            bl = QPointF(rect.left(), rect.bottom())
            path.moveTo(tl)
            path.lineTo(tr)
            path.lineTo(br)
            path.lineTo(bl)
            path.closeSubpath()

        elif mode == DrawMode.BEZIER:
            # Quadratic bezier with control point above midpoint
            mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
            dy = abs(p2.y() - p1.y())
            dx = abs(p2.x() - p1.x())
            ctrl = QPointF(mid.x(), mid.y() - max(dy, dx) * 0.5)
            path.moveTo(p1)
            path.quadTo(ctrl, p2)

        return path

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.RightButton and not (self.mode in (DrawMode.CUSTOM_FREE, DrawMode.CUSTOM_POLYGON) and self._multi_click_points)):
            self._is_panning = True
            self._pan_start = event.position()
            self._pan_scroll_start_x = self._scroll_x
            self._pan_scroll_start_y = self._scroll_y
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        pos = self._canvas_pos(event.position())
        if event.button() == Qt.MouseButton.LeftButton:
            banner_rect = self._next_page_banner_rect()
            if banner_rect.contains(pos):
                self.go_next()
                event.accept()
                return
            if self.mode in (DrawMode.SELECT_RECT, DrawMode.SELECT_FREE):
                if self._selection_rect and not self._selection_rect.isEmpty():
                    corner = self._hit_test_corner_handle(pos, self._selection_rect)
                    if corner:
                        self._is_resizing_selection = True
                        self._resize_corner = corner
                        self._move_start_pos = pos
                        self.setCursor(Qt.CursorShape.SizeFDiagCursor if corner in ("tl", "br") else Qt.CursorShape.SizeBDiagCursor)
                        event.accept()
                        return
                    if self._selection_rect.contains(pos):
                        self._is_moving_selection = True
                        self._move_start_pos = pos
                        self.setCursor(Qt.CursorShape.SizeAllCursor)
                        event.accept()
                        return
                self._selected_elements.clear()
                if self.mode == DrawMode.SELECT_RECT:
                    self._selection_start = pos
                    self._is_selecting = True
                    self._selection_rect = None
                elif self.mode == DrawMode.SELECT_FREE:
                    self._free_select_path = QPainterPath()
                    self._free_select_path.moveTo(pos)
                    self._is_free_selecting = True
                    self._selection_rect = None
            elif self.mode == DrawMode.FREEHAND or self.mode == DrawMode.HIGHLIGHT:
                self._is_drawing = True
                self._current_path = QPainterPath()
                self._current_path.moveTo(pos)
                self._last_point = pos
            elif self.mode == DrawMode.ERASER:
                self._erase_at(pos)
            elif self.mode == DrawMode.TYPE:
                self._start_type_mode(pos)
            elif self.mode in (DrawMode.CUSTOM_GEOMETRY, DrawMode.CUSTOM_FREE, DrawMode.CUSTOM_POLYGON):
                self._handle_multi_click(pos)
            elif self._is_two_point_mode():
                self._shape_start = pos
                self._shape_end = pos
                self._is_shape_drawing = True
        elif event.button() == Qt.MouseButton.RightButton:
            # Right-click finishes free/polygon tools
            if self.mode in (DrawMode.CUSTOM_FREE, DrawMode.CUSTOM_POLYGON) and self._multi_click_points:
                self._finish_multi_click()
        super().mousePressEvent(event)

    def _handle_multi_click(self, pos: QPointF):
        """Handle a click for multi-point tools (geometry, free polygon, freehand)."""
        self._multi_click_points.append(pos)
        self._is_multi_clicking = True

        tool_name = self.engine.current_custom_tool
        tool = self.engine.custom_tools.get(tool_name)
        if not tool:
            tool = self.engine.geometry_tools.get(tool_name)
        if not tool:
            tool = self.engine.free_tools.get(tool_name)
        if not tool:
            return

        n_points = tool.get('n_points', -1)
        if n_points > 0 and len(self._multi_click_points) >= n_points:
            # Got enough points, build and commit
            self._finish_multi_click()
        else:
            self.update()

    def _finish_multi_click(self):
        """Finish multi-point tool and commit the shape."""
        if not self._multi_click_points:
            return

        tool_name = self.engine.current_custom_tool
        tool = self.engine.custom_tools.get(tool_name)
        if not tool:
            tool = self.engine.geometry_tools.get(tool_name)
        if not tool:
            tool = self.engine.free_tools.get(tool_name)
        if not tool:
            self._multi_click_points.clear()
            self._is_multi_clicking = False
            return

        fn = tool.get('fn')
        if not fn:
            self._multi_click_points.clear()
            self._is_multi_clicking = False
            return

        min_pts = tool.get('min_points', tool.get('n_points', 2))
        if min_pts > 0 and len(self._multi_click_points) < min_pts:
            self._multi_click_points.clear()
            self._is_multi_clicking = False
            self.update()
            return

        # Build shape path
        try:
            import inspect
            sig = inspect.signature(fn)
            if 'closed' in sig.parameters:
                closed = getattr(self.engine, 'free_close_enabled', True)
                path = fn(self._multi_click_points, closed=closed)
            else:
                path = fn(self._multi_click_points)
        except Exception:
            path = QPainterPath()

        if not path.isEmpty():
            el = StrokeElement(
                path=path,
                color=QColor(self._pen_color),
                width=self.engine.pen_width,
                mode=tool_name,
            )
            self._current_slide.add_element(el)
            self._current_slide.paint_stroke_onto_cache(
                lambda p: self._paint_stroke(p, el)
            )
            self._current_slide.save_state()

        self._multi_click_points.clear()
        self._is_multi_clicking = False
        self.update()

    def mouseMoveEvent(self, event):
        if getattr(self, "_is_panning", False):
            delta = event.position() - self._pan_start
            max_x = self._max_scroll_x()
            if max_x > 0:
                self._scroll_x = max(0.0, min(max_x, self._pan_scroll_start_x - delta.x() / self._zoom))
            else:
                self._scroll_x = 0.0
            slide = self._current_slide
            sh = getattr(slide, "height", 1080)
            vh = self.height() / self._zoom
            max_y = max(0.0, sh + 150 - vh)
            self._scroll_y = max(0.0, min(max_y, self._pan_scroll_start_y - delta.y() / self._zoom))
            self.update()
            event.accept()
            return
        pos = self._canvas_pos(event.position())
        if self._is_moving_selection:
            delta = pos - self._move_start_pos
            self._move_start_pos = pos
            self._translate_selected_elements(delta.x(), delta.y())
            if self._selection_rect:
                self._selection_rect.translate(delta.x(), delta.y())
            self.update()
            event.accept()
            return
        elif self._is_resizing_selection:
            self._handle_resize_selection(pos)
            self.update()
            event.accept()
            return

        # Cursor feedback when hovering in selection mode
        if not (event.buttons() & Qt.MouseButton.LeftButton) and self.mode in (DrawMode.SELECT_RECT, DrawMode.SELECT_FREE):
            if self._selection_rect and not self._selection_rect.isEmpty():
                corner = self._hit_test_corner_handle(pos, self._selection_rect)
                if corner in ("tl", "br"):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                elif corner in ("tr", "bl"):
                    self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                elif self._selection_rect.contains(pos):
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
                else:
                    self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)

        if not self._is_drawing and not self._is_selecting and not self._is_shape_drawing:
            banner_rect = self._next_page_banner_rect()
            if banner_rect.contains(pos):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif self.cursor().shape() == Qt.CursorShape.PointingHandCursor:
                self.unsetCursor()
        if self._is_selecting and self._selection_start:
            p1 = QPointF(min(self._selection_start.x(), pos.x()), min(self._selection_start.y(), pos.y()))
            p2 = QPointF(max(self._selection_start.x(), pos.x()), max(self._selection_start.y(), pos.y()))
            self._selection_rect = QRectF(p1, p2)
            self.update()
        elif self._is_free_selecting and self._free_select_path:
            self._free_select_path.lineTo(pos)
            self.update()
        elif self._is_drawing:
            self._current_path.lineTo(pos)
            self._last_point = pos
            self.update()
        elif self._is_shape_drawing:
            self._shape_end = pos
            self.update()
        elif self.mode == DrawMode.ERASER and event.buttons() & Qt.MouseButton.LeftButton:
            self._erase_at(pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, "_is_panning", False):
            if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
                self._is_panning = False
                self.unsetCursor()
                event.accept()
                return
        pos = self._canvas_pos(event.position())
        if self._is_moving_selection:
            self._is_moving_selection = False
            self.unsetCursor()
            self._current_slide.save_state()
            self.update()
            event.accept()
            return
        if self._is_resizing_selection:
            self._is_resizing_selection = False
            self.unsetCursor()
            self._current_slide.save_state()
            self.update()
            event.accept()
            return
        if self._is_selecting:
            self._is_selecting = False
            if self._selection_rect and self._selection_rect.width() > 3 and self._selection_rect.height() > 3:
                self._find_selected_elements()
                self.update()
        elif self._is_free_selecting:
            self._is_free_selecting = False
            if self._free_select_path:
                self._free_select_path.closeSubpath()
                self._selection_rect = self._free_select_path.boundingRect()
                self._find_selected_elements()
                self.update()
        elif self._is_shape_drawing:
            self._is_shape_drawing = False
            self._shape_end = pos
            if self._shape_start and self._shape_end:
                import math
                dist = math.hypot(
                    self._shape_end.x() - self._shape_start.x(),
                    self._shape_end.y() - self._shape_start.y()
                )
                if dist > 3:
                    shape_path = self._build_shape_path(self._shape_start, self._shape_end)
                    if not shape_path.isEmpty():
                        el = StrokeElement(
                            path=shape_path,
                            color=QColor(self._pen_color),
                            width=self.engine.pen_width,
                            mode=self.mode.name.lower(),
                        )
                        self._current_slide.add_element(el)
                        self._current_slide.paint_stroke_onto_cache(
                            lambda p: self._paint_stroke(p, el)
                        )
                        self._current_slide.save_state()
            self._shape_start = None
            self._shape_end = None
            self.update()
        elif self._is_drawing:
            self._is_drawing = False
            if not self._current_path.isEmpty():
                el = StrokeElement(
                    path=QPainterPath(self._current_path),
                    color=QColor(self._pen_color),
                    width=self.engine.pen_width,
                    mode="freehand",
                )
                self._current_slide.add_element(el)
                self._current_slide.paint_stroke_onto_cache(lambda p: self._paint_stroke(p, el))
                self._current_slide.save_state()
            self._current_path = QPainterPath()
            self.update()
        super().mouseReleaseEvent(event)

    def _paint_stroke(self, painter, el):
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(el.color), el.width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(el.path)

    def wheelEvent(self, event):
        delta_y = event.angleDelta().y()
        delta_x = event.angleDelta().x()
        pos = self._canvas_pos(event.position())
        # Scale selected elements with mouse wheel when hovering over selection
        if self.mode in (DrawMode.SELECT_RECT, DrawMode.SELECT_FREE) and self._selection_rect and self._selection_rect.contains(pos) and self._selected_elements:
            factor = 1.08 if delta_y > 0 else 0.92
            center = self._selection_rect.center()
            self._scale_selected_elements(factor, factor, center)
            t = QTransform()
            t.translate(center.x(), center.y())
            t.scale(factor, factor)
            t.translate(-center.x(), -center.y())
            self._selection_rect = t.mapRect(self._selection_rect)
            self._current_slide.save_state()
            self.update()
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.1 if delta_y > 0 else 0.9
            self._zoom = max(0.1, min(10.0, self._zoom * factor))
        else:
            slide = getattr(self, "_current_slide", None)
            sh = getattr(slide, "height", 1080) if slide else 1080
            vh = self.height() / self._zoom

            # Smooth page down transition when scrolling down past the link banner
            now = time.time()
            if delta_y < -40 and (now - getattr(self, "_last_page_scroll_time", 0.0) > 0.45):
                if self._scroll_y + vh >= sh + 30:
                    self._last_page_scroll_time = now
                    self.go_next()
                    return
            elif delta_y > 40 and (now - getattr(self, "_last_page_scroll_time", 0.0) > 0.45):
                if self._scroll_y <= 5 and self._slide_idx > 0:
                    self._last_page_scroll_time = now
                    self.go_prev()
                    sh_prev = getattr(self._current_slide, "height", 1080)
                    self._scroll_y = max(0.0, sh_prev - vh + 50)
                    return

            if delta_y != 0:
                max_y = max(0.0, sh + 150 - vh)
                self._scroll_y = max(0.0, min(max_y, self._scroll_y - delta_y * 0.8 / self._zoom))

            # Horizontal scroll: strictly locked if slide fits window horizontally (zero wobbling!)
            max_x = self._max_scroll_x()
            if max_x > 0 and delta_x != 0:
                self._scroll_x = max(0.0, min(max_x, self._scroll_x - delta_x * 0.8 / self._zoom))
            else:
                self._scroll_x = 0.0

        self.update()

    def _canvas_pos(self, pos):
        offset_x = self._horizontal_offset()
        return QPointF((pos.x() - offset_x) / self._zoom + self._scroll_x, pos.y() / self._zoom + self._scroll_y)

    def _erase_at(self, pos):
        slide = self._current_slide
        eraser_rect = QRectF(pos.x() - self._eraser_width / 2, pos.y() - self._eraser_width / 2, self._eraser_width, self._eraser_width)
        to_remove = []
        for el in slide.elements:
            if el.kind == "stroke":
                if el.path.controlPointRect().intersects(eraser_rect):
                    to_remove.append(el)
        for el in to_remove:
            slide.remove_element(el.id)
        if to_remove:
            slide.rebuild_stroke_pixmap()
            slide.save_state()
            self.update()

    def _start_type_mode(self, pos):
        """Show text input dialog and render text at clicked position."""
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getMultiLineText(
            self, "បញ្ជូលអត្ថបទ", "សូមវាយអត្ថបទ:", ""
        )
        if ok and text.strip():
            from PyQt6.QtGui import QFont, QFontMetrics
            font_size = max(12, self.engine.pen_width * 3)
            font = QFont("Arial", font_size)
            # Create text as a path
            path = QPainterPath()
            path.addText(pos.x(), pos.y(), font, text)
            if not path.isEmpty():
                el = StrokeElement(
                    path=path,
                    color=QColor(self._pen_color),
                    width=1,
                    mode="type",
                )
                self._current_slide.add_element(el)
                self._current_slide.paint_stroke_onto_cache(
                    lambda p: self._paint_type_stroke(p, el, font)
                )
                self._current_slide.save_state()
                self.update()

    def _paint_type_stroke(self, painter, el, font=None):
        """Paint a type element with fill instead of stroke."""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(el.color)))
        painter.drawPath(el.path)
