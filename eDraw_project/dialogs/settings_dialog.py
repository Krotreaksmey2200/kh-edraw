# Source Generated with Decompyle++
# File: settings_dlg.pyc (Python 3.12)

'''
dialogs/settings_dialog.py
Hộp thoại cài đặt bảng vẽ: màu nền, lưới kẻ, độ mượt nét.
'''
from __future__ import annotations
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFontComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget
from core.i18n import current_language, language_name, set_language, supported_languages, t
from core.latex_engine import display_pdflatex_command, save_pdflatex_command

class BoardSettingsDialog(QDialog):
    
    def __init__(self, canvas=None, parent=None, *, on_reset):
        super().__init__(parent)
        self.setWindowTitle(t('Cài đặt Bảng'))
        self.setMinimumWidth(560)
        self.canvas = canvas
        self._on_reset = on_reset
        self._texstudio_upgrade_prompt_open = False
        self._build_ui()

    
    def _build_ui(self = None):
        root = QVBoxLayout(self)
        root.setSpacing(12)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        board_tab = QWidget()
        layout = QVBoxLayout(board_tab)
        layout.setSpacing(12)
        self.tabs.addTab(board_tab, '')
        row_language = QHBoxLayout()
        self.lbl_language = QLabel()
        row_language.addWidget(self.lbl_language)
        self.combo_language = QComboBox()
        for code in supported_languages():
            parent = self.parent()
            icon = None
            if hasattr(parent, '_create_shape_icon'):
                icon = parent._create_shape_icon(f'''flag_{code}''')
            if icon and not icon.isNull():
                self.combo_language.addItem(icon, language_name(code), code)
                continue
            self.combo_language.addItem(language_name(code), code)
        lang_idx = self.combo_language.findData(current_language())
        if lang_idx >= 0:
            self.combo_language.setCurrentIndex(lang_idx)
        self.combo_language.currentIndexChanged.connect(self._on_language_change)
        row_language.addWidget(self.combo_language)
        layout.addLayout(row_language)
        row = QHBoxLayout()
        self.lbl_board_color = QLabel()
        row.addWidget(self.lbl_board_color)
        self.btn_color = QPushButton()
        self._refresh_color_btn()
        self.btn_color.clicked.connect(self._choose_color)
        row.addWidget(self.btn_color)
        layout.addLayout(row)
        self.chk_h = QCheckBox()
        self.chk_h.setChecked(self.canvas.grid_h)
        self.chk_h.stateChanged.connect(self._apply)
        layout.addWidget(self.chk_h)
        self.chk_v = QCheckBox()
        self.chk_v.setChecked(self.canvas.grid_v)
        self.chk_v.stateChanged.connect(self._apply)
        layout.addWidget(self.chk_v)
        row2 = QHBoxLayout()
        self.lbl_grid_thickness = QLabel()
        row2.addWidget(self.lbl_grid_thickness)
        self.spin_thick = QSpinBox()
        self.spin_thick.setRange(1, 10)
        self.spin_thick.setValue(self.canvas.grid_thickness)
        self.spin_thick.valueChanged.connect(self._apply)
        row2.addWidget(self.spin_thick)
        layout.addLayout(row2)
        row3 = QHBoxLayout()
        self.lbl_grid_spacing = QLabel()
        row3.addWidget(self.lbl_grid_spacing)
        self.spin_spacing = QSpinBox()
        self.spin_spacing.setRange(10, 300)
        self.spin_spacing.setValue(self.canvas.grid_spacing)
        self.spin_spacing.valueChanged.connect(self._apply)
        row3.addWidget(self.spin_spacing)
        layout.addLayout(row3)
        row_toolbar = QHBoxLayout()
        self.lbl_toolbar_height = QLabel()
        row_toolbar.addWidget(self.lbl_toolbar_height)
        self.spin_toolbar_height = QSpinBox()
        parent = self.parent()
        current_vertical = bool(getattr(parent, '_toolbar_vertical', False))
        min_h = getattr(parent, 'VERTICAL_MIN_TOOLBAR_HEIGHT' if current_vertical else 'MIN_TOOLBAR_HEIGHT', 16 if current_vertical else 28)
        max_h = getattr(parent, 'MAX_TOOLBAR_HEIGHT', 64)
        default_h = getattr(parent, 'DEFAULT_TOOLBAR_HEIGHT', 33)
        current_h = getattr(parent, '_toolbar_height', default_h)
        self.spin_toolbar_height.setRange(min_h, max_h)
        self.spin_toolbar_height.setValue(int(current_h))
        self.spin_toolbar_height.setSuffix(' px')
        self.spin_toolbar_height.valueChanged.connect(self._apply)
        row_toolbar.addWidget(self.spin_toolbar_height)
        layout.addLayout(row_toolbar)
        row_group = QHBoxLayout()
        self.lbl_tool_group_height = QLabel()
        row_group.addWidget(self.lbl_tool_group_height)
        self.spin_tool_group_height = QSpinBox()
        min_group_h = getattr(parent, 'VERTICAL_MIN_TOOL_GROUP_HEIGHT' if current_vertical else 'MIN_TOOL_GROUP_HEIGHT', 16 if current_vertical else 24)
        max_group_h = getattr(parent, 'MAX_TOOL_GROUP_HEIGHT', 56)
        default_group_h = getattr(parent, 'DEFAULT_TOOL_GROUP_HEIGHT', 27)
        current_group_h = getattr(parent, '_tool_group_height', default_group_h)
        self.spin_tool_group_height.setRange(min_group_h, max_group_h)
        self.spin_tool_group_height.setValue(int(current_group_h))
        self.spin_tool_group_height.setSuffix(' px')
        self.spin_tool_group_height.valueChanged.connect(self._apply)
        row_group.addWidget(self.spin_tool_group_height)
        layout.addLayout(row_group)
        self.chk_toolbar_vertical = QCheckBox()
        self.chk_toolbar_vertical.setChecked(current_vertical)
        self.chk_toolbar_vertical.stateChanged.connect(self._apply)
        layout.addWidget(self.chk_toolbar_vertical)
        self._sync_toolbar_size_ranges()
        self.chk_follow_pen = QCheckBox()
        self.chk_follow_pen.setChecked(bool(getattr(self.canvas.engine, 'tool_attrs_follow_pen', True)))
        self._last_follow_pen = self.chk_follow_pen.isChecked()
        self.chk_follow_pen.stateChanged.connect(self._apply)
        layout.addWidget(self.chk_follow_pen)
        self.lbl_latex = QLabel()
        layout.addWidget(self.lbl_latex)
        row_latex = QHBoxLayout()
        self.edit_pdflatex = QLineEdit()
        self.edit_pdflatex.setText(display_pdflatex_command())
        self.edit_pdflatex.editingFinished.connect(self._save_pdflatex)
        row_latex.addWidget(self.edit_pdflatex, 1)
        self.btn_pdflatex_browse = QPushButton()
        self.btn_pdflatex_browse.clicked.connect(self._choose_pdflatex)
        row_latex.addWidget(self.btn_pdflatex_browse)
        self.btn_pdflatex_clear = QPushButton()
        self.btn_pdflatex_clear.clicked.connect(self._clear_pdflatex)
        row_latex.addWidget(self.btn_pdflatex_clear)
        self.btn_preamble = QPushButton()
        self.btn_preamble.clicked.connect(self._open_preamble_dialog)
        row_latex.addWidget(self.btn_preamble)
        layout.addLayout(row_latex)
        self._build_pen_tab()
        self._build_texstudio_tab()
        row_buttons = QHBoxLayout()
        self.btn_defaults = QPushButton()
        self.btn_defaults.clicked.connect(self._defaults)
        row_buttons.addWidget(self.btn_defaults)
        row_buttons.addStretch(1)
        self.btn_close = QPushButton()
        self.btn_close.clicked.connect(self.accept)
        row_buttons.addWidget(self.btn_close)
        root.addLayout(row_buttons)
        self._refresh_texts()

    
    def _build_pen_tab(self = None):
        '''Tab tập trung mọi tham số tinh chỉnh nét bút.'''
        e = self.canvas.engine
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setSpacing(10)
        self.tabs.addTab(tab, '')
        self.grp_pen_basic = QGroupBox()
        basic = QFormLayout(self.grp_pen_basic)
        self.lbl_smoothing = QLabel()
        self.slider_smooth = QSlider(Qt.Orientation.Horizontal)
        self.slider_smooth.setRange(0, 100)
        self.slider_smooth.setValue(int(e.freehand_smoothing * 100))
        self.slider_smooth.valueChanged.connect(self._apply)
        basic.addRow(self.lbl_smoothing, self.slider_smooth)
        self.lbl_min_dist = QLabel()
        self.spin_min_dist = QDoubleSpinBox()
        self.spin_min_dist.setRange(0, 8)
        self.spin_min_dist.setSingleStep(0.1)
        self.spin_min_dist.setDecimals(1)
        self.spin_min_dist.setValue(float(e.freehand_min_distance))
        self.spin_min_dist.valueChanged.connect(self._apply)
        basic.addRow(self.lbl_min_dist, self.spin_min_dist)
        self.lbl_ink_min_dist = QLabel()
        self.spin_ink_min_dist = QDoubleSpinBox()
        self.spin_ink_min_dist.setRange(0.1, 4)
        self.spin_ink_min_dist.setSingleStep(0.05)
        self.spin_ink_min_dist.setDecimals(2)
        self.spin_ink_min_dist.setValue(float(e.ink_sampling_min_distance))
        self.spin_ink_min_dist.valueChanged.connect(self._apply)
        basic.addRow(self.lbl_ink_min_dist, self.spin_ink_min_dist)
        self.chk_pressure = QCheckBox()
        self.chk_pressure.setChecked(bool(e.use_pressure))
        self.chk_pressure.stateChanged.connect(self._apply)
        basic.addRow('', self.chk_pressure)
        self.chk_final_smoothing = QCheckBox()
        self.chk_final_smoothing.setChecked(bool(getattr(e, 'final_stroke_smoothing_enabled', False)))
        self.chk_final_smoothing.stateChanged.connect(self._apply)
        basic.addRow('', self.chk_final_smoothing)
        outer.addWidget(self.grp_pen_basic)
        self.grp_one_euro = QGroupBox()
        one_euro = QFormLayout(self.grp_one_euro)
        self.lbl_one_euro_cutoff = QLabel()
        self.spin_one_euro_cutoff = QDoubleSpinBox()
        self.spin_one_euro_cutoff.setRange(0.1, 20)
        self.spin_one_euro_cutoff.setSingleStep(0.1)
        self.spin_one_euro_cutoff.setDecimals(2)
        self.spin_one_euro_cutoff.setValue(float(e.one_euro.min_cutoff))
        self.spin_one_euro_cutoff.valueChanged.connect(self._apply)
        one_euro.addRow(self.lbl_one_euro_cutoff, self.spin_one_euro_cutoff)
        self.lbl_one_euro_beta = QLabel()
        self.spin_one_euro_beta = QDoubleSpinBox()
        self.spin_one_euro_beta.setRange(0, 1)
        self.spin_one_euro_beta.setSingleStep(0.005)
        self.spin_one_euro_beta.setDecimals(3)
        self.spin_one_euro_beta.setValue(float(e.one_euro.beta))
        self.spin_one_euro_beta.valueChanged.connect(self._apply)
        one_euro.addRow(self.lbl_one_euro_beta, self.spin_one_euro_beta)
        outer.addWidget(self.grp_one_euro)
        self.grp_lead = QGroupBox()
        lead = QFormLayout(self.grp_lead)
        self.lbl_lead_lookahead = QLabel()
        self.spin_lead_lookahead = QDoubleSpinBox()
        self.spin_lead_lookahead.setRange(0, 50)
        self.spin_lead_lookahead.setSingleStep(0.5)
        self.spin_lead_lookahead.setDecimals(1)
        self.spin_lead_lookahead.setSuffix(' ms')
        self.spin_lead_lookahead.setValue(float(e._lead_lookahead_sec) * 1000)
        self.spin_lead_lookahead.valueChanged.connect(self._apply)
        lead.addRow(self.lbl_lead_lookahead, self.spin_lead_lookahead)
        self.lbl_lead_speed = QLabel()
        self.spin_lead_speed = QDoubleSpinBox()
        self.spin_lead_speed.setRange(0, 2000)
        self.spin_lead_speed.setSingleStep(10)
        self.spin_lead_speed.setDecimals(0)
        self.spin_lead_speed.setSuffix(' px/s')
        self.spin_lead_speed.setValue(float(e._lead_predict_min_speed))
        self.spin_lead_speed.valueChanged.connect(self._apply)
        lead.addRow(self.lbl_lead_speed, self.spin_lead_speed)
        outer.addWidget(self.grp_lead)
        self.grp_dynamic = QGroupBox()
        dyn = QFormLayout(self.grp_dynamic)
        self.lbl_pressure_strength = QLabel()
        self.spin_pressure_strength = QDoubleSpinBox()
        self.spin_pressure_strength.setRange(0, 2)
        self.spin_pressure_strength.setSingleStep(0.05)
        self.spin_pressure_strength.setDecimals(2)
        self.spin_pressure_strength.setValue(float(e.pressure_width_strength))
        self.spin_pressure_strength.valueChanged.connect(self._apply)
        dyn.addRow(self.lbl_pressure_strength, self.spin_pressure_strength)
        self.lbl_velocity_strength = QLabel()
        self.spin_velocity_strength = QDoubleSpinBox()
        self.spin_velocity_strength.setRange(0, 2)
        self.spin_velocity_strength.setSingleStep(0.05)
        self.spin_velocity_strength.setDecimals(2)
        self.spin_velocity_strength.setValue(float(e.velocity_width_strength))
        self.spin_velocity_strength.valueChanged.connect(self._apply)
        dyn.addRow(self.lbl_velocity_strength, self.spin_velocity_strength)
        outer.addWidget(self.grp_dynamic)
        outer.addStretch(1)

    
    def _build_texstudio_tab(self = None):
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setSpacing(12)
        self.tabs.addTab(tab, 'TeXstudio')
        row_mode = QHBoxLayout()
        self.chk_ts_split_mode = QCheckBox()
        if self._texstudio_allowed():
            self._texstudio_allowed()
        self.chk_ts_split_mode.setChecked(str(getattr(self.canvas, 'texstudio_layout_mode', 'inline')).lower() == 'split')
        self.chk_ts_split_mode.stateChanged.connect(self._guard_texstudio_split_mode)
        self.chk_ts_split_mode.stateChanged.connect(self._apply)
        row_mode.addWidget(self.chk_ts_split_mode)
        self.chk_editable_text = QCheckBox()
        if self.chk_ts_split_mode.isChecked():
            self.chk_ts_split_mode.isChecked()
        self.chk_editable_text.setChecked(bool(getattr(self.canvas, 'editable_text_mode', False)))
        self.chk_editable_text.stateChanged.connect(self._apply)
        row_mode.addWidget(self.chk_editable_text)
        row_mode.addStretch(1)
        outer.addLayout(row_mode)
        self.grp_ts_editor = QGroupBox()
        editor_form = QFormLayout(self.grp_ts_editor)
        self.lbl_ts_editor_font = QLabel()
        self.combo_ts_editor_font = QFontComboBox()
        self.combo_ts_editor_font.setCurrentFont(QFont(str(getattr(self.canvas, 'texstudio_editor_font_family', 'Consolas'))))
        self.combo_ts_editor_font.currentFontChanged.connect(self._apply)
        editor_form.addRow(self.lbl_ts_editor_font, self.combo_ts_editor_font)
        self.lbl_ts_editor_size = QLabel()
        self.spin_ts_editor_size = QSpinBox()
        self.spin_ts_editor_size.setRange(6, 72)
        self.spin_ts_editor_size.setValue(int(getattr(self.canvas, 'texstudio_editor_font_size', 16)))
        self.spin_ts_editor_size.valueChanged.connect(self._apply)
        editor_form.addRow(self.lbl_ts_editor_size, self.spin_ts_editor_size)
        self.lbl_ts_editor_color = QLabel()
        self.btn_ts_editor_color = QPushButton()
        self._set_texstudio_color_button(self.btn_ts_editor_color, self._canvas_color('texstudio_editor_color', '#111827'))
        self.btn_ts_editor_color.clicked.connect(lambda _checked=False: self._choose_texstudio_color(self.btn_ts_editor_color, 'Chọn màu chữ code'))
        editor_form.addRow(self.lbl_ts_editor_color, self.btn_ts_editor_color)
        self.lbl_ts_editor_bg = QLabel()
        self.btn_ts_editor_bg = QPushButton()
        self._set_texstudio_color_button(self.btn_ts_editor_bg, self._canvas_color('texstudio_editor_background', '#ffffff'))
        self.btn_ts_editor_bg.clicked.connect(lambda _checked=False: self._choose_texstudio_color(self.btn_ts_editor_bg, 'Chọn màu nền code'))
        editor_form.addRow(self.lbl_ts_editor_bg, self.btn_ts_editor_bg)
        self.chk_ts_rainbow = QCheckBox()
        self.chk_ts_rainbow.setChecked(bool(getattr(self.canvas, 'texstudio_editor_rainbow', True)))
        self.chk_ts_rainbow.stateChanged.connect(self._apply)
        editor_form.addRow('', self.chk_ts_rainbow)
        outer.addWidget(self.grp_ts_editor)
        self.grp_ts_preview = QGroupBox()
        preview_form = QFormLayout(self.grp_ts_preview)
        self.lbl_ts_preview_font = QLabel()
        self.combo_ts_preview_font = QFontComboBox()
        self.combo_ts_preview_font.setCurrentFont(QFont(str(getattr(self.canvas, 'texstudio_preview_font_family', 'Arial'))))
        self.combo_ts_preview_font.currentFontChanged.connect(self._apply)
        preview_form.addRow(self.lbl_ts_preview_font, self.combo_ts_preview_font)
        self.lbl_ts_preview_size = QLabel()
        self.spin_ts_preview_size = QSpinBox()
        self.spin_ts_preview_size.setRange(1, 200)
        self.spin_ts_preview_size.setValue(int(getattr(self.canvas, 'texstudio_preview_font_size', 16)))
        self.spin_ts_preview_size.valueChanged.connect(self._apply)
        preview_form.addRow(self.lbl_ts_preview_size, self.spin_ts_preview_size)
        self.lbl_ts_preview_color = QLabel()
        self.btn_ts_preview_color = QPushButton()
        self._set_texstudio_color_button(self.btn_ts_preview_color, self._canvas_color('texstudio_preview_text_color', '#111827'))
        self.btn_ts_preview_color.clicked.connect(lambda _checked=False: self._choose_texstudio_color(self.btn_ts_preview_color, 'Chọn màu chữ kết quả'))
        preview_form.addRow(self.lbl_ts_preview_color, self.btn_ts_preview_color)
        self.lbl_ts_preview_bg = QLabel()
        self.btn_ts_preview_bg = QPushButton()
        self._set_texstudio_color_button(self.btn_ts_preview_bg, self._canvas_color('texstudio_preview_background', '#fffbeb'))
        self.btn_ts_preview_bg.clicked.connect(lambda _checked=False: self._choose_texstudio_color(self.btn_ts_preview_bg, 'Chọn màu nền kết quả'))
        preview_form.addRow(self.lbl_ts_preview_bg, self.btn_ts_preview_bg)
        self.lbl_ts_split = QLabel()
        self.spin_ts_split = QSpinBox()
        self.spin_ts_split.setRange(25, 75)
        self.spin_ts_split.setSuffix(' %')
        self.spin_ts_split.setValue(int(getattr(self.canvas, 'texstudio_split_percent', 50)))
        self.spin_ts_split.valueChanged.connect(self._apply)
        preview_form.addRow(self.lbl_ts_split, self.spin_ts_split)
        outer.addWidget(self.grp_ts_preview)

        # ── TeXstudio Actions Section ──
        grp_actions = QGroupBox("សកម្មភាព TeXstudio (TeXstudio Actions)")
        actions_layout = QHBoxLayout(grp_actions)
        actions_layout.setSpacing(10)

        self.btn_open_texstudio = QPushButton("🚀 បើក TeXstudio & ចម្លងខ្លឹមសារ")
        self.btn_open_texstudio.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-weight: bold;
                padding: 8px 14px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        self.btn_open_texstudio.clicked.connect(self._open_texstudio_with_content)
        actions_layout.addWidget(self.btn_open_texstudio)

        self.btn_copy_texstudio = QPushButton("📋 ចម្លងកូដ/ខ្លឹមសារ (Copy)")
        self.btn_copy_texstudio.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #0f172a;
                font-weight: 600;
                padding: 8px 14px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #e2e8f0;
            }
        """)
        self.btn_copy_texstudio.clicked.connect(self._copy_texstudio_content)
        actions_layout.addWidget(self.btn_copy_texstudio)

        outer.addWidget(grp_actions)
        outer.addStretch(1)
        self._sync_texstudio_enabled()

    def _extract_all_canvas_text(self):
        """Extract all written text, LaTeX formulas, and annotations from canvas slides."""
        parts = []
        if self.canvas and hasattr(self.canvas, "_slides"):
            for idx, slide in enumerate(self.canvas._slides, 1):
                slide_texts = []
                for el in getattr(slide, "elements", []):
                    if getattr(el, "kind", "") == "text":
                        md = getattr(el, "markdown", "") or getattr(el, "text", "")
                        if md.strip():
                            slide_texts.append(md.strip())
                if slide_texts:
                    parts.append(f"% ── Slide {idx} ──\n" + "\n\n".join(slide_texts))

        if not parts:
            from pathlib import Path
            tpl_path = Path(__file__).resolve().parent.parent / "config" / "templates" / "extest" / "style.tex"
            if tpl_path.exists():
                return tpl_path.read_text(encoding="utf-8")
            return "% eDraw LaTeX Document\n\\documentclass[12pt,a4paper]{article}\n\\usepackage{amsmath,amssymb}\n\\usepackage{tikz}\n\\begin{document}\n\n\\end{document}"

        body = "\n\n".join(parts)
        full_doc = (
            "\\documentclass[12pt,a4paper]{article}\n"
            "\\usepackage[a4paper,margin=2cm]{geometry}\n"
            "\\usepackage{amsmath,amssymb,amsfonts}\n"
            "\\usepackage{tikz}\n"
            "\\usepackage{tkz-euclide}\n"
            "\\usepackage{iftex}\n"
            "\\ifXeTeX\n"
            "  \\usepackage{fontspec}\n"
            "  \\IfFontExistsTF{Khmer OS}{\\setmainfont{Khmer OS}}{}\n"
            "\\fi\n\n"
            "\\begin{document}\n\n"
            f"{body}\n\n"
            "\\end{document}\n"
        )
        return full_doc

    def _copy_texstudio_content(self):
        content = self._extract_all_canvas_text()
        from PyQt6.QtWidgets import QApplication, QMessageBox
        QApplication.clipboard().setText(content)
        QMessageBox.information(
            self,
            "TeXstudio",
            "បានចម្លងខ្លឹមសារទាំងអស់ទៅកាន់ Clipboard រួចរាល់ហើយ! (Copied to Clipboard)",
        )

    def _open_texstudio_with_content(self):
        content = self._extract_all_canvas_text()
        from PyQt6.QtWidgets import QApplication, QMessageBox
        import tempfile, os, glob, subprocess, sys

        QApplication.clipboard().setText(content)

        tmp_dir = tempfile.gettempdir()
        tex_file = os.path.join(tmp_dir, "edraw_texstudio_export.tex")
        with open(tex_file, "w", encoding="utf-8") as f:
            f.write(content)

        opened = False
        if sys.platform == "darwin":
            candidates = [
                "/Applications/texstudio-4.9.2-osx-m1.app",
                "/Applications/texstudio.app",
                "/Applications/TeXstudio.app",
            ] + glob.glob("/Applications/*texstudio*.app")

            app_to_open = None
            for cand in candidates:
                if os.path.exists(cand):
                    app_to_open = cand
                    break

            if app_to_open:
                subprocess.Popen(["open", "-a", app_to_open, tex_file])
                opened = True
            else:
                subprocess.Popen(["open", tex_file])
                opened = True
        elif sys.platform == "win32":
            win_paths = [
                r"C:\Program Files\texstudio\texstudio.exe",
                r"C:\Program Files (x86)\texstudio\texstudio.exe",
            ]
            for p in win_paths:
                if os.path.exists(p):
                    subprocess.Popen([p, tex_file])
                    opened = True
                    break
            if not opened:
                os.startfile(tex_file)
                opened = True
        else:
            import shutil
            ts_bin = shutil.which("texstudio")
            if ts_bin:
                subprocess.Popen([ts_bin, tex_file])
                opened = True
            else:
                subprocess.Popen(["xdg-open", tex_file])
                opened = True

        QMessageBox.information(
            self,
            "TeXstudio",
            "បានចម្លងខ្លឹមសារទៅ Clipboard និងបានបើកកម្មវិធី TeXstudio ដោយជោគជ័យ! 🎉",
        )

    def _canvas_color(self = None, attr = None, default = None):
        color = QColor(getattr(self.canvas, attr, QColor(default)))
        if color.isValid():
            return color
        return QColor(default)

    
    def _set_texstudio_color_button(self = None, button = None, color = None):
        c = QColor(color)
        if not c.isValid():
            c = QColor('#111827')
        button.setProperty('edraw_color', c.name(QColor.NameFormat.HexArgb))
        text = 'white' if c.lightness() < 128 else 'black'
        button.setStyleSheet(f'''background-color:{c.name()};color:{text};border:1px solid gray;padding:5px;''')
        button.setText(t('Chọn màu…'))

    
    def _texstudio_button_color(self = None, button = None, default = None):
        if not button.property('edraw_color'):
            button.property('edraw_color')
        color = QColor(str(default))
        if color.isValid():
            return color
        return QColor(default)

    
    def _choose_texstudio_color(self = None, button = None, title = None):
        current = self._texstudio_button_color(button, '#111827')
        color = QColorDialog.getColor(current, self, t(title))
        if color.isValid():
            self._set_texstudio_color_button(button, color)
            self._apply()
            return None

    
    def _refresh_texstudio_color_buttons(self = None):
        if not hasattr(self, 'btn_ts_editor_color'):
            return None
        for button, default in ((self.btn_ts_editor_color, '#111827'), (self.btn_ts_editor_bg, '#ffffff'), (self.btn_ts_preview_color, '#111827'), (self.btn_ts_preview_bg, '#fffbeb')):
            self._set_texstudio_color_button(button, self._texstudio_button_color(button, default))

    
    def _refresh_texts(self = None):
        self.setWindowTitle(t('Cài đặt Bảng'))
        if hasattr(self, 'tabs'):
            self.tabs.setTabText(0, t('Bảng'))
            self.tabs.setTabText(1, t('Bút'))
            self.tabs.setTabText(2, 'TeXstudio')
        self.lbl_language.setText(t('Ngôn ngữ:'))
        self.combo_language.blockSignals(True)
        for i in range(self.combo_language.count()):
            code = self.combo_language.itemData(i)
            self.combo_language.setItemText(i, language_name(code))
        lang_idx = self.combo_language.findData(current_language())
        if lang_idx >= 0:
            self.combo_language.setCurrentIndex(lang_idx)
        self.combo_language.blockSignals(False)
        self.lbl_board_color.setText(t('Màu nền bảng:'))
        self.chk_h.setText(t('Bật lưới kẻ ngang'))
        self.chk_v.setText(t('Bật lưới kẻ dọc'))
        self.lbl_grid_thickness.setText(t('Độ dày nét lưới:'))
        self.lbl_grid_spacing.setText(t('Khoảng cách ô:'))
        self.lbl_toolbar_height.setText(t('Chiều cao thanh công cụ:'))
        self.spin_toolbar_height.setToolTip(t('Giảm để toolbar gọn hơn, tăng nếu muốn nút dễ bấm hơn.'))
        self.lbl_tool_group_height.setText(t('Chiều cao nhóm công cụ:'))
        self.spin_tool_group_height.setToolTip(t('Điều chỉnh chiều cao các khung nhóm công cụ độc lập với chiều cao toàn toolbar.'))
        self.chk_toolbar_vertical.setText(t('Đặt dọc'))
        self.chk_toolbar_vertical.setToolTip(t('Thu gọn thanh công cụ thành cột dọc ở cạnh trái màn hình.'))
        self.grp_pen_basic.setTitle(t('Cơ bản'))
        self.lbl_smoothing.setText(t('Độ mượt nét viết tay:'))
        self.lbl_min_dist.setText(t('Lọc điểm tối thiểu:'))
        self.spin_min_dist.setToolTip(t('0.0 = tự tính theo độ dày bút'))
        self.lbl_ink_min_dist.setText(t('Khoảng cách mẫu tối thiểu (px):'))
        self.spin_ink_min_dist.setToolTip(t('Bỏ qua sample gần sample trước. Quá cao mất chi tiết; quá thấp tốn CPU.'))
        self.chk_pressure.setText(t('Dùng áp lực bút nếu thiết bị hỗ trợ'))
        self.chk_final_smoothing.setText(t('Làm mượt nét khi nhấc bút'))
        self.chk_final_smoothing.setToolTip(t('Khi bật, eDraw dựng lại nét mượt hơn sau khi nhấc bút. Mặc định tắt để nét không đổi hình ở cuối thao tác.'))
        self.grp_one_euro.setTitle(t('Bộ lọc nét (OneEuro)'))
        self.lbl_one_euro_cutoff.setText(t('Cutoff cơ bản:'))
        self.spin_one_euro_cutoff.setToolTip(t('Khử rung tay lúc dừng. Tăng để bám tay sát hơn, giảm để lọc tremor mạnh hơn.'))
        self.lbl_one_euro_beta.setText(t('Độ nhạy theo tốc độ (beta):'))
        self.spin_one_euro_beta.setToolTip(t('Filter mở khi tay viết nhanh. Tăng để bám tay khi viết tốc cao, giảm để giữ nét mượt.'))
        self.grp_lead.setTitle(t('Đầu bút dự đoán'))
        self.lbl_lead_lookahead.setText(t('Độ dự đoán (ms):'))
        self.spin_lead_lookahead.setToolTip(t('Đầu bút đi trước ngón bao nhiêu ms. 0 = đầu bút đúng vị trí ngón; tăng để bù latency input→màn hình, quá cao dễ rubber-band.'))
        self.lbl_lead_speed.setText(t('Ngưỡng tốc độ dự đoán (px/s):'))
        self.spin_lead_speed.setToolTip(t('Chỉ dự đoán khi tay viết nhanh hơn ngưỡng (tránh overshoot khi viết chậm).'))
        self.grp_dynamic.setTitle(t('Bề rộng động'))
        self.lbl_pressure_strength.setText(t('Ảnh hưởng lực bút:'))
        self.spin_pressure_strength.setToolTip(t('Bề rộng nét theo lực bút. 0 = tắt, 1 = ảnh hưởng đầy đủ.'))
        self.lbl_velocity_strength.setText(t('Ảnh hưởng tốc độ:'))
        self.spin_velocity_strength.setToolTip(t('Nét nhỏ lại khi tay viết nhanh. 0 = tắt.'))
        self.chk_follow_pen.setText(t('Thuộc tính phụ thuộc bút'))
        self.chk_follow_pen.setToolTip(t('Khi bật, các công cụ hình học dùng màu, nét, độ dày và độ mờ của bút vẽ đang chọn.'))
        self.lbl_latex.setText(t('Lệnh PdfLaTeX:'))
        self.edit_pdflatex.setPlaceholderText(t('Dán dòng PdfLaTeX trong TeXstudio, ví dụ: pdflatex.exe -synctex=1 -interaction=nonstopmode %.tex'))
        self.btn_pdflatex_browse.setText(t('Chọn…'))
        self.btn_pdflatex_clear.setText(t('Xoá'))
        if hasattr(self, 'btn_preamble'):
            self.btn_preamble.setText(t('Preamble & ទំហំទំព័រ…'))
        self.chk_ts_split_mode.setText(t('Bật bố cục TeXstudio chia đôi'))
        self.chk_ts_split_mode.setToolTip(t('Bỏ chọn để dùng chế độ gõ chữ hiện tại; các tùy chỉnh TeXstudio bên dưới sẽ bị khóa.'))
        self.chk_editable_text.setText(t('Chỉnh văn bản'))
        self.chk_editable_text.setToolTip(t('Khi bật, khối markdown sau khi nhập sẽ được lưu dưới dạng đối tượng văn bản và có thể chỉnh sửa lại bằng cách click vào trong chế độ Gõ chữ. Mặc định: tắt (đè thẳng vào bảng như ảnh).'))
        self.grp_ts_editor.setTitle(t('Cửa sổ code'))
        self.lbl_ts_editor_font.setText(t('Font chữ:'))
        self.lbl_ts_editor_size.setText(t('Cỡ chữ:'))
        self.lbl_ts_editor_color.setText(t('Màu chữ:'))
        self.lbl_ts_editor_bg.setText(t('Màu nền:'))
        self.chk_ts_rainbow.setText(t('Giữ màu chữ cầu vồng mặc định'))
        self.chk_ts_rainbow.setToolTip(t('Khi bật, editor vẫn tô từng ký tự bằng màu cầu vồng như hiện tại.'))
        self.grp_ts_preview.setTitle(t('Cửa sổ kết quả render'))
        self.lbl_ts_preview_font.setText(t('Font chữ:'))
        self.lbl_ts_preview_size.setText(t('Cỡ chữ:'))
        self.lbl_ts_preview_color.setText(t('Màu chữ:'))
        self.lbl_ts_preview_bg.setText(t('Màu nền:'))
        self.lbl_ts_split.setText(t('Bề rộng cửa sổ code:'))
        self._refresh_texstudio_color_buttons()
        self._sync_texstudio_enabled()
        self.btn_defaults.setText(t('Mặc định'))
        self.btn_close.setText(t('Đóng'))
        self._refresh_color_btn()

    
    def _on_language_change(self = None):
        language = self.combo_language.currentData()
        if not language:
            return None
        set_language(str(language))
        self._refresh_texts()
        parent = self.parent()
        if parent:
            if hasattr(parent, '_refresh_localized_texts'):
                parent._refresh_localized_texts()
                return None
            return None

    
    def _refresh_color_btn(self = None):
        c = self.canvas.board_color
        text = 'white' if c.lightness() < 128 else 'black'
        self.btn_color.setStyleSheet(f'''background-color:{c.name()};color:{text};border:1px solid gray;padding:5px;''')
        self.btn_color.setText(t('Chọn màu…'))

    
    def _choose_color(self = None):
        color = QColorDialog.getColor(self.canvas.board_color, self, t('Chọn màu nền'))
        if color.isValid():
            self.canvas.board_color = color
            self._refresh_color_btn()
            self.canvas.update()
            return None

    
    def _choose_pdflatex(self = None):
        if not self.edit_pdflatex.text().strip():
            self.edit_pdflatex.text().strip()
        (path, _) = QFileDialog.getOpenFileName(self, t('Chọn pdflatex'), '/Library/TeX/texbin')
        if path:
            self.edit_pdflatex.setText(path)
            self._save_pdflatex()
            return None

    
    def _clear_pdflatex(self = None):
        self.edit_pdflatex.clear()
        self._save_pdflatex()

    
    def _save_pdflatex(self = None):
        save_pdflatex_command(self.edit_pdflatex.text())

    def _open_preamble_dialog(self = None):
        from dialogs.latex_preamble_dialog import LatexPreambleDialog
        dlg = LatexPreambleDialog(self, canvas=self.canvas)
        dlg.exec()

    
    def _sync_toolbar_size_ranges(self = None):
        parent = self.parent()
        vertical = self.chk_toolbar_vertical.isChecked()
        min_h = getattr(parent, 'VERTICAL_MIN_TOOLBAR_HEIGHT' if vertical else 'MIN_TOOLBAR_HEIGHT', 16 if vertical else 28)
        max_h = getattr(parent, 'MAX_TOOLBAR_HEIGHT', 64)
        min_group_h = getattr(parent, 'VERTICAL_MIN_TOOL_GROUP_HEIGHT' if vertical else 'MIN_TOOL_GROUP_HEIGHT', 16 if vertical else 24)
        max_group_h = getattr(parent, 'MAX_TOOL_GROUP_HEIGHT', 56)
        old_toolbar_block = self.spin_toolbar_height.blockSignals(True)
        old_group_block = self.spin_tool_group_height.blockSignals(True)
        self.spin_toolbar_height.setRange(min_h, max_h)
        self.spin_tool_group_height.setRange(min_group_h, max_group_h)
        self.spin_toolbar_height.blockSignals(old_toolbar_block)
        self.spin_tool_group_height.blockSignals(old_group_block)

    
    def _sync_texstudio_enabled(self = None):
        if not hasattr(self, 'chk_ts_split_mode'):
            return None
        allowed = self._texstudio_allowed()
        self.chk_ts_split_mode.setEnabled(True)
        if not allowed:
            self._force_texstudio_split_unchecked()
            self.chk_ts_split_mode.setToolTip(t('Chỉ tài khoản PRO được bật bố cục TeXstudio chia đôi.'))
            enabled = False
        else:
            self.chk_ts_split_mode.setToolTip(t('Bỏ chọn để dùng chế độ gõ chữ hiện tại; các tùy chỉnh TeXstudio bên dưới sẽ bị khóa.'))
            enabled = self.chk_ts_split_mode.isChecked()
        if enabled and self.chk_editable_text.isChecked():
            blocked = self.chk_editable_text.blockSignals(True)
            self.chk_editable_text.setChecked(False)
            self.chk_editable_text.blockSignals(blocked)
        for widget in (self.chk_editable_text, self.grp_ts_editor, self.grp_ts_preview):
            widget.setEnabled(enabled)

    
    def _texstudio_allowed(self = None):
        return True

    
    def _show_texstudio_pro_required(self = None):
        if self._texstudio_upgrade_prompt_open:
            return None
        self._texstudio_upgrade_prompt_open = True
        
        try:
            QMessageBox.information(self, t('Cần nâng cấp PRO'), t('Bố cục TeXstudio chia đôi chỉ dành cho tài khoản PRO. Vui lòng nâng cấp lên PRO để sử dụng tính năng này.'))
            self._texstudio_upgrade_prompt_open = False
            return None
        except:
            self._texstudio_upgrade_prompt_open = False


    
    def _force_texstudio_split_unchecked(self = None):
        if not hasattr(self, 'chk_ts_split_mode'):
            return None
        blocked = self.chk_ts_split_mode.blockSignals(True)
        self.chk_ts_split_mode.setChecked(False)
        self.chk_ts_split_mode.blockSignals(blocked)
        if hasattr(self, 'chk_editable_text'):
            blocked = self.chk_editable_text.blockSignals(True)
            self.chk_editable_text.setChecked(False)
            self.chk_editable_text.blockSignals(blocked)
        self.canvas.texstudio_layout_mode = 'inline'
        self.canvas.editable_text_mode = False
        apply_type_settings = getattr(self.canvas, 'apply_texstudio_type_settings', None)
        if callable(apply_type_settings):
            apply_type_settings()
            return None

    
    def _guard_texstudio_split_mode(self = None, state = None):
        if not state == Qt.CheckState.Checked.value:
            state == Qt.CheckState.Checked.value
            if not state == Qt.CheckState.Checked:
                state == Qt.CheckState.Checked
        checked = self.chk_ts_split_mode.isChecked()
        if checked:
            if not self._texstudio_allowed():
                self._force_texstudio_split_unchecked()
                self._show_texstudio_pro_required()
                self._force_texstudio_split_unchecked()
                QTimer.singleShot(0, self._force_texstudio_split_unchecked)
                return None
            return None

    
    def _block_texstudio_signals(self = None, block = None):
        if not hasattr(self, 'chk_ts_split_mode'):
            return None
        for widget in (self.chk_ts_split_mode, self.combo_ts_editor_font, self.spin_ts_editor_size, self.chk_ts_rainbow, self.combo_ts_preview_font, self.spin_ts_preview_size, self.spin_ts_split, self.chk_editable_text):
            widget.blockSignals(block)

    
    def _set_texstudio_defaults(self = None):
        self.chk_ts_split_mode.setChecked(False)
        self.combo_ts_editor_font.setCurrentFont(QFont('Consolas'))
        self.spin_ts_editor_size.setValue(16)
        self._set_texstudio_color_button(self.btn_ts_editor_color, QColor('#111827'))
        self._set_texstudio_color_button(self.btn_ts_editor_bg, QColor('#ffffff'))
        self.chk_ts_rainbow.setChecked(True)
        self.combo_ts_preview_font.setCurrentFont(QFont('Arial'))
        self.spin_ts_preview_size.setValue(16)
        self._set_texstudio_color_button(self.btn_ts_preview_color, QColor('#111827'))
        self._set_texstudio_color_button(self.btn_ts_preview_bg, QColor('#fffbeb'))
        self.spin_ts_split.setValue(50)
        self.canvas.texstudio_layout_mode = 'inline'
        self.canvas.texstudio_editor_font_family = 'Consolas'
        self.canvas.texstudio_editor_font_size = 16
        self.canvas.texstudio_editor_color = QColor('#111827')
        self.canvas.texstudio_editor_background = QColor('#ffffff')
        self.canvas.texstudio_editor_rainbow = True
        self.canvas.texstudio_preview_font_family = 'Arial'
        self.canvas.texstudio_preview_font_size = 16
        self.canvas.texstudio_preview_text_color = QColor('#111827')
        self.canvas.texstudio_preview_background = QColor('#fffbeb')
        self.canvas.texstudio_split_percent = 50
        apply_type_settings = getattr(self.canvas, 'apply_texstudio_type_settings', None)
        if callable(apply_type_settings):
            apply_type_settings()
        self._sync_texstudio_enabled()

    
    def _defaults(self = None):
        if self._on_reset:
            self._on_reset()
        from core.app_settings import DEFAULT_LANGUAGE
        set_language(DEFAULT_LANGUAGE)
        self._refresh_texts()
        parent = self.parent()
        if parent and hasattr(parent, '_refresh_localized_texts'):
            parent._refresh_localized_texts()
        pen_widgets = (self.slider_smooth, self.spin_min_dist, self.spin_ink_min_dist, self.chk_pressure, self.chk_final_smoothing, self.spin_one_euro_cutoff, self.spin_one_euro_beta, self.spin_lead_lookahead, self.spin_lead_speed, self.spin_pressure_strength, self.spin_velocity_strength)
        board_widgets = (self.chk_h, self.chk_v, self.spin_thick, self.spin_spacing, self.spin_toolbar_height, self.spin_tool_group_height, self.chk_toolbar_vertical, self.chk_follow_pen, self.chk_editable_text, self.edit_pdflatex)
        for w in board_widgets + pen_widgets:
            w.blockSignals(True)
        self._block_texstudio_signals(True)
        self.chk_h.setChecked(True)
        self.chk_v.setChecked(True)
        self.spin_thick.setValue(1)
        self.spin_spacing.setValue(40)
        self.spin_toolbar_height.setValue(getattr(self.parent(), 'DEFAULT_TOOLBAR_HEIGHT', 33))
        self.spin_tool_group_height.setValue(getattr(self.parent(), 'DEFAULT_TOOL_GROUP_HEIGHT', 27))
        self.chk_toolbar_vertical.setChecked(False)
        self.slider_smooth.setValue(52)
        self.spin_min_dist.setValue(0)
        self.spin_ink_min_dist.setValue(0.5)
        self.chk_pressure.setChecked(False)
        self.chk_final_smoothing.setChecked(False)
        self.spin_one_euro_cutoff.setValue(2.5)
        self.spin_one_euro_beta.setValue(0.5)
        self.spin_lead_lookahead.setValue(0)
        self.spin_lead_speed.setValue(1000)
        self.spin_pressure_strength.setValue(1)
        self.spin_velocity_strength.setValue(0.1)
        self.chk_follow_pen.setChecked(True)
        e = self.canvas.engine
        e.tool_attrs_follow_pen = True
        e.use_pressure = False
        e.ink_sampling_min_distance = 0.5
        e.final_stroke_smoothing_enabled = False
        e.one_euro.set_params(min_cutoff = 2.5, beta = 0.5)
        e._lead_lookahead_sec = 0
        e._lead_predict_min_speed = 1000
        e.pressure_width_strength = 1
        e.velocity_width_strength = 0.1
        self._last_follow_pen = True
        self.chk_editable_text.setChecked(False)
        self.canvas.editable_text_mode = False
        self.edit_pdflatex.clear()
        save_pdflatex_command('')
        self.edit_pdflatex.setText(display_pdflatex_command())
        self._set_texstudio_defaults()
        self._refresh_color_btn()
        for w in board_widgets + pen_widgets:
            w.blockSignals(False)
        self._block_texstudio_signals(False)
        self._sync_toolbar_size_ranges()

    
    def _apply(self = None):
        self.canvas.grid_h = self.chk_h.isChecked()
        self.canvas.grid_v = self.chk_v.isChecked()
        self.canvas.grid_thickness = self.spin_thick.value()
        self.canvas.grid_spacing = self.spin_spacing.value()
        self._sync_toolbar_size_ranges()
        parent = self.parent()
        if parent and hasattr(parent, '_set_toolbar_vertical'):
            parent._set_toolbar_vertical(self.chk_toolbar_vertical.isChecked())
        if parent and hasattr(parent, '_set_toolbar_height'):
            parent._set_toolbar_height(self.spin_toolbar_height.value())
        if parent and hasattr(parent, '_set_tool_group_height'):
            parent._set_tool_group_height(self.spin_tool_group_height.value())
        e = self.canvas.engine
        e.freehand_smoothing = self.slider_smooth.value() / 100
        e.freehand_min_distance = float(self.spin_min_dist.value())
        e.ink_sampling_min_distance = float(self.spin_ink_min_dist.value())
        e.use_pressure = self.chk_pressure.isChecked()
        e.final_stroke_smoothing_enabled = self.chk_final_smoothing.isChecked()
        e.one_euro.set_params(min_cutoff = float(self.spin_one_euro_cutoff.value()), beta = float(self.spin_one_euro_beta.value()))
        e._lead_lookahead_sec = float(self.spin_lead_lookahead.value()) / 1000
        e._lead_predict_min_speed = float(self.spin_lead_speed.value())
        e.pressure_width_strength = float(self.spin_pressure_strength.value())
        e.velocity_width_strength = float(self.spin_velocity_strength.value())
        if hasattr(self, 'chk_ts_split_mode'):
            texstudio_allowed = self._texstudio_allowed()
            if texstudio_allowed:
                split_mode = self.chk_ts_split_mode.isChecked()
            else:
                self._force_texstudio_split_unchecked()
                split_mode = False
            self.canvas.texstudio_layout_mode = 'split' if split_mode else 'inline'
            if split_mode:
                split_mode
            self.canvas.editable_text_mode = self.chk_editable_text.isChecked()
            self.canvas.texstudio_editor_font_family = self.combo_ts_editor_font.currentFont().family()
            self.canvas.texstudio_editor_font_size = int(self.spin_ts_editor_size.value())
            self.canvas.texstudio_editor_color = self._texstudio_button_color(self.btn_ts_editor_color, '#111827')
            self.canvas.texstudio_editor_background = self._texstudio_button_color(self.btn_ts_editor_bg, '#ffffff')
            self.canvas.texstudio_editor_rainbow = self.chk_ts_rainbow.isChecked()
            self.canvas.texstudio_preview_font_family = self.combo_ts_preview_font.currentFont().family()
            self.canvas.texstudio_preview_font_size = int(self.spin_ts_preview_size.value())
            self.canvas.texstudio_preview_text_color = self._texstudio_button_color(self.btn_ts_preview_color, '#111827')
            self.canvas.texstudio_preview_background = self._texstudio_button_color(self.btn_ts_preview_bg, '#fffbeb')
            self.canvas.texstudio_split_percent = int(self.spin_ts_split.value())
            apply_type_settings = getattr(self.canvas, 'apply_texstudio_type_settings', None)
            if callable(apply_type_settings):
                apply_type_settings()
            self._sync_texstudio_enabled()
        else:
            self.canvas.editable_text_mode = self.chk_editable_text.isChecked()
        follow_pen = self.chk_follow_pen.isChecked()
        if follow_pen != self._last_follow_pen:
            parent = self.parent()
            if parent and hasattr(parent, '_set_tool_attrs_follow_pen'):
                parent._set_tool_attrs_follow_pen(follow_pen)
            else:
                self.canvas.engine.tool_attrs_follow_pen = follow_pen
                if not follow_pen:
                    self.canvas.engine.reset_tool_attrs_to_defaults()
            self._last_follow_pen = follow_pen
        self.canvas.update()

