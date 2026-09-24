"""
Floating slider panel for live-tweaking a PythonFigureElement.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.i18n import t

if TYPE_CHECKING:
    from models.elements import PythonFigureElement

_DEBOUNCE_MS = 40


class PythonFigureParamPanel(QWidget):
    """Floating slider panel for live-tweaking a PythonFigureElement."""

    params_changed = pyqtSignal(dict)
    edit_code_requested = pyqtSignal()
    bake_requested = pyqtSignal()
    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(
            'PythonFigureParamPanel { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px;}'
        )
        self._element: PythonFigureElement | None = None
        self._params: dict[str, float] = {}
        self._sliders: dict[str, QSlider] = {}
        self._spinboxes: dict[str, QDoubleSpinBox] = {}
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_params)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(6)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        self.title_label = QLabel(t('Hình Python'))
        title_font = QFont()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet('color:#0f172a;')
        header.addWidget(self.title_label, 1)
        self.btn_edit = QPushButton(t('Sửa mã'))
        self.btn_bake = QPushButton(t('Chuyển thành ảnh'))
        self.btn_close = QPushButton('×')
        self.btn_close.setFixedWidth(28)
        for btn in (self.btn_edit, self.btn_bake, self.btn_close):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                'QPushButton { padding:2px 8px; border:1px solid #cbd5e1; border-radius:4px; background:#f8fafc; }'
                'QPushButton:hover { background:#e0e7ff; }'
            )
        header.addWidget(self.btn_edit)
        header.addWidget(self.btn_bake)
        header.addWidget(self.btn_close)
        root.addLayout(header)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet('color:#e2e8f0;')
        root.addWidget(sep)
        self._form_host = QWidget()
        self._form = QFormLayout(self._form_host)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._form.setHorizontalSpacing(8)
        self._form.setVerticalSpacing(4)
        root.addWidget(self._form_host)
        self.btn_edit.clicked.connect(self.edit_code_requested.emit)
        self.btn_bake.clicked.connect(self.bake_requested.emit)
        self.btn_close.clicked.connect(self.close_requested.emit)

    def attach_to(self, element: PythonFigureElement, anchor_global: QPoint) -> None:
        """Bind to `element` and show next to `anchor_global` (top-right corner)."""
        self._element = element
        self._params = dict(element.params)
        self.title_label.setText(t('Hình TikZ') if getattr(element, 'backend', '') == 'tikz' else t('Hình Python'))
        self._rebuild_rows(element.param_specs)
        self.adjustSize()
        screen = self.screen() or (self.parentWidget().screen() if self.parentWidget() else None)
        rect = screen.availableGeometry() if screen else None
        target_x = anchor_global.x() + 16
        target_y = anchor_global.y()
        if rect:
            target_x = min(target_x, rect.right() - self.width() - 8)
            target_x = max(target_x, rect.left() + 8)
            target_y = min(target_y, rect.bottom() - self.height() - 8)
            target_y = max(target_y, rect.top() + 8)
        self.move(target_x, target_y)
        self.show()
        self.raise_()

    def detach(self) -> None:
        self._element = None
        self.hide()

    @property
    def element(self) -> PythonFigureElement | None:
        return self._element

    def _rebuild_rows(self, param_specs: dict) -> None:
        while self._form.rowCount() > 0:
            self._form.removeRow(0)
        self._sliders.clear()
        self._spinboxes.clear()
        if not param_specs:
            empty = QLabel(t('Không có tham số.'))
            empty.setStyleSheet('color:#94a3b8;')
            self._form.addRow(empty)
            return
        for name, spec in param_specs.items():
            lbl = QLabel(spec.get('label', name))
            row = self._build_param_row(name, spec)
            self._form.addRow(lbl, row)

    def _build_param_row(self, name: str, spec: dict) -> QWidget:
        values = _numeric_values(spec)
        lo = float(spec['min'])
        hi = float(spec['max'])
        step = float(spec['step'])
        value = float(self._params.get(name, spec.get('value', lo)))
        slider = QSlider(Qt.Orientation.Horizontal)
        if values:
            slider.setRange(0, max(0, len(values) - 1))
            slider.setSingleStep(1)
            idx = min(range(len(values)), key=lambda i: abs(values[i] - value))
            value = values[idx]
            slider.setValue(idx)
        else:
            n_steps = max(1, int(round((hi - lo) / step)))
            slider.setRange(0, n_steps)
            slider.setSingleStep(1)
            slider.setValue(int(round((value - lo) / step)))
        slider.setFixedWidth(180)
        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setDecimals(_decimals_for_values(values) if values else _decimals_for(step))
        spin.setValue(value)
        spin.setFixedWidth(80)

        def from_slider(i: int) -> None:
            if values:
                v = values[max(0, min(len(values) - 1, int(i)))]
            else:
                v = lo + i * step
            v = max(lo, min(hi, v))
            self._params[name] = v
            spin.blockSignals(True)
            spin.setValue(v)
            spin.blockSignals(False)
            self._schedule_emit()

        def from_spin(v: float) -> None:
            v = max(lo, min(hi, float(v)))
            if values:
                idx = min(range(len(values)), key=lambda i: abs(values[i] - v))
                v = values[idx]
            else:
                idx = int(round((v - lo) / step))
            self._params[name] = v
            slider.blockSignals(True)
            slider.setValue(idx)
            slider.blockSignals(False)
            if values and abs(spin.value() - v) > 1e-12:
                spin.blockSignals(True)
                spin.setValue(v)
                spin.blockSignals(False)
            self._schedule_emit()

        slider.valueChanged.connect(from_slider)
        spin.valueChanged.connect(from_spin)
        self._sliders[name] = slider
        self._spinboxes[name] = spin
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(slider, 1)
        lay.addWidget(spin, 0)
        return wrap

    def _schedule_emit(self) -> None:
        self._debounce.start()

    def _emit_params(self) -> None:
        if not self._element:
            return
        self.params_changed.emit(dict(self._params))


def _decimals_for(step: float) -> int:
    if step >= 1:
        return 0
    s = f'{step:.10f}'.rstrip('0')
    if '.' in s:
        return min(6, len(s.split('.')[1]))
    return 0


def _numeric_values(spec: dict) -> list[float]:
    raw = spec.get('values')
    if not raw:
        return []
    values = []
    try:
        for value in raw:
            values.append(float(value))
        return values
    except (TypeError, ValueError):
        return []


def _decimals_for_values(values: list[float]) -> int:
    if len(values) < 2:
        return 2
    diffs = [abs(values[i + 1] - values[i]) for i in range(len(values) - 1) if abs(values[i + 1] - values[i]) > 1e-12]
    return _decimals_for(min(diffs) if diffs else 1.0)
