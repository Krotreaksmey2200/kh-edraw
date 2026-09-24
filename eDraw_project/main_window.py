"""
main_window.py
Cửa sổ chính: toolbar trực quan + canvas + shortcut.

Phần thân được chia nhỏ vào các mixin trong  và :

  ui.icons_mixin        — vẽ icon vector
  ui.toolbar_mixin      — build toolbar và các nút công cụ
  ui.account_mixin      — avatar Google / login button
  actions.modes_mixin   — chọn mode + đồng bộ trạng thái UI
  actions.files_mixin   — image/PDF/settings/login/reset
  actions.ai_mixin      — AI custom tool + sinh đề câu hỏi
  actions.custom_tools_mixin — install/edit/rename/delete công cụ AI

Class  chỉ giữ phần khởi tạo state, shortcut, slide nav,
event handler và composition các mixin trên.
"""
from __future__ import annotations
from pathlib import Path
import sys
from PyQt6.QtCore import QEvent, QMimeData, QRect, QTimer, Qt, QUrl
from PyQt6.QtGui import QAction, QColor, QCursor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QToolTip,
)
from actions.ai_mixin import AIMixin
from actions.custom_tools_mixin import CustomToolsMixin
from actions.files_mixin import FilesMixin
from actions.modes_mixin import ModesMixin
from actions.python_figure_mixin import PythonFigureMixin
from core.app_icon import load_app_icon
from core.app_settings import save as settings_save
from core.drawing_engine import DrawMode
from core.i18n import t
from core.screen_recorder import WindowScreenRecorder
from core.updater import current_version
from ui.account_mixin import AccountMixin
from ui.constants import MENU_STYLE
from ui.icons_mixin import IconsMixin
from ui.toolbar_mixin import ToolbarMixin
from widgets.mirror_window import MirrorWindow

PLAN_BASIC = 'BASIC'
PLAN_PLUS = 'PLUS'
PLAN_PRO = 'PRO'
VALID_PLANS = {PLAN_BASIC, PLAN_PLUS, PLAN_PRO}
PLUS_OR_HIGHER_PLANS = {PLAN_PLUS, PLAN_PRO}


def _resource_root() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


VERSION_FILE = _resource_root() / 'config' / 'version.txt'

AI_TOOL_TYPE_LABELS = {
    'line': 'Đường thẳng',
    'geometry': 'Điểm/Đường đặc biệt',
    'curve': 'Đường cong',
    'polygon': 'Đa giác',
    'free': 'Tự do',
}

PLAN_LIMITS = {
    PLAN_PRO: {
        'extra_pens': None,
        'ai_tools_per_group': None,
        'can_edit_code': True,
        'figure_templates': None,
        'can_delete_figure_templates': True,
    },
    PLAN_PLUS: {
        'extra_pens': 5,
        'ai_tools_per_group': 5,
        'can_edit_code': False,
        'figure_templates': 5,
        'can_delete_figure_templates': False,
    },
    PLAN_BASIC: {
        'extra_pens': 1,
        'ai_tools_per_group': 2,
        'can_edit_code': False,
        'figure_templates': 2,
        'can_delete_figure_templates': False,
    },
}


def _app_title_name() -> str:
    version = current_version()
    if version:
        return f'eDraw v{version}'
    return 'eDraw'


class MainWindow(
    QMainWindow,
    PythonFigureMixin,
    CustomToolsMixin,
    AIMixin,
    FilesMixin,
    ModesMixin,
    IconsMixin,
    AccountMixin,
    ToolbarMixin,
):
    AVATAR_SIZE = 36
    DEFAULT_PEN_SLOT_COUNT = 2
    DEFAULT_PEN2_SLOT_COUNT = 1
    DEFAULT_HIGHLIGHT_SLOT_COUNT = 1

    def __init__(
        self,
        user_plan: str = 'BASIC',
        user_email: str = '',
        user_uid: str = '',
        user_picture_url: str = '',
    ) -> None:
        super().__init__()
        self.setWindowIcon(self._load_app_icon())
        normalized_plan = (user_plan or PLAN_BASIC).upper()
        self._user_plan = PLAN_PRO
        self._user_email = user_email or ''
        self._user_uid = user_uid or ''
        self._user_picture_url = user_picture_url or ''
        self._avatar_pixmap = self._load_user_avatar_pixmap()
        self._refresh_window_title()
        self._current_line_mode = DrawMode.LINE
        self._current_curve_mode = DrawMode.BEZIER
        self._current_polygon_mode = DrawMode.TRIANGLE
        self._mode_controls = {}
        self._line_actions = {}
        self._curve_actions = {}
        self._polygon_actions = {}
        self._custom_curve_actions = {}
        self._custom_line_actions = {}
        self._custom_geometry_actions = {}
        self._geometry_actions = {}
        self._custom_polygon_actions = {}
        self._free_actions = {}
        self._custom_free_actions = {}
        self._current_custom_tool_name = None
        self._current_free_tool_name = None
        self._line_menu = None
        self._line_menu_separator = None
        self._geometry_menu = None
        self._geometry_menu_separator = None
        self._curve_menu = None
        self._curve_menu_separator = None
        self._polygon_menu = None
        self._polygon_menu_separator = None
        self._free_menu = None
        self._free_menu_separator = None
        self._ai_thread = None
        self._tikz_ai_thread = None
        self._tikz_ai_worker = None
        self._tikz_ai_log = None
        self._tikz_ai_dialog = None
        self._tikz_ai_target = None
        self._handwriting_ai_thread = None
        self._handwriting_ai_worker = None
        self._handwriting_ai_log = None
        self._handwriting_ai_target = None
        self._curve_tool_thread = None
        self._curve_tool_worker = None
        self._curve_tool_log = None
        self._py_fig_pending_element = None
        self._mirror_window = None
        self._screen_recorder = WindowScreenRecorder(
            self, excluded_rect_provider=self._screen_recording_excluded_rects
        )
        self._pen_slots = [
            {
                'color': QColor(Qt.GlobalColor.black),
                'width': 3,
                'opacity': 100,
                'style_idx': 0,
            },
            {
                'color': QColor('#2563eb'),
                'width': 3,
                'opacity': 100,
                'style_idx': 0,
            },
        ]
        self._active_pen_slot = 0
        self._pen2_slots = [
            {
                'color': QColor('#e11d48'),
                'width': 3,
                'opacity': 100,
                'style_idx': 0,
            }
        ]
        self._active_pen2_slot = 0
        self._active_pen_group = 1
        self._highlight_slots = [
            {
                'color': QColor('#eab308'),
                'width': 15,
                'opacity': 50,
            }
        ]
        self._active_highlight_slot = 0
        self._build_ui()
        self._init_screen_recording_indicator()
        self._install_shortcuts()
        self._load_and_apply_settings()
        self._init_custom_tools()
        self._update_slide_label()
        self._sync_ui_for_mode(DrawMode.FREEHAND)
        self._on_stroke_style_change(self.combo_stroke.currentIndex())
        self._apply_plan_restrictions()
        self.init_python_figure_signals()
        QApplication.instance().installEventFilter(self)
        self.statusBar().hide()
        self._start_update_check()

    def is_plus(self) -> bool:
        return True

    def is_pro(self) -> bool:
        return True

    def _plan_limits(self) -> dict:
        return PLAN_LIMITS.get(PLAN_PRO, PLAN_LIMITS[PLAN_BASIC])

    def can_edit_custom_tool_code(self) -> bool:
        return True

    def _refresh_window_title(self) -> None:
        parts = [_app_title_name()]
        if self._user_plan:
            parts.append(f'- {self._user_plan}')
        if self._user_email:
            parts.append(f'● {self._user_email}')
        self.setWindowTitle(' '.join(parts))

    def _can_add_pen_slot(self) -> bool:
        limit = self._plan_limits()['extra_pens']
        if limit is None:
            return True
        return self._extra_pen_count() < limit

    def _extra_pen_count(self) -> int:
        pen_extra = max(0, len(self._pen_slots) - self.DEFAULT_PEN_SLOT_COUNT)
        pen2_extra = max(0, len(self._pen2_slots) - self.DEFAULT_PEN2_SLOT_COUNT)
        highlight_extra = max(0, len(self._highlight_slots) - self.DEFAULT_HIGHLIGHT_SLOT_COUNT)
        return pen_extra + pen2_extra + highlight_extra

    def _enforce_pen_slot_limit(self) -> None:
        limit = self._plan_limits()['extra_pens']
        if limit is None:
            return
        while self._extra_pen_count() > limit:
            if len(self._highlight_slots) > self.DEFAULT_HIGHLIGHT_SLOT_COUNT:
                self._highlight_slots.pop()
                btn = self._highlight_buttons.pop()
            elif len(self._pen2_slots) > self.DEFAULT_PEN2_SLOT_COUNT:
                self._pen2_slots.pop()
                btn = self._pen2_buttons.pop()
            elif len(self._pen_slots) > self.DEFAULT_PEN_SLOT_COUNT:
                self._pen_slots.pop()
                btn = self._pen_buttons.pop()
            else:
                break
            btn.setParent(None)
            btn.deleteLater()
        self._active_pen_slot = min(self._active_pen_slot, len(self._pen_slots) - 1)
        self._active_pen2_slot = min(self._active_pen2_slot, len(self._pen2_slots) - 1)
        self._active_highlight_slot = min(self._active_highlight_slot, len(self._highlight_slots) - 1)
        self.btn_pen = self._pen_buttons[0]
        self.btn_pen2 = self._pen_buttons[1] if len(self._pen_buttons) > 1 else self._pen_buttons[0]
        self.btn_pen3 = self._pen_buttons[2] if len(self._pen_buttons) > 2 else self._pen_buttons[0]
        self.btn_highlight = self._highlight_buttons[0]
        self.btn_highlight2 = (
            self._highlight_buttons[1] if len(self._highlight_buttons) > 1 else self._highlight_buttons[0]
        )
        self._refresh_toolbar_overflow()

    def _show_pen_limit_reached(self) -> None:
        limit = self._plan_limits()['extra_pens']
        if limit is None:
            return
        if limit == 0:
            message = t('Gói {plan} không được thêm bút mới.', plan=self._user_plan)
        else:
            message = t('Gói {plan} được thêm tối đa {limit} bút mới.', plan=self._user_plan, limit=limit)
        QMessageBox.information(self, t('Đã đạt hạn mức'), message)
        self.statusBar().showMessage(message, 4000)

    def _custom_tool_count(self, tool_type: str) -> int:
        if tool_type == 'line':
            return len(self._custom_line_actions)
        if tool_type == 'geometry':
            return len(self._custom_geometry_actions)
        if tool_type == 'polygon':
            return len(self._custom_polygon_actions)
        if tool_type == 'free':
            return len(self._custom_free_actions)
        return len(self._custom_curve_actions)

    def _can_add_custom_tool(self, tool_type: str) -> bool:
        limit = self._plan_limits()['ai_tools_per_group']
        if limit is None:
            return True
        return self._custom_tool_count(tool_type) < limit

    def _show_custom_tool_limit_reached(self, tool_type: str) -> None:
        limit = self._plan_limits()['ai_tools_per_group']
        if limit is None:
            return
        group_name = t(AI_TOOL_TYPE_LABELS.get(tool_type, AI_TOOL_TYPE_LABELS['curve']))
        message = t(
            'Gói {plan} chỉ cho phép tối đa {limit} công cụ AI trong nhóm {group}.',
            plan=self._user_plan,
            limit=limit,
            group=group_name,
        )
        QMessageBox.information(self, t('Đã đạt hạn mức'), message)
        self.statusBar().showMessage(message, 4000)

    def _apply_plan_restrictions(self) -> None:
        pen_limit = self._plan_limits()['extra_pens']
        if pen_limit is None:
            pen_tip = t('Thêm bút mới')
            highlight_tip = t('Thêm bút dạ quang mới')
        elif pen_limit == 0:
            pen_tip = t('Gói {plan} không được thêm bút mới', plan=self._user_plan)
            highlight_tip = t('Gói {plan} không được thêm bút dạ quang mới', plan=self._user_plan)
        else:
            used = self._extra_pen_count()
            pen_tip = t('Thêm bút mới ({used}/{limit})', used=used, limit=pen_limit)
            highlight_tip = t('Thêm bút dạ quang mới ({used}/{limit})', used=used, limit=pen_limit)
        for btn_attr, default_tip in (
            ('btn_add_pen', pen_tip),
            ('btn_add_pen2', pen_tip),
            ('btn_add_highlight', highlight_tip),
        ):
            btn = getattr(self, btn_attr, None)
            if btn is None:
                continue
            btn.setEnabled(True)
            btn.setToolTip(default_tip)
        ai_limit = self._plan_limits()['ai_tools_per_group']
        for tool_type, attr in (
            ('line', '_line_add_action'),
            ('geometry', '_geometry_add_action'),
            ('curve', '_curve_add_action'),
            ('polygon', '_polygon_add_action'),
            ('free', '_free_add_action'),
        ):
            action = getattr(self, attr, None)
            if action is None:
                continue
            group_name = t(AI_TOOL_TYPE_LABELS[tool_type])
            if ai_limit is None:
                action.setToolTip(t('Thêm công cụ AI vào nhóm {group}', group=group_name))
                continue
            action.setToolTip(
                t(
                    'Thêm công cụ AI vào nhóm {group} ({used}/{limit})',
                    group=group_name,
                    used=self._custom_tool_count(tool_type),
                    limit=ai_limit,
                )
            )
        tikz_btn = getattr(self, 'btn_tikz_ai', None)
        if tikz_btn:
            tikz_btn.setEnabled(True)
            if self.is_pro():
                tikz_btn.setToolTip(
                    t('TikZ AI từ vùng đã chọn\nGemini vẽ lại vùng quét bằng mã TikZ, cho sửa và biên dịch lại.')
                )
                return
            tikz_btn.setToolTip(t('TikZ AI chỉ dành cho tài khoản PRO.'))

    def _refresh_localized_texts(self) -> None:
        if hasattr(self, '_refresh_toolbar_texts'):
            self._refresh_toolbar_texts()
        self._apply_plan_restrictions()
        if hasattr(self, '_sync_ui_for_mode') and hasattr(self, 'canvas'):
            self._sync_ui_for_mode(self.canvas.mode)
        if hasattr(self, '_refresh_account_button'):
            self._refresh_account_button()

    def _show_plus_required(self) -> None:
        self._show_pen_limit_reached()

    def _install_shortcuts(self) -> None:
        def _bind(seq, slot):
            sc = QShortcut(QKeySequence(seq), self, activated=slot)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            return sc

        # Undo / Redo
        self._sc_undo = _bind('Ctrl+Z', self.canvas.undo)
        self._sc_redo = _bind('Ctrl+Y', self.canvas.redo)
        self._sc_redo2 = _bind('Ctrl+Shift+Z', self.canvas.redo)

        # File & Image
        self._sc_open = _bind('Ctrl+O', self._insert_file)
        self._sc_image = _bind('Ctrl+I', self._insert_image)
        self._sc_save = _bind('Ctrl+S', self._export_pdf)
        self._sc_export = _bind('Ctrl+E', self._export_selection)
        self._sc_ai = _bind('Ctrl+G', self._run_ai_questions)

        # Object selection, editing & clipboard
        self._sc_copy = _bind('Ctrl+C', self.canvas.copy_selection)
        self._sc_paste = _bind('Ctrl+V', self.canvas.paste_selection)
        self._sc_dup = _bind('Ctrl+D', self.canvas.duplicate_selection)
        self._sc_del = _bind('Delete', self.canvas.delete_active_selection)
        self._sc_bs = _bind('Backspace', self.canvas.delete_active_selection)
        self._sc_esc = _bind('Escape', self._on_escape_key)

        # Zoom
        self._sc_zoom_fit = _bind('Ctrl+0', self._fit_canvas_window)
        self._sc_zoom_in = _bind('Ctrl+=', self._zoom_in_canvas)
        self._sc_zoom_in2 = _bind('Ctrl++', self._zoom_in_canvas)
        self._sc_zoom_out = _bind('Ctrl+-', self._zoom_out_canvas)

        # Tool shortcuts
        from core.drawing_engine import DrawMode
        self._sc_tool_p = _bind('P', lambda: self._set_mode(DrawMode.FREEHAND))
        self._sc_tool_h = _bind('H', lambda: self._set_mode(DrawMode.HIGHLIGHT))
        self._sc_tool_e = _bind('E', lambda: self._set_mode(DrawMode.ERASER))
        self._sc_tool_s = _bind('S', lambda: self._set_mode(DrawMode.SELECT_RECT))
        self._sc_tool_t = _bind('T', lambda: self._set_mode(DrawMode.TYPE))

        # Page navigation
        self._sc_next_pg = _bind('PageDown', self._next_slide)
        self._sc_prev_pg = _bind('PageUp', self._prev_slide)

        # Modes / Features
        self._sc_curve_fill = _bind('Ctrl+F', self._toggle_curve_fill)
        self._sc_free_close = _bind('Ctrl+J', self._toggle_free_close)
        self._sc_border = _bind('Ctrl+B', self._toggle_border_visible)
        self._sc_mirror = _bind('Ctrl+M', self._open_mirror_window)
        self._sc_record = _bind('Ctrl+R', self._toggle_screen_recording)
        self._sc_fullscreen = _bind('F11', self._toggle_fullscreen)

    def _on_escape_key(self):
        if not self.canvas.escape_action():
            from core.drawing_engine import DrawMode
            self._set_mode(DrawMode.FREEHAND)

    def _next_slide(self) -> None:
        self.canvas.go_next()
        self._update_slide_label()

    def _prev_slide(self) -> None:
        self.canvas.go_prev()
        self._update_slide_label()

    def _first_slide(self) -> None:
        self.canvas.go_first()
        self._update_slide_label()

    def _last_slide(self) -> None:
        self.canvas.go_last()
        self._update_slide_label()

    def _update_slide_label(self) -> None:
        if getattr(self, '_toolbar_vertical', False):
            self.lbl_slide.setText(f'{self.canvas.current_slide_number}/{self.canvas.slide_count}')
            return
        self.lbl_slide.setText(f'{self.canvas.current_slide_number} / {self.canvas.slide_count}')

    def _delete_page(self) -> None:
        ans = QMessageBox.question(
            self,
            t('Xóa trang'),
            t('Bạn có chắc chắn muốn xóa trang hiện tại không?'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.canvas.delete_current_slide()
            self._update_slide_label()

    def canvas_undo(self) -> None:
        self.canvas.undo()
        self._update_slide_label()

    def canvas_redo(self) -> None:
        self.canvas.redo()
        self._update_slide_label()

    def _load_app_icon(self):
        return load_app_icon()

    def _start_update_check(self) -> None:
        from PyQt6.QtCore import QThread
        from core.updater import UpdateChecker

        self._update_check_thread = QThread(self)
        self._update_checker = UpdateChecker()
        self._update_checker.moveToThread(self._update_check_thread)
        self._update_check_thread.started.connect(self._update_checker.run)
        self._update_checker.update_available.connect(self._set_update_available)
        self._update_checker.check_done.connect(self._update_check_thread.quit)
        self._update_check_thread.start()

    def closeEvent(self, event) -> None:
        recorder = getattr(self, '_screen_recorder', None)
        if recorder is not None and recorder.is_recording:
            recorder.stop()
        self._set_screen_recording_indicator_visible(False)
        thread = getattr(self, '_update_check_thread', None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(2000)
        timer = getattr(self, '_blink_timer', None)
        if timer is not None:
            timer.stop()
        settings_save(
            self.canvas,
            self.combo_stroke.currentIndex(),
            pen_slots=self._pen_slots,
            pen2_slots=self._pen2_slots,
            highlight_slots=self._highlight_slots,
            active_pen=self._active_pen_slot,
            active_pen2=self._active_pen2_slot,
            active_pen_group=self._active_pen_group,
            active_hl=self._active_highlight_slot,
            toolbar_height=getattr(self, '_toolbar_height', self.DEFAULT_TOOLBAR_HEIGHT),
            tool_group_height=getattr(self, '_tool_group_height', self.DEFAULT_TOOL_GROUP_HEIGHT),
            toolbar_vertical=getattr(self, '_toolbar_vertical', False),
        )
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_toolbar_overflow()
        self._queue_toolbar_overflow_refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._queue_toolbar_overflow_refresh()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized()
            return
        self.showFullScreen()

    def _toggle_image_transform_cursor_mode(self) -> None:
        enabled = self.canvas.toggle_image_transform_cursor_mode()
        if enabled:
            message = t('Biến hình ảnh theo con trỏ: bật')
        else:
            message = t('Biến hình ảnh theo con trỏ: tắt')
        self.statusBar().showMessage(message, 2500)
        QToolTip.showText(QCursor.pos(), message, self.canvas)

    def _open_mirror_window(self) -> None:
        mirror = self._mirror_window
        if mirror is None:
            mirror = MirrorWindow(self.canvas, self)
            mirror.destroyed.connect(lambda: setattr(self, '_mirror_window', None))
            self._mirror_window = mirror
        mirror.show()
        mirror.raise_()
        mirror.activateWindow()

    def _init_screen_recording_indicator(self) -> None:
        toolbar = getattr(self, '_toolbar', None)
        parent = toolbar if toolbar is not None else self
        self._recording_indicator = QLabel(parent)
        self._recording_indicator.setObjectName('RecordingIndicator')
        self._recording_indicator.setTextFormat(Qt.TextFormat.RichText)
        self._recording_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._recording_indicator.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._recording_indicator.setStyleSheet(
            'QLabel#RecordingIndicator {background-color: rgba(15, 23, 42, 224);border: 2px solid #ef4444;border-radius: 10px;padding: 3px 8px;font-size: 12px;font-weight: 800;}'
        )
        self._recording_indicator.hide()
        self._recording_indicator_timer = QTimer(self)
        self._recording_indicator_timer.setInterval(500)
        self._recording_indicator_timer.timeout.connect(self._refresh_screen_recording_indicator)
        self._insert_screen_recording_indicator_into_toolbar()

    def _insert_screen_recording_indicator_into_toolbar(self) -> None:
        row = getattr(self, '_toolbar_row', None)
        indicator = getattr(self, '_recording_indicator', None)
        if row is None or indicator is None:
            return
        page_group = getattr(self, 'lbl_slide', None)
        page_group = page_group.parentWidget() if page_group else None
        index = row.indexOf(page_group) if page_group else -1
        if index < 0:
            index = max(0, row.count() - 4)
        row.insertWidget(index, indicator, 0, Qt.AlignmentFlag.AlignVCenter)

    def _set_screen_recording_indicator_visible(self, visible: bool) -> None:
        indicator = getattr(self, '_recording_indicator', None)
        timer = getattr(self, '_recording_indicator_timer', None)
        if indicator is None or timer is None:
            return
        if visible:
            self._refresh_screen_recording_indicator()
            indicator.show()
            indicator.raise_()
            if not timer.isActive():
                timer.start()
            return
        if timer.isActive():
            timer.stop()
        indicator.hide()
        self._refresh_window_title()

    def _refresh_screen_recording_indicator(self) -> None:
        recorder = getattr(self, '_screen_recorder', None)
        if recorder is None or not recorder.is_recording:
            self._set_screen_recording_indicator_visible(False)
            return
        elapsed = self._format_recording_elapsed(recorder.elapsed_seconds)
        self._recording_indicator.setText(
            f"<span style='color:#ef4444;'>● REC</span><span style='color:#f8fafc;'> {elapsed}</span>"
        )
        self._recording_indicator.adjustSize()
        self._recording_indicator.raise_()

    def _screen_recording_excluded_rects(self) -> tuple[QRect, ...]:
        indicator = getattr(self, '_recording_indicator', None)
        if indicator is None or not indicator.isVisible():
            return ()
        top_left = indicator.mapToGlobal(indicator.rect().topLeft())
        return (QRect(top_left, indicator.size()).adjusted(-3, -3, 3, 3),)

    @staticmethod
    def _format_recording_elapsed(seconds: float) -> str:
        total = max(0, int(seconds))
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        if hours:
            return f'{hours:02d}:{minutes:02d}:{secs:02d}'
        return f'{minutes:02d}:{secs:02d}'

    def _is_screen_record_shortcut_event(self, event) -> bool:
        if event.type() != QEvent.Type.KeyPress or event.isAutoRepeat():
            return False
        if event.key() != Qt.Key.Key_R:
            return False
        mods = event.modifiers()
        ctrl = Qt.KeyboardModifier.ControlModifier
        meta = Qt.KeyboardModifier.MetaModifier
        keypad = Qt.KeyboardModifier.KeypadModifier
        primary_mods = ctrl
        if QApplication.platformName().lower() == 'cocoa':
            primary_mods = primary_mods | meta
        if not bool(mods & primary_mods):
            return False
        return not bool(mods & ~(primary_mods | keypad))

    def _toggle_screen_recording(self) -> None:
        recorder = getattr(self, '_screen_recorder', None)
        if recorder is None:
            return
        if recorder.is_recording:
            result = recorder.stop()
            self._set_screen_recording_indicator_visible(False)
            self._refresh_window_title()
            if not result:
                return
            if result.error:
                QMessageBox.critical(self, t('Lỗi'), t('Không thể lưu bản ghi: {error}', error=result.error))
                return
            copied = self._copy_recording_to_clipboard(result.path)
            if copied:
                message = t('Đã lưu video và đưa vào clipboard: {path}', path=str(result.path))
            else:
                message = t('Đã lưu bản ghi: {path}', path=str(result.path))
            self.statusBar().showMessage(message, 6000)
            QToolTip.showText(QCursor.pos(), message, self.canvas)
            return
        try:
            path = recorder.start()
            self._refresh_window_title()
            self._set_screen_recording_indicator_visible(True)
            message = t('Đang ghi cửa sổ eDraw... Ctrl+R để dừng.')
            self.statusBar().showMessage(f'{message} {path}', 5000)
            QToolTip.showText(QCursor.pos(), message, self.canvas)
        except Exception as exc:
            QMessageBox.critical(self, t('Lỗi'), t('Không thể bắt đầu ghi hình: {error}', error=exc))

    def _copy_recording_to_clipboard(self, path: Path) -> bool:
        if not path.exists():
            return False
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        mime.setText(str(path))
        QApplication.clipboard().setMimeData(mime)
        return True

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self.showMaximized()
            elif self.canvas.has_selection():
                self.canvas.clear_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if self._is_screen_record_shortcut_event(event):
            self._toggle_screen_recording()
            event.accept()
            return True
        toolbar_scroller = getattr(self, '_toolbar_left_scroller', None)
        if toolbar_scroller is not None and obj is toolbar_scroller.viewport() and event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().x() or event.angleDelta().y()
            if delta:
                if getattr(self, '_toolbar_vertical', False):
                    bar = toolbar_scroller.verticalScrollBar()
                else:
                    bar = toolbar_scroller.horizontalScrollBar()
                bar.setValue(bar.value() - delta)
                event.accept()
                return True
        is_curve_menu = obj is getattr(self, '_curve_menu', None)
        is_line_menu = obj is getattr(self, '_line_menu', None)
        is_geometry_menu = obj is getattr(self, '_geometry_menu', None)
        is_polygon_menu = obj is getattr(self, '_polygon_menu', None)
        is_free_menu = obj is getattr(self, '_free_menu', None)
        if is_curve_menu or is_line_menu or is_geometry_menu or is_polygon_menu or is_free_menu:
            menu_pos = None
            global_pos = None
            is_macos = QApplication.platformName().lower() == 'cocoa'
            context_click_mods = Qt.KeyboardModifier.ControlModifier if is_macos else Qt.KeyboardModifier.NoModifier
            if event.type() == QEvent.Type.ContextMenu:
                menu_pos = event.pos()
                global_pos = event.globalPos()
            elif event.type() == QEvent.Type.MouseButtonPress:
                is_right_click = event.button() == Qt.MouseButton.RightButton
                is_macos_context_click = is_macos and event.button() == Qt.MouseButton.LeftButton and bool(event.modifiers() & context_click_mods)
                if is_right_click or is_macos_context_click:
                    menu_pos = event.pos()
                    global_pos = event.globalPosition().toPoint()
            if menu_pos is not None and global_pos is not None:
                menu = obj
                action = menu.actionAt(menu_pos)
                if action is None:
                    return False
                ai_name = None
                if is_curve_menu:
                    ai_name = next((n for n, a in self._custom_curve_actions.items() if a is action), None)
                elif is_line_menu:
                    ai_name = next((n for n, a in self._custom_line_actions.items() if a is action), None)
                elif is_geometry_menu:
                    ai_name = next((n for n, a in self._custom_geometry_actions.items() if a is action), None)
                elif is_polygon_menu:
                    ai_name = next((n for n, a in self._custom_polygon_actions.items() if a is action), None)
                elif is_free_menu:
                    ai_name = next((n for n, a in self._custom_free_actions.items() if a is action), None)
                if ai_name is not None:
                    ctx_menu = QMenu(self)
                    ctx_menu.setStyleSheet(MENU_STYLE)
                    act_rename = ctx_menu.addAction('✏  ' + t('Đổi tên…'))
                    act_edit = ctx_menu.addAction('👨‍💻  ' + t('Xem / Sửa code…'))
                    act_delete = ctx_menu.addAction('🗑  ' + t('Xóa công cụ này'))
                    chosen = ctx_menu.exec(global_pos)
                    if chosen is act_rename:
                        self._rename_custom_curve_tool(ai_name)
                    elif chosen is act_edit:
                        self._edit_custom_tool_code(ai_name)
                        return True
                    elif chosen is act_delete:
                        self._delete_custom_curve_tool(ai_name)
                        return True
        if event.type() == QEvent.Type.KeyPress and QApplication.activeWindow() is self:
            mods = event.modifiers()
            key = event.key()
            ctrl = Qt.KeyboardModifier.ControlModifier
            meta = Qt.KeyboardModifier.MetaModifier
            keypad = Qt.KeyboardModifier.KeypadModifier
            primary_mods = ctrl
            if QApplication.platformName().lower() == 'cocoa':
                primary_mods = primary_mods | meta
            primary_active = bool(mods & primary_mods)
            none_only = not bool(mods & ~keypad)
            shift = Qt.KeyboardModifier.ShiftModifier
            shift_active = bool(mods & shift)
            focused = QApplication.focusWidget()
            input_focused = isinstance(focused, (QAbstractSpinBox, QLineEdit, QPlainTextEdit, QTextEdit))
            primary_with_shift = bool(mods & primary_mods) and not bool(mods & ~(primary_mods | shift | keypad))
            if primary_with_shift:
                if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
                    adjust = getattr(self.canvas, 'adjust_type_preview_font_size', None)
                    if callable(adjust):
                        delta = -1 if key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore) else 1
                        if adjust(delta):
                            if getattr(self.canvas, '_type_use_split_layout', lambda: False)():
                                size = getattr(self.canvas, 'texstudio_preview_font_size', 16)
                            else:
                                size = getattr(self.canvas.engine, 'markdown_font_size', 16)
                            self.statusBar().showMessage(f'{t("Cỡ chữ render")}: {int(size)}', 1200)
                            return True
            if event.matches(QKeySequence.StandardKey.Paste):
                if self._paste_image_from_clipboard():
                    return True
            if not input_focused:
                if event.matches(QKeySequence.StandardKey.Undo):
                    self.canvas_undo()
                    return True
                if event.matches(QKeySequence.StandardKey.Redo):
                    self.canvas_redo()
                    return True
            shift_only = bool(shift_active and not (mods & ~(shift | keypad)))
            if shift_only and not input_focused:
                if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                    if hasattr(self.canvas, 'flip_selection'):
                        self.canvas.flip_selection(horizontal=True)
                        return True
                elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                    if hasattr(self.canvas, 'flip_selection'):
                        self.canvas.flip_selection(horizontal=False)
                        return True
            primary_only = bool(primary_active and not (mods & ~(primary_mods | keypad)))
            if primary_only:
                if key == Qt.Key.Key_E:
                    self._export_selection()
                    return True
                if key == Qt.Key.Key_T:
                    self._toggle_image_transform_cursor_mode()
                    return True
                if not input_focused:
                    if key == Qt.Key.Key_Right:
                        self._next_slide()
                        return True
                    if key == Qt.Key.Key_Left:
                        self._prev_slide()
                        return True
                    if key == Qt.Key.Key_Up:
                        self.canvas._scroll_y = max(0.0, self.canvas._scroll_y - 150 / self.canvas._zoom)
                        self.canvas.update()
                        return True
                    if key == Qt.Key.Key_Down:
                        self.canvas._scroll_y = max(0.0, self.canvas._scroll_y + 150 / self.canvas._zoom)
                        self.canvas.update()
                        return True
                    if key == Qt.Key.Key_PageDown:
                        self._next_slide()
                        return True
                    if key == Qt.Key.Key_PageUp:
                        self._prev_slide()
                        return True
                    if key == Qt.Key.Key_Home:
                        self._first_slide()
                        return True
                    if key == Qt.Key.Key_End:
                        self._last_slide()
                        return True
                    if key == Qt.Key.Key_Z:
                        self.canvas_undo()
                        return True
                    if key == Qt.Key.Key_Y:
                        self.canvas_redo()
                        return True
                    if key == Qt.Key.Key_A:
                        self.canvas.select_all()
                        return True
                    if key == Qt.Key.Key_M:
                        self._open_mirror_window()
                        return True
                    has_active_selection = (
                        self.canvas.has_active_selection()
                        if hasattr(self.canvas, 'has_active_selection')
                        else self.canvas.has_selection()
                    )
                    if key == Qt.Key.Key_C and has_active_selection:
                        self.canvas.copy_selection()
                        return True
                    if key == Qt.Key.Key_X and has_active_selection:
                        self.canvas.cut_selection()
                        return True
            if none_only and not input_focused:
                pan_step = getattr(self.canvas, '_scroll_step', 80)
                if key == Qt.Key.Key_Left:
                    self.canvas.pan_by(-pan_step, 0)
                    return True
                if key == Qt.Key.Key_Right:
                    self.canvas.pan_by(pan_step, 0)
                    return True
                if key == Qt.Key.Key_Up:
                    self.canvas.pan_by(0, -pan_step)
                    return True
                if key == Qt.Key.Key_Down:
                    self.canvas.pan_by(0, pan_step)
                    return True
            if none_only and key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                if not input_focused:
                    if hasattr(self.canvas, 'delete_active_selection'):
                        self.canvas.delete_active_selection()
                    if self.canvas.has_selection():
                        self.canvas.delete_selection()
                    return True
        return super().eventFilter(obj, event)
