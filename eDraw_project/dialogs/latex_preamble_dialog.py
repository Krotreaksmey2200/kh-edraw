"""dialogs/latex_preamble_dialog.py
Dialog for viewing & editing LaTeX preambles and configuring page/frame dimensions and canvas zoom/view.
"""
from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.i18n import t

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config" / "templates" / "extest"
_SLIDE_WRAPPER = _CONFIG_DIR / "slide_wrapper.tex"
_TIKZ_WRAPPER = _CONFIG_DIR / "tikz_ai_wrapper.tex"


class LatexPreambleDialog(QDialog):
    """Dialog to inspect & customize LaTeX preambles, slide dimensions, and zoom/fit canvas."""

    def __init__(self, parent=None, canvas=None) -> None:
        super().__init__(parent)
        self.canvas = canvas
        if self.canvas is None and parent is not None:
            self.canvas = getattr(parent, "canvas", None)
            if self.canvas is None and hasattr(parent, "parent"):
                p_parent = parent.parent()
                if p_parent is not None:
                    self.canvas = getattr(p_parent, "canvas", None)

        self.setWindowTitle(t("កំណត់ទំហំទំព័រ & LaTeX Preamble"))
        self.setMinimumSize(900, 680)
        self._build_ui()
        self._load_data()

        # Connect canvas zoom signal if available
        if self.canvas and hasattr(self.canvas, "zoom_changed"):
            self.canvas.zoom_changed.connect(self._on_zoom_changed)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # ── 1. Page & Frame Size Settings ──
        grp_size = QGroupBox(t("កំណត់ទំហំទំព័រ និងទំហំស៊ុម (Page & Frame Dimensions)"))
        size_layout = QHBoxLayout(grp_size)
        size_layout.setSpacing(20)

        # Slide / Canvas Resolution
        form_canvas = QFormLayout()
        self.combo_preset = QComboBox()
        self.combo_preset.addItems([
            "1920 × 1080 (16:9 Full HD)",
            "1280 × 720 (16:9 HD)",
            "1024 × 768 (4:3 Standard)",
            "2560 × 1440 (2K QHD)",
            "A4 Landscape (1920 × 1357)",
            "A4 Portrait (1080 × 1528)",
            t("ផ្ទាល់ខ្លួន (Custom)"),
        ])
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        form_canvas.addRow(t("ទម្រង់ទំព័រ (Preset):"), self.combo_preset)

        row_wh = QHBoxLayout()
        self.spin_width = QSpinBox()
        self.spin_width.setRange(400, 7680)
        self.spin_width.setSingleStep(80)
        self.spin_width.setSuffix(" px")
        self.spin_height = QSpinBox()
        self.spin_height.setRange(300, 4320)
        self.spin_height.setSingleStep(60)
        self.spin_height.setSuffix(" px")
        row_wh.addWidget(self.spin_width)
        row_wh.addWidget(QLabel("×"))
        row_wh.addWidget(self.spin_height)
        form_canvas.addRow(t("ទទឹង × កម្ពស់ (W × H):"), row_wh)
        size_layout.addLayout(form_canvas, 1)

        # LaTeX Frame / Box Width
        form_box = QFormLayout()
        self.combo_box_width = QComboBox()
        self.combo_box_width.addItems(["16cm", "18cm", "20cm", "22cm", "24cm", "26cm"])
        self.combo_box_width.currentTextChanged.connect(self._on_box_width_changed)
        form_box.addRow(t("ទទឹងប្រអប់លំហាត់ (Box Width):"), self.combo_box_width)

        row_tikz = QHBoxLayout()
        self.spin_tikz_w = QSpinBox()
        self.spin_tikz_w.setRange(2, 20)
        self.spin_tikz_w.setSuffix(" cm")
        self.spin_tikz_h = QSpinBox()
        self.spin_tikz_h.setRange(2, 20)
        self.spin_tikz_h.setSuffix(" cm")
        self.spin_tikz_w.valueChanged.connect(self._on_tikz_size_changed)
        self.spin_tikz_h.valueChanged.connect(self._on_tikz_size_changed)
        row_tikz.addWidget(self.spin_tikz_w)
        row_tikz.addWidget(QLabel("×"))
        row_tikz.addWidget(self.spin_tikz_h)
        form_box.addRow(t("ទំហំរូប TikZ (W × H):"), row_tikz)
        size_layout.addLayout(form_box, 1)

        root.addWidget(grp_size)

        # ── 2. Canvas View & Zoom Controls (Professional View Tools) ──
        grp_view = QGroupBox(t("មុខងារមើល និង Zoom ស្លាយ (Canvas View & Zoom Controls)"))
        view_layout = QVBoxLayout(grp_view)
        view_layout.setSpacing(8)

        # Row 1: Zoom / Fit action buttons
        row_buttons = QHBoxLayout()
        row_buttons.setSpacing(8)

        self.btn_zoom_out = QPushButton(t("➖ បង្រួម (Zoom Out)"))
        self.btn_zoom_out.setToolTip(t("បង្រួមទំហំមើល (Zoom Out)"))
        self.btn_zoom_out.clicked.connect(self._on_zoom_out)
        row_buttons.addWidget(self.btn_zoom_out)

        self.lbl_zoom_val = QLabel("100%")
        self.lbl_zoom_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_zoom_val.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 13px;
                color: #1e293b;
                background-color: #f1f5f9;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 4px 12px;
                min-width: 55px;
            }
        """)
        row_buttons.addWidget(self.lbl_zoom_val)

        self.btn_zoom_in = QPushButton(t("➕ ពង្រីក (Zoom In)"))
        self.btn_zoom_in.setToolTip(t("ពង្រីកទំហំមើល (Zoom In)"))
        self.btn_zoom_in.clicked.connect(self._on_zoom_in)
        row_buttons.addWidget(self.btn_zoom_in)

        self.btn_zoom_100 = QPushButton("100% (ដើម)")
        self.btn_zoom_100.setToolTip(t("ត្រឡប់ទៅទំហំដើម 100%"))
        self.btn_zoom_100.clicked.connect(self._on_zoom_reset)
        row_buttons.addWidget(self.btn_zoom_100)

        self.btn_fit_win = QPushButton(t("⊡ សមល្មមផ្ទាំង (Fit Window)"))
        self.btn_fit_win.setToolTip(t("សម្រួលទំហំស្លាយឱ្យសមល្មមពេញផ្ទាំង (Fit to Window)"))
        self.btn_fit_win.setStyleSheet("font-weight: 600; color: #1e40af;")
        self.btn_fit_win.clicked.connect(self._on_fit_window)
        row_buttons.addWidget(self.btn_fit_win)

        self.btn_fit_width = QPushButton(t("↔ សមល្មមទទឹង (Fit Width)"))
        self.btn_fit_width.setToolTip(t("សម្រួលឱ្យសមល្មមតាមទទឹងផ្ទាំង (Fit Width)"))
        self.btn_fit_width.clicked.connect(self._on_fit_width)
        row_buttons.addWidget(self.btn_fit_width)

        self.btn_fit_height = QPushButton(t("↕ សមល្មមកម្ពស់ (Fit Height)"))
        self.btn_fit_height.setToolTip(t("សម្រួលឱ្យសមល្មមតាមកម្ពស់ផ្ទាំង (Fit Height)"))
        self.btn_fit_height.clicked.connect(self._on_fit_height)
        row_buttons.addWidget(self.btn_fit_height)

        row_buttons.addStretch(1)
        view_layout.addLayout(row_buttons)

        # Row 2: Options and live apply
        row_opts = QHBoxLayout()
        row_opts.setSpacing(16)

        self.chk_apply_all = QCheckBox(t("អនុវត្តទំហំទៅស្លាយទាំងអស់ (Apply size to all slides)"))
        self.chk_apply_all.setChecked(True)
        row_opts.addWidget(self.chk_apply_all)

        self.chk_auto_fit = QCheckBox(t("សមល្មមផ្ទាំងដោយស្វ័យប្រវត្តិ (Auto-fit to window)"))
        self.chk_auto_fit.setChecked(True)
        row_opts.addWidget(self.chk_auto_fit)

        row_opts.addStretch(1)

        self.btn_apply_now = QPushButton(t("⚡ អនុវត្តទំហំលើផ្ទាំងភ្លាមៗ (Apply Now)"))
        self.btn_apply_now.setToolTip(t("អនុវត្តទំហំស្លាយ និងកែសម្រួលផ្ទាំងគំនូរភ្លាមៗ"))
        self.btn_apply_now.setStyleSheet("background-color: #0284c7; color: white; font-weight: 600; padding: 4px 12px; border-radius: 4px;")
        self.btn_apply_now.clicked.connect(self._apply_dimensions_now)
        row_opts.addWidget(self.btn_apply_now)

        view_layout.addLayout(row_opts)
        root.addWidget(grp_view)

        # ── 3. LaTeX Preamble Tabs ──
        self.tabs = QTabWidget()

        # Tab 1: Slide Wrapper (Exercises)
        self.editor_slide = self._create_editor()
        self.tabs.addTab(self.editor_slide, t("Slide Wrapper (លំហាត់ / Questions)"))

        # Tab 2: TikZ Wrapper (Drawings)
        self.editor_tikz = self._create_editor()
        self.tabs.addTab(self.editor_tikz, t("TikZ AI Wrapper (រូបគំនូរ / Figures)"))

        root.addWidget(self.tabs, 1)

        # ── 4. Bottom Actions ──
        bottom_layout = QHBoxLayout()

        btn_reset = QPushButton(t("កំណត់ដើមឡើងវិញ (Reset Default)"))
        btn_reset.setStyleSheet("color: #b91c1c;")
        btn_reset.clicked.connect(self._reset_default)
        bottom_layout.addWidget(btn_reset)

        bottom_layout.addStretch(1)

        btn_cancel = QPushButton(t("បោះបង់ (Cancel)"))
        btn_cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(btn_cancel)

        btn_save = QPushButton(t("រក្សាទុក (Save Changes)"))
        btn_save.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 6px 18px; border-radius: 4px;")
        btn_save.clicked.connect(self._save_changes)
        bottom_layout.addWidget(btn_save)

        root.addLayout(bottom_layout)

    def _create_editor(self) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        editor.setFont(font)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        return editor

    def _load_data(self) -> None:
        # Load slide wrapper
        if _SLIDE_WRAPPER.exists():
            content = _SLIDE_WRAPPER.read_text(encoding="utf-8")
            self.editor_slide.setPlainText(content)
            self._parse_box_settings(content)

        # Load TikZ wrapper
        if _TIKZ_WRAPPER.exists():
            content_tikz = _TIKZ_WRAPPER.read_text(encoding="utf-8")
            self.editor_tikz.setPlainText(content_tikz)

        # Load Canvas resolution from QSettings or active slide
        s = QSettings("eDraw", "eDraw")
        saved_w = int(s.value("slide/width", 1080))
        saved_h = int(s.value("slide/height", 1528))
        if self.canvas and hasattr(self.canvas, "_current_slide"):
            cs = self.canvas._current_slide
            if hasattr(cs, "width") and cs.width > 0:
                saved_w = cs.width
            if hasattr(cs, "height") and cs.height > 0:
                saved_h = cs.height
        self.spin_width.setValue(saved_w)
        self.spin_height.setValue(saved_h)

        if self.canvas and hasattr(self.canvas, "_zoom"):
            self._on_zoom_changed(self.canvas._zoom)

    def _on_zoom_changed(self, zoom: float) -> None:
        pct = int(round(zoom * 100))
        self.lbl_zoom_val.setText(f"{pct}%")

    def _on_zoom_in(self) -> None:
        if self.canvas and hasattr(self.canvas, "zoom_in"):
            self.canvas.zoom_in()

    def _on_zoom_out(self) -> None:
        if self.canvas and hasattr(self.canvas, "zoom_out"):
            self.canvas.zoom_out()

    def _on_zoom_reset(self) -> None:
        if self.canvas and hasattr(self.canvas, "zoom_reset"):
            self.canvas.zoom_reset()

    def _on_fit_window(self) -> None:
        if self.canvas and hasattr(self.canvas, "fit_to_window"):
            self.canvas.fit_to_window()

    def _on_fit_width(self) -> None:
        if self.canvas and hasattr(self.canvas, "fit_to_width"):
            self.canvas.fit_to_width()

    def _on_fit_height(self) -> None:
        if self.canvas and hasattr(self.canvas, "fit_to_height"):
            self.canvas.fit_to_height()

    def _apply_dimensions_now(self) -> None:
        w = self.spin_width.value()
        h = self.spin_height.value()
        if self.canvas and hasattr(self.canvas, "set_slide_dimensions"):
            self.canvas.set_slide_dimensions(w, h, apply_all=self.chk_apply_all.isChecked())
            if self.chk_auto_fit.isChecked() and hasattr(self.canvas, "fit_to_window"):
                self.canvas.fit_to_window()
            else:
                self.canvas.update()

    def _parse_box_settings(self, content: str) -> None:
        m_box = re.search(r"width=(\d+cm)", content)
        if m_box:
            idx = self.combo_box_width.findText(m_box.group(1))
            if idx >= 0:
                self.combo_box_width.setCurrentIndex(idx)

        m_tw = re.search(r"\\setlength\{\\SlideTikzPictureWidth\}\{(\d+)cm\}", content)
        if m_tw:
            self.spin_tikz_w.setValue(int(m_tw.group(1)))
        m_th = re.search(r"\\setlength\{\\SlideTikzPictureHeight\}\{(\d+)cm\}", content)
        if m_th:
            self.spin_tikz_h.setValue(int(m_th.group(1)))

    def _on_preset_changed(self, index: int) -> None:
        presets = [
            (1920, 1080),
            (1280, 720),
            (1024, 768),
            (2560, 1440),
            (1920, 1357),
            (1080, 1528),
        ]
        if index < len(presets):
            w, h = presets[index]
            self.spin_width.setValue(w)
            self.spin_height.setValue(h)

    def _on_box_width_changed(self, new_val: str) -> None:
        text = self.editor_slide.toPlainText()
        updated = re.sub(r"width=\d+cm", f"width={new_val}", text)
        if updated != text:
            self.editor_slide.setPlainText(updated)

    def _on_tikz_size_changed(self) -> None:
        tw = self.spin_tikz_w.value()
        th = self.spin_tikz_h.value()
        text = self.editor_slide.toPlainText()
        text = re.sub(r"(\\setlength\{\\SlideTikzPictureWidth\}\{)\d+cm(\})", rf"\g<1>{tw}cm\g<2>", text)
        text = re.sub(r"(\\setlength\{\\SlideTikzPictureHeight\}\{)\d+cm(\})", rf"\g<1>{th}cm\g<2>", text)
        self.editor_slide.setPlainText(text)

    def _save_changes(self) -> None:
        try:
            # 1. Save Slide Wrapper
            slide_code = self.editor_slide.toPlainText().strip()
            if "% __SLIDE_BODY__" not in slide_code:
                QMessageBox.warning(self, t("ព្រមាន"), t("កូដ slide_wrapper.tex ត្រូវតែមាន '% __SLIDE_BODY__' សម្រាប់ជំនួសខ្លឹមសារ។"))
                return
            _SLIDE_WRAPPER.write_text(slide_code + "\n", encoding="utf-8")

            # 2. Save TikZ Wrapper
            tikz_code = self.editor_tikz.toPlainText().strip()
            if "\\begin{document}" not in tikz_code:
                QMessageBox.warning(self, t("ព្រមាន"), t("កូដ tikz_ai_wrapper.tex ត្រូវតែមាន '\\begin{document}'។"))
                return
            _TIKZ_WRAPPER.write_text(tikz_code + "\n", encoding="utf-8")

            # 3. Apply Dimensions to Canvas & Save resolution settings
            w = self.spin_width.value()
            h = self.spin_height.value()
            self._apply_dimensions_now()

            s = QSettings("eDraw", "eDraw")
            s.setValue("slide/width", w)
            s.setValue("slide/height", h)

            QMessageBox.information(self, t("ជោគជ័យ"), t("បានរក្សាទុកការកំណត់ទំហំទំព័រ និង LaTeX Preamble ដោយជោគជ័យ!"))
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, t("កំហុស"), t("មិនអាចរក្សាទុកបានទេ៖ {err}", err=exc))

    def _reset_default(self) -> None:
        ans = QMessageBox.question(
            self,
            t("បញ្ជាក់"),
            t("តើលោកអ្នកពិតជាចង់កំណត់ LaTeX Preamble ត្រឡប់ទៅជាទម្រង់ដើមវិញមែនទេ?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        if _SLIDE_WRAPPER.exists():
            default_slide = _SLIDE_WRAPPER.read_text(encoding="utf-8")
            self.editor_slide.setPlainText(default_slide)
            self._parse_box_settings(default_slide)
        if _TIKZ_WRAPPER.exists():
            default_tikz = _TIKZ_WRAPPER.read_text(encoding="utf-8")
            self.editor_tikz.setPlainText(default_tikz)

        self.spin_width.setValue(1080)
        self.spin_height.setValue(1528)
        self.combo_preset.setCurrentIndex(5)
