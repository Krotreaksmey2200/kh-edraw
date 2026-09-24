"""
dialogs/python_figure_dialog.py
Editor + preview dialog for compiling code-based figures.

UI follows `dialogs/tikz_ai_dialog.py`: QSplitter with a code editor on the
left and (preview + parameter sliders) on the right.  Rendering happens on
a QThread worker so dragging sliders never blocks the UI.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Callable

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QRegularExpression,
    QSize,
    QSizeF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetricsF,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
    QShortcut,
    QSyntaxHighlighter,
    QTextCursor,
    QTextCharFormat,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.app_settings import (
    load_figure_template_code_overrides,
    load_figure_template_hidden_keys,
    load_figure_template_title_overrides,
    load_figure_templates,
    save_figure_template_code_overrides,
    save_figure_template_hidden_keys,
    save_figure_template_title_overrides,
    save_figure_templates,
)
from core.i18n import t
from core.python_figure import PythonFigureRenderWorker, SandboxError, get_service, start_python_figure_worker


def _bleed_transparent_pixels(source: QImage) -> QImage:
    """Prepare alpha pixels before scaling so Qt does not interpolate black."""
    if source.isNull():
        return QImage(source)
    img = source.convertToFormat(QImage.Format.Format_RGBA8888)
    try:
        bits = img.bits()
        bits.setsize(img.sizeInBytes())
        data = memoryview(bits).cast("B")
        stride = img.bytesPerLine()
        for y in range(img.height()):
            row = y * stride
            for x in range(img.width()):
                i = row + x * 4
                if data[i + 3] == 0:
                    data[i] = 255
                    data[i + 1] = 255
                    data[i + 2] = 255
    except Exception:
        pass
    return img


class _TransparentPreviewLabel(QLabel):
    """Label that shows a checkerboard pattern behind transparent images."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checker_pixmap = self._make_checker()

    @staticmethod
    def _make_checker() -> QPixmap:
        pix = QPixmap(16, 16)
        p = QPainter(pix)
        p.fillRect(0, 0, 8, 8, QColor("#e0e0e0"))
        p.fillRect(8, 0, 8, 8, QColor("#ffffff"))
        p.fillRect(0, 8, 8, 8, QColor("#ffffff"))
        p.fillRect(8, 8, 8, 8, QColor("#e0e0e0"))
        p.end()
        return pix

    def paintEvent(self, event):
        p = QPainter(self)
        p.setBrush(QBrush(self._checker_pixmap))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(self.rect())
        super().paintEvent(event)


_PY_KEYWORDS = (
    "def class if elif else for while in not and or is return lambda import from as "
    "try except finally raise with yield pass break continue True False None "
    "global nonlocal del assert async await"
).split()
_PY_BUILTINS = (
    "print len range abs min max sum sorted list dict tuple set frozenset "
    "int float str bool round pow enumerate zip map filter reversed any all "
    "isinstance issubclass repr type"
).split()


class _PythonHighlighter(QSyntaxHighlighter):
    """Simple Python syntax highlighter for the code editor."""

    def highlightBlock(self, text):
        for keyword in _PY_KEYWORDS:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#9333ea"))
            fmt.setFontWeight(QFont.Weight.Bold)
            expression = QRegularExpression(rf"\b{keyword}\b")
            it = expression.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)
        for builtin in _PY_BUILTINS:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#0891b2"))
            expression = QRegularExpression(rf"\b{builtin}\b")
            it = expression.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)
        # Strings
        fmt_str = QTextCharFormat()
        fmt_str.setForeground(QColor("#059669"))
        it = QRegularExpression(r"""('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")""").globalMatch(text)
        while it.hasNext():
            match = it.next()
            self.setFormat(match.capturedStart(), match.capturedLength(), fmt_str)
        # Comments
        fmt_comment = QTextCharFormat()
        fmt_comment.setForeground(QColor("#94a3b8"))
        fmt_comment.setFontItalic(True)
        idx = _latex_comment_index(text) if "%" in text else -1
        if idx >= 0:
            self.setFormat(idx, len(text) - idx, fmt_comment)


class _LatexHighlighter(QSyntaxHighlighter):
    """Simple LaTeX syntax highlighter."""

    def highlightBlock(self, text):
        fmt_cmd = QTextCharFormat()
        fmt_cmd.setForeground(QColor("#9333ea"))
        it = QRegularExpression(r"\\[a-zA-Z]+").globalMatch(text)
        while it.hasNext():
            match = it.next()
            self.setFormat(match.capturedStart(), match.capturedLength(), fmt_cmd)
        idx = _latex_comment_index(text)
        if idx >= 0:
            fmt_comment = QTextCharFormat()
            fmt_comment.setForeground(QColor("#94a3b8"))
            fmt_comment.setFontItalic(True)
            self.setFormat(idx, len(text) - idx, fmt_comment)


def _latex_comment_index(text: str) -> int:
    i = 0
    while i < len(text):
        if text[i] == "%" and (i == 0 or text[i - 1] != "\\"):
            return i
        i += 1
    return -1


def _inside_string(text: str, pos: int) -> bool:
    """Cheap heuristic: count un-escaped quotes before `pos`."""
    in_single = False
    in_double = False
    i = 0
    while i < pos:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "'" and not in_double:
            in_single = not in_single
        elif c == '"' and not in_single:
            in_double = not in_double
        i += 1
    return in_single or in_double


class _CodeEditor(QPlainTextEdit):
    """Code editor with line numbers and syntax highlighting."""

    def __init__(self, parent=None, highlighter_class=None):
        super().__init__(parent)
        self.setFont(QFont("Consolas", 11))
        self.setTabStopDistance(40)
        if highlighter_class:
            self._highlighter = highlighter_class(self.document())


# Template strings
_TEMPLATE_TIKZ_DYNAMIC_1 = r"""\documentclass[tikz,border=1mm]{standalone}
\usepackage[utf8]{vietnam}
\usepackage{amsmath,amssymb}
\usepackage{tikz}
\usetikzlibrary{arrows.meta,calc,intersections,patterns,patterns.meta,positioning,shapes.geometric,angles,quotes}
\begin{document}
\foreach \i in{-90,-85,...,90}{
\begin{tikzpicture}[magenta, line width=2pt]
\clip(-1,-1)rectangle(12,12);
\hv(20,-\i)
\end{tikzpicture}
}
\end{document}
"""

_TEMPLATE_EDRAW_DYNAMIC_1 = """# ed is the built-in drawing API passed to eDraw(ed, p).
PARAMS = {
    "i": {"min": -90, "max": 90, "step": 5, "value": -90, "label": "i"},
}

def eDraw(ed, p):
    ed.axis("off")
    ed.view(-1, 12, -1, 12)
    phi = (math.sqrt(5) - 1) / 2
    angle = math.radians(-p["i"])

    def draw_hv(level, x, y, angle):
        if level <= 0:
            return
        ed.sector(x, y, 4, 180, 90, fill="#67e8f9", stroke="#d946ef")
        ed.rect(x, y, 4, 4, fill=None, stroke="#d946ef")
        nx = x + 4 * math.cos(math.radians(angle))
        ny = y + 4 + 4 * math.sin(math.radians(angle))
        draw_hv(level - 1, nx, ny, angle)

    draw_hv(20, 0, 0, 0)
"""

_TEMPLATE_TIKZ_STATIC_1 = r"""\documentclass[tikz,border=1mm]{standalone}
\usepackage[utf8]{vietnam}
\usepackage{amsmath,amssymb}
\usepackage{tikz}
\begin{document}
\begin{tikzpicture}[scale=0.5]
\draw[->] (-1,0)--(12,0) node[below]{$x$};
\draw[->] (0,-1)--(0,3.5) node[left]{$y$};
\draw[magenta,thick] plot[domain=0:11.12] ({\x},{-9.8*(\x)^2/(200) + \x*0.839 + 1});
\end{tikzpicture}
\end{document}
"""

_TEMPLATE_EDRAW_STATIC_1 = """# ed is the built-in drawing API passed to eDraw(ed, p).
PARAMS = {}

def eDraw(ed, p):
    g, a, Vo, Yo = 9.8, 40, 10, 1
    ar = math.radians(a)
    y = lambda x: -g*x*x/(2*Vo*Vo*math.cos(ar)**2) + x*math.tan(ar) + Yo
    ed.axes(-1.1, 11.5, -0.2, 3.5, grid=False, labels=True)
    ed.plot(y, xmin=0, xmax=11.12, n=500, color="#d946ef", width=2)
    ed.point(0, Yo, radius=4, color="#d946ef")
"""

_DEFAULT_TEMPLATE = _TEMPLATE_EDRAW_DYNAMIC_1
_DEFAULT_TIKZ_TEMPLATE = _TEMPLATE_TIKZ_DYNAMIC_1
_TEMPLATES_EDRAW: list[tuple[str, str]] = [
    ("Mẫu động", _TEMPLATE_EDRAW_DYNAMIC_1),
    ("Mẫu tĩnh", _TEMPLATE_EDRAW_STATIC_1),
]
_TEMPLATES_TIKZ: list[tuple[str, str]] = [
    ("Mẫu động", _TEMPLATE_TIKZ_DYNAMIC_1),
    ("Mẫu tĩnh", _TEMPLATE_TIKZ_STATIC_1),
]


def _backend_label(name: str) -> str:
    labels = {"edraw": "Python (ed)", "tikz": "TikZ"}
    return labels.get(name, name)


def _figure_icon(kind: str, color: str = "#9333ea") -> QIcon:
    pix = QPixmap(16, 16)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(2, 2, 12, 12, 3, 3)
    p.end()
    return QIcon(pix)


class PythonFigureDialog(QDialog):
    """Unified dialog for editing and previewing Python/TikZ figures."""

    finished_signal = pyqtSignal()

    def __init__(
        self,
        parent=None,
        code: str = "",
        backend: str = "tikz",
        params: dict = None,
        param_specs: dict = None,
        editing: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(t("Python Figure — Soạn thảo"))
        self.setMinimumSize(900, 600)
        self._code = code
        self._backend = backend
        self._params = dict(params or {})
        self._param_specs = dict(param_specs or {})
        self._editing = editing
        self._result_data = None
        self._worker = None
        self._build_ui()
        if code:
            self.editor.setPlainText(code)
        elif backend == "tikz":
            self.editor.setPlainText(_DEFAULT_TIKZ_TEMPLATE)
        else:
            self.editor.setPlainText(_DEFAULT_TEMPLATE)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        # Backend selector
        top_row = QHBoxLayout()
        lbl_backend = QLabel(t("Backend:"))
        top_row.addWidget(lbl_backend)
        self.combo_backend = QComboBox()
        self.combo_backend.addItem("TikZ", "tikz")
        self.combo_backend.addItem("Python (ed)", "edraw")
        idx = self.combo_backend.findData(self._backend)
        if idx >= 0:
            self.combo_backend.setCurrentIndex(idx)
        self.combo_backend.currentIndexChanged.connect(self._on_backend_changed)
        top_row.addWidget(self.combo_backend)
        top_row.addStretch()
        # Template selector
        self.combo_template = QComboBox()
        self.combo_template.addItem(t("Mẫu..."), "")
        self.combo_template.currentIndexChanged.connect(self._on_template_selected)
        top_row.addWidget(self.combo_template)
        root.addLayout(top_row)
        self._populate_templates()
        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        # Left: code editor
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.editor = _CodeEditor(highlighter_class=_PythonHighlighter)
        left_layout.addWidget(self.editor, stretch=1)
        btn_row = QHBoxLayout()
        self.btn_compile = QPushButton(t("Biên dịch"))
        self.btn_compile.clicked.connect(self._compile)
        btn_row.addWidget(self.btn_compile)
        left_layout.addLayout(btn_row)
        splitter.addWidget(left)
        # Right: preview + params
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.lbl_preview = _TransparentPreviewLabel()
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(self.lbl_preview)
        right_layout.addWidget(scroll, stretch=1)
        # Params form
        self.params_form = QFormLayout()
        self._param_widgets = {}
        right_layout.addLayout(self.params_form)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)
        # Bottom buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        self.btn_ok = QPushButton(t("Chấp nhận"))
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._accept)
        btn_box.addWidget(self.btn_ok)
        self.btn_cancel = QPushButton(t("Hủy"))
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)
        root.addLayout(btn_box)

    def _populate_templates(self):
        self.combo_template.blockSignals(True)
        self.combo_template.clear()
        self.combo_template.addItem(t("Mẫu..."), "")
        templates = _TEMPLATES_TIKZ if self._backend == "tikz" else _TEMPLATES_EDRAW
        for label, code in templates:
            self.combo_template.addItem(label, code)
        self.combo_template.blockSignals(False)

    def _on_backend_changed(self, idx):
        self._backend = self.combo_backend.currentData()
        self._populate_templates()

    def _on_template_selected(self, idx):
        code = self.combo_template.currentData()
        if code:
            self.editor.setPlainText(code)

    def _compile(self):
        code = self.editor.toPlainText()
        self.btn_compile.setEnabled(False)
        self.lbl_preview.setText(t("Đang biên dịch..."))
        from PyQt6.QtCore import QThread
        self._render_thread = QThread(self)
        self._render_worker = PythonFigureRenderWorker()
        self._render_worker.moveToThread(self._render_thread)
        self._render_thread.started.connect(
            lambda: self._render_worker.run_compile_and_render(
                code, self._backend, self._params, 400, 300
            )
        )
        self._render_worker.rendered.connect(self._on_render_done)
        self._render_worker.failed.connect(self._on_render_failed)
        self._render_worker.rendered.connect(self._render_thread.quit)
        self._render_worker.failed.connect(self._render_thread.quit)
        self._render_thread.finished.connect(self._render_thread.deleteLater)
        self._render_worker.rendered.connect(self._render_worker.deleteLater)
        self._render_worker.failed.connect(self._render_worker.deleteLater)
        self._render_thread.start()

    def _on_render_done(self, image):
        if image and not image.isNull():
            pix = QPixmap.fromImage(_bleed_transparent_pixels(image))
            self.lbl_preview.setPixmap(pix)
        self.btn_compile.setEnabled(True)

    def _on_render_failed(self, error):
        QMessageBox.warning(self, t("Lỗi"), str(error))
        self.btn_compile.setEnabled(True)

    def _accept(self):
        code = self.editor.toPlainText()
        self._result_data = {
            "code": code,
            "backend": self._backend,
            "params": dict(self._params),
            "param_specs": dict(self._param_specs),
            "width": 400,
            "height": 300,
        }
        self.finished_signal.emit()
        self.accept()

    def get_result_data(self) -> dict | None:
        return self._result_data


def _decimals_for(step) -> int:
    if step >= 1:
        return 0
    s = f"{step:.10f}".rstrip("0")
    if "." in s:
        return min(6, len(s.split(".")[1]))
    return 0


def _numeric_values(spec: dict) -> list[float]:
    raw = spec.get("values")
    if not raw:
        return []
    values = []
    try:
        for value in raw:
            values.append(float(value))
    except (TypeError, ValueError):
        return []
    return values


def _decimals_for_values(values: list[float]) -> int:
    if len(values) < 2:
        return 2
    diffs = [abs(values[i + 1] - values[i]) for i in range(len(values) - 1)]
    min_diff = min(d for d in diffs if d > 0) if diffs else 1
    if min_diff >= 1:
        return 0
    s = f"{min_diff:.10f}".rstrip("0")
    if "." in s:
        return min(6, len(s.split(".")[1]))
    return 2
