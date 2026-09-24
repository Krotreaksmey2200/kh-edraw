"""
ui/toolbar_mixin.py
Builder for the top toolbar of MainWindow.
"""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QColor, QIcon
from PyQt6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidgetAction,
    QWidget,
)

from core.drawing_engine import DrawMode
from core.i18n import t
from ui.constants import CURVE_MODES, FILL_STYLES, LINE_MODES, MENU_STYLE, POLYGON_MODES, STROKE_STYLES
from widgets.canvas import Canvas


class ToolbarMixin:
    """Full toolbar construction and tool-button logic for MainWindow."""

    DEFAULT_TOOLBAR_HEIGHT = 44
    MIN_TOOLBAR_HEIGHT = 36
    VERTICAL_MIN_TOOLBAR_HEIGHT = 20
    MAX_TOOLBAR_HEIGHT = 68
    DEFAULT_TOOL_GROUP_HEIGHT = 36
    MIN_TOOL_GROUP_HEIGHT = 28
    VERTICAL_MIN_TOOL_GROUP_HEIGHT = 20
    MAX_TOOL_GROUP_HEIGHT = 56
    _MAX_WIDGET_SIZE = 16777215
    _DYNAMIC_TOOL_NORMAL_LIMIT = 5
    _DYNAMIC_TOOL_COMPACT_LIMIT = 8
    _NEW_PEN_COLORS = [
        "#7c3aed", "#0891b2", "#059669", "#d97706", "#db2777",
        "#ea580c", "#0284c7", "#65a30d", "#9333ea", "#0d9488",
    ]
    _NEW_HIGHLIGHT_COLORS = [
        "#22c55e", "#3b82f6", "#f43f5e", "#a855f7", "#06b6d4",
        "#f97316", "#84cc16", "#ec4899", "#14b8a6", "#eab308",
    ]

    # ── Main UI builder ──────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.canvas = Canvas()
        if hasattr(self.canvas, "slide_changed"):
            self.canvas.slide_changed.connect(lambda c, t: self._update_slide_label() if hasattr(self, "_update_slide_label") else None)
        root_layout.addWidget(self._build_toolbar())
        root_layout.addWidget(self.canvas, stretch=1)

    # ── Toolbar frame ────────────────────────────────────────────────────

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopToolbar")
        self._toolbar = bar
        self._toolbar_height = getattr(self, "_toolbar_height", self.DEFAULT_TOOLBAR_HEIGHT)
        self._tool_group_height = getattr(self, "_tool_group_height", self.DEFAULT_TOOL_GROUP_HEIGHT)
        self._toolbar_vertical = bool(getattr(self, "_toolbar_vertical", False))
        self._tool_group_frames = []
        self._tool_group_inner_layouts = []

        bar.setStyleSheet(self._toolbar_css())
        row = QBoxLayout(QBoxLayout.Direction.LeftToRight, bar)
        row.setContentsMargins(8, 3, 8, 3)
        row.setSpacing(6)
        self._toolbar_row = row

        # Left scroller with all tool groups
        left_scroller = QScrollArea()
        left_scroller.setObjectName("ToolbarLeftScroller")
        left_scroller.setFrameShape(QFrame.Shape.NoFrame)
        left_scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroller.setWidgetResizable(False)
        left_scroller.setMinimumWidth(0)
        left_scroller.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        left_scroller.setToolTip(t("Cuộn ngang để xem thêm công cụ khi toolbar quá dài"))
        left_scroller.viewport().setStyleSheet("background:#ffffff;")
        left_scroller.viewport().installEventFilter(self)
        left_content = QWidget()
        left_content.setObjectName("ToolbarLeftContent")
        left_content.setStyleSheet("background:#ffffff;")
        left_row = QBoxLayout(QBoxLayout.Direction.LeftToRight, left_content)
        left_row.setContentsMargins(0, 0, 0, 0)
        left_row.setSpacing(6)
        self._toolbar_left_scroller = left_scroller
        self._toolbar_left_content = left_content
        self._toolbar_left_layout = left_row

        left_row.addWidget(self._tool_group(self._build_primary_tools()))
        left_row.addWidget(self._tool_group(self._build_secondary_pen_tools()))
        left_row.addWidget(self._tool_group(self._build_highlight_tools()))
        left_row.addWidget(self._tool_group(self._build_erase_tools()))
        left_row.addWidget(self._tool_group(self._build_selection_tools()))
        left_row.addWidget(self._tool_group(self._build_stroke_tools()))
        left_row.addWidget(self._tool_group(self._build_line_tools()))
        left_row.addWidget(self._tool_group(self._build_curve_tools()))
        left_row.addWidget(self._tool_group(self._build_polygon_tools()))
        left_row.addWidget(self._tool_group(self._build_geometry_tools()))
        left_row.addWidget(self._tool_group(self._build_free_tools()))
        left_row.addWidget(self._tool_group(self._build_type_tools()))
        left_scroller.setWidget(left_content)
        row.addWidget(left_scroller, 1)

        # Right-side groups
        page_group = self._tool_group(self._build_page_tools())
        delete_page_group = self._tool_group(self._build_delete_page_tools())
        view_group = self._tool_group(self._build_view_tools())
        ai_group = self._tool_group(self._build_ai_tools())
        file_group = self._tool_group(self._build_file_tools())
        account_button = self._build_account_button()
        self._toolbar_right_widgets = [
            page_group, delete_page_group, view_group, ai_group, file_group, account_button,
        ]
        self._toolbar_right_extra_spacing = 6
        row.addWidget(page_group)
        row.addWidget(delete_page_group)
        row.addWidget(view_group)
        row.addWidget(ai_group)
        row.addWidget(file_group)
        row.addSpacing(self._toolbar_right_extra_spacing)
        row.addWidget(account_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self._set_toolbar_height(self._toolbar_height)
        self._set_tool_group_height(self._tool_group_height)
        self._set_toolbar_vertical(self._toolbar_vertical)
        self._refresh_toolbar_overflow()
        self._queue_toolbar_overflow_refresh()
        return bar

    def _toolbar_css(self) -> str:
        return (
            "#TopToolbar { background:#ffffff; border-bottom:1px solid #e2e8f0; }"
            "#TopToolbar[toolbarPlacement='vertical'] { border-bottom:none; border-right:1px solid #e2e8f0; }"
            "QFrame[toolGroup='true'] { background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:1px 2px; }"
            "QToolButton { min-width:26px; min-height:26px; max-width:32px; max-height:32px; padding:2px; border-radius:6px; border:1px solid transparent; background:transparent; color:#334155; }"
            "QToolButton:hover { background:#e2e8f0; border:1px solid #cbd5e1; }"
            "QToolButton:checked { background:#e0e7ff; border:1.5px solid #4f46e5; }"
            "QToolButton:pressed { background:#cbd5e1; }"
            "QToolButton::menu-indicator { image:none; width:0px; }"
        )


    # ── Overflow management ──────────────────────────────────────────────

    def _queue_toolbar_overflow_refresh(self):
        if not getattr(self, "_toolbar_overflow_refresh_pending", False):
            self._toolbar_overflow_refresh_pending = True
            QTimer.singleShot(0, self._run_queued_toolbar_overflow_refresh)
        if self.isVisible():
            if not getattr(self, "_toolbar_overflow_refresh_delayed_pending", False):
                self._toolbar_overflow_refresh_delayed_pending = True
                QTimer.singleShot(120, self._run_delayed_toolbar_overflow_refresh)

    def _run_queued_toolbar_overflow_refresh(self):
        self._toolbar_overflow_refresh_pending = False
        self._refresh_toolbar_overflow()

    def _run_delayed_toolbar_overflow_refresh(self):
        self._toolbar_overflow_refresh_delayed_pending = False
        self._refresh_toolbar_overflow()

    def _refresh_toolbar_overflow(self):
        """Coalesce pen buttons and update scroll region so right-side stays visible."""
        total_dynamic = (
            len(getattr(self, "_pen_buttons", []))
            + len(getattr(self, "_pen2_buttons", []))
            + len(getattr(self, "_highlight_buttons", []))
        )
        if total_dynamic <= self._DYNAMIC_TOOL_NORMAL_LIMIT:
            icon_size, state, spacing = 20, "normal", 4
        elif total_dynamic <= self._DYNAMIC_TOOL_COMPACT_LIMIT:
            icon_size, state, spacing = 18, "compact", 3
        else:
            icon_size, state, spacing = 16, "tiny", 2

        if getattr(self, "_tool_group_height", self.DEFAULT_TOOL_GROUP_HEIGHT) <= 28:
            icon_size = min(icon_size, 14)
            spacing = min(spacing, 1)

        for btn in getattr(self, "_pen_buttons", []):
            self._apply_dynamic_button_density(btn, state, icon_size)
        for btn in getattr(self, "_pen2_buttons", []):
            self._apply_dynamic_button_density(btn, state, icon_size)
        for btn in getattr(self, "_highlight_buttons", []):
            self._apply_dynamic_button_density(btn, state, icon_size)

        content = getattr(self, "_toolbar_left_content", None)
        scroller = getattr(self, "_toolbar_left_scroller", None)
        if not content or not scroller:
            return

        vertical = bool(getattr(self, "_toolbar_vertical", False))
        left_layout = content.layout()
        if left_layout:
            left_layout.invalidate()
            left_layout.activate()
            hint = left_layout.sizeHint()
        else:
            hint = content.sizeHint()

        if vertical:
            self._set_fixed_size_if_needed(content, self._vertical_tool_group_width(), hint.height())
            self._set_fixed_width_if_needed(scroller, self._vertical_tool_group_width() + 2)
            return

        self._set_fixed_size_if_needed(content, hint.width(), hint.height())
        self._set_fixed_height_if_needed(
            scroller,
            max(20, min(hint.height(), getattr(self, "_tool_group_height", self.DEFAULT_TOOL_GROUP_HEIGHT)))
        )

    def _apply_dynamic_button_density(self, btn: QToolButton, state: str, icon_size: int):
        """Apply dynamic pen density only when it really changed."""
        needs_repolish = btn.property("dynamicPen") != state
        if needs_repolish:
            btn.setProperty("dynamicPen", state)
        size = QSize(icon_size, icon_size)
        if btn.iconSize() != size:
            btn.setIconSize(size)
        if needs_repolish:
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    @staticmethod
    def _set_fixed_size_if_needed(widget, width, height):
        width = max(0, int(width))
        height = max(0, int(height))
        if widget.width() != width or widget.height() != height:
            widget.setFixedSize(width, height)

    @staticmethod
    def _set_fixed_width_if_needed(widget, width):
        width = max(0, int(width))
        if widget.minimumWidth() != width or widget.maximumWidth() != width:
            widget.setFixedWidth(width)

    @staticmethod
    def _set_fixed_height_if_needed(widget, height):
        height = max(0, int(height))
        if widget.minimumHeight() != height or widget.maximumHeight() != height:
            widget.setFixedHeight(height)

    @staticmethod
    def _set_visible_if_needed(widget, visible):
        current_explicit_visible = not widget.isHidden()
        if current_explicit_visible != visible:
            widget.setVisible(visible)

    # ── Toolbar sizing ───────────────────────────────────────────────────

    def _set_toolbar_height(self, height):
        min_height = self.VERTICAL_MIN_TOOLBAR_HEIGHT if getattr(self, "_toolbar_vertical", False) else self.MIN_TOOLBAR_HEIGHT
        height = max(min_height, min(self.MAX_TOOLBAR_HEIGHT, int(height)))
        self._toolbar_height = height
        toolbar = getattr(self, "_toolbar", None)
        if toolbar:
            self._set_fixed_height_if_needed(toolbar, height)

    def _set_tool_group_height(self, height):
        min_height = self.VERTICAL_MIN_TOOL_GROUP_HEIGHT if getattr(self, "_toolbar_vertical", False) else self.MIN_TOOL_GROUP_HEIGHT
        height = max(min_height, min(self.MAX_TOOL_GROUP_HEIGHT, int(height)))
        self._tool_group_height = height
        self._apply_tool_group_sizing()

    def _set_toolbar_vertical(self, vertical):
        vertical = bool(vertical)
        self._toolbar_vertical = vertical
        root_layout = getattr(self, "_root_layout", None)
        if root_layout:
            toolbar = getattr(self, "_toolbar", None)
            if toolbar:
                toolbar.setProperty("toolbarPlacement", "vertical" if vertical else "horizontal")
                self._apply_toolbar_container_size()

    def _apply_toolbar_container_size(self):
        toolbar = getattr(self, "_toolbar", None)
        if toolbar:
            if getattr(self, "_toolbar_vertical", False):
                toolbar.setFixedWidth(self._vertical_toolbar_width())
                toolbar.setFixedHeight(self._MAX_WIDGET_SIZE)
            else:
                toolbar.setFixedHeight(self._toolbar_height)
                toolbar.setFixedWidth(self._MAX_WIDGET_SIZE)

    def _vertical_toolbar_width(self):
        configured_height = int(getattr(self, "_toolbar_height", self.DEFAULT_TOOLBAR_HEIGHT))
        return max(40, min(84, configured_height + 20))

    def _vertical_tool_group_width(self):
        return max(30, self._vertical_toolbar_width() - 10)

    def _vertical_control_width(self):
        return max(26, self._vertical_tool_group_width() - 8)

    def _vertical_family_button_width(self):
        return self._vertical_control_width()

    def _apply_tool_group_sizing(self):
        vertical = bool(getattr(self, "_toolbar_vertical", False))
        for frame in getattr(self, "_tool_group_frames", []):
            if vertical:
                self._set_fixed_width_if_needed(frame, self._vertical_tool_group_width())
            else:
                frame.setFixedWidth(self._MAX_WIDGET_SIZE)
                frame.setFixedHeight(self._tool_group_height)
        self._apply_vertical_control_compaction()
        self._apply_tool_group_density()

    def _apply_vertical_control_compaction(self):
        vertical = bool(getattr(self, "_toolbar_vertical", False))
        control_w = self._vertical_control_width()
        family_w = self._vertical_family_button_width()
        if hasattr(self, "spin_size"):
            self.spin_size.setPrefix("" if vertical else "\u2195 ")
            self.spin_size.setFixedWidth(max(control_w, 70) if vertical else 70)
        if hasattr(self, "spin_opacity"):
            self.spin_opacity.setSuffix("" if vertical else " %")
            self.spin_opacity.setFixedWidth(max(control_w, 72) if vertical else 72)
        if hasattr(self, "combo_stroke"):
            self.combo_stroke.setIconSize(QSize(24, 10) if vertical else QSize(40, 12))
            self.combo_stroke.setFixedWidth(max(control_w, 168) if vertical else 168)
        if hasattr(self, "combo_fill"):
            self.combo_fill.setIconSize(QSize(30, 14) if vertical else QSize(40, 18))
            self.combo_fill.setFixedWidth(max(control_w, 168) if vertical else 168)
        if hasattr(self, "spin_fill_opacity"):
            self.spin_fill_opacity.setSuffix("" if vertical else " %")
            self.spin_fill_opacity.setFixedWidth(max(control_w, 72) if vertical else 72)

    def _apply_tool_group_density(self):
        toolbar = getattr(self, "_toolbar", None)
        if toolbar and getattr(self, "_toolbar_vertical", False):
            for frame in getattr(self, "_tool_group_frames", []):
                self._set_fixed_width_if_needed(frame, self._vertical_tool_group_width())

    def _resize_account_for_toolbar(self):
        btn = getattr(self, "btn_account", None)
        if btn:
            size = getattr(self, "AVATAR_SIZE", 28)
            btn.setFixedSize(size + 4, size + 4)

    def _align_tool_group_layout(self, layout, vertical):
        alignment = Qt.AlignmentFlag.AlignHCenter if vertical else Qt.AlignmentFlag.AlignVCenter
        if hasattr(layout, "setAlignment"):
            layout.setAlignment(alignment)

    def _sync_compact_toolbar_controls(self):
        """Sync compact toolbar slider/spinbox values."""
        if hasattr(self, 'spin_size') and hasattr(self.canvas, 'engine'):
            self.spin_size.setValue(self.canvas.engine.get_active_width())
        if hasattr(self, 'spin_opacity') and hasattr(self.canvas, 'engine'):
            self.spin_opacity.setValue(self.canvas.engine.get_active_opacity())

    def _open_vertical_slider(self, spinbox, title, suffix=""):
        button = getattr(self, 'btn_size_slider', None)
        if spinbox is getattr(self, 'spin_opacity', None):
            button = getattr(self, 'btn_opacity_slider', None)
        if not button:
            return None
        menu = QMenu(self)
        menu.setStyleSheet(
            MENU_STYLE
            + 'QWidget { background:#1e293b; color:#f8fafc; }'
            + 'QSlider::groove:vertical { background:#334155; width:6px; border-radius:3px; }'
            + 'QSlider::handle:vertical { background:#818cf8; height:14px; margin:0 -5px; border-radius:7px; }'
            + 'QSlider::sub-page:vertical { background:#6366f1; border-radius:3px; }'
        )
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        value_label = QLabel(f'{spinbox.value()}{suffix}')
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setStyleSheet('font-weight:700; color:#f8fafc;')
        layout.addWidget(value_label)
        slider = QSlider(Qt.Orientation.Vertical)
        slider.setRange(spinbox.minimum(), spinbox.maximum())
        slider.setValue(spinbox.value())
        slider.setFixedHeight(150)
        slider.setTickPosition(QSlider.TickPosition.NoTicks)
        layout.addWidget(slider, 0, Qt.AlignmentFlag.AlignHCenter)
        title_label = QLabel(t(title))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setStyleSheet('font-size:10px; color:#cbd5e1;')
        layout.addWidget(title_label)

        def apply_value(value=None):
            value_label.setText(f'{value}{suffix}')
            spinbox.setValue(value)
            self._sync_compact_toolbar_controls()

        slider.valueChanged.connect(apply_value)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        menu.exec(button.mapToGlobal(button.rect().topRight()))

    def _set_stroke_style_index(self, idx):
        if not hasattr(self, "combo_stroke"):
            return
        if not (0 <= idx < self.combo_stroke.count()):
            return
        if self.combo_stroke.currentIndex() == idx:
            self._on_stroke_style_change(idx)
        else:
            self.combo_stroke.setCurrentIndex(idx)
        self._sync_compact_toolbar_controls()

    # ── Tool group / button helpers ──────────────────────────────────────

    def _tool_group(self, inner, title=None) -> QFrame:
        frame = QFrame()
        frame.setProperty("toolGroup", True)
        if hasattr(self, "_tool_group_frames"):
            self._tool_group_frames.append(frame)
        if hasattr(self, "_tool_group_inner_layouts"):
            self._tool_group_inner_layouts.append(inner)
        if title:
            outer = QVBoxLayout(frame)
            outer.setContentsMargins(5, 2, 5, 2)
            outer.setSpacing(1)
            lbl = QLabel(title)
            lbl.setStyleSheet(
                "color:#64748b; font-size:9px; font-weight:700; "
                "letter-spacing:0.5px; padding:0px; background:transparent; border:none;"
            )
            outer.addWidget(lbl)
            outer.addLayout(inner)
            return frame
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(3, 2, 3, 2)
        layout.setSpacing(1)
        layout.addLayout(inner)
        return frame

    def _tool_button(self, icon, tooltip, *, checkable=False, popup_mode=None) -> QToolButton:
        btn = QToolButton()
        btn.setIcon(icon)
        btn.setToolTip(tooltip)
        btn.setCheckable(checkable)
        btn.setIconSize(QSize(18, 18))
        btn.setAutoRaise(False)
        btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if popup_mode is not None:
            btn.setPopupMode(popup_mode)
        return btn

    # ── Text refresh ─────────────────────────────────────────────────────

    def _refresh_toolbar_texts(self):
        """Re-translate all toolbar tooltips/labels after language change."""
        if hasattr(self, 'btn_pen_more'):
            self.btn_pen_more.setToolTip(t("Chọn bút (nhóm 1)"))
        if hasattr(self, 'btn_add_pen'):
            self.btn_add_pen.setToolTip(t("Thêm bút mới (nhóm 1)"))
        if hasattr(self, 'btn_highlight_more'):
            self.btn_highlight_more.setToolTip(t("Chọn bút dạ quang"))
        if hasattr(self, 'btn_add_highlight'):
            self.btn_add_highlight.setToolTip(t("Thêm bút dạ quang mới"))
        if hasattr(self, 'spin_size'):
            self.spin_size.setToolTip(t("Kích thước"))
        if hasattr(self, 'btn_color'):
            self.btn_color.setToolTip(t("Màu sắc"))

    # ── Primary pen tools (group 1) ─────────────────────────────────────

    def _build_primary_tools(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._pen_layout = layout
        self._pen_buttons = []
        for i in range(len(self._pen_slots)):
            self._add_pen_button_to_layout(i)
        self.btn_pen_more = self._tool_button(
            self._create_shape_icon("pen", color_override=self._pen_slots[self._active_pen_slot]["color"]),
            t("Chọn bút (nhóm 1)"),
            checkable=True,
            popup_mode=QToolButton.ToolButtonPopupMode.InstantPopup,
        )
        self.btn_pen_more.setMenu(QMenu(self))
        self.btn_pen_more.menu().setStyleSheet(MENU_STYLE)
        self.btn_pen_more.setVisible(False)
        layout.addWidget(self.btn_pen_more)
        self.btn_add_pen = self._tool_button(
            self._create_shape_icon("plus", color_override=QColor("#64748b")),
            t("Thêm bút mới (nhóm 1)"),
        )
        self.btn_add_pen.clicked.connect(self._add_new_pen)
        layout.addWidget(self.btn_add_pen)
        self.btn_pen = self._pen_buttons[0]
        self.btn_pen2 = self._pen_buttons[1] if len(self._pen_buttons) > 1 else self._pen_buttons[0]
        self.btn_pen3 = self._pen_buttons[2] if len(self._pen_buttons) > 2 else self._pen_buttons[0]
        return layout

    # ── Secondary pen tools (group 2) ───────────────────────────────────

    def _build_secondary_pen_tools(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._pen2_layout = layout
        self._pen2_buttons = []
        for i in range(len(self._pen2_slots)):
            self._add_pen2_button_to_layout(i)
        self.btn_pen2_more = self._tool_button(
            self._create_shape_icon("fountain_pen", color_override=self._pen2_slots[self._active_pen2_slot]["color"]),
            t("Chọn bút máy (nhóm 2)"),
            checkable=True,
            popup_mode=QToolButton.ToolButtonPopupMode.InstantPopup,
        )
        self.btn_pen2_more.setMenu(QMenu(self))
        self.btn_pen2_more.menu().setStyleSheet(MENU_STYLE)
        self.btn_pen2_more.setVisible(False)
        layout.addWidget(self.btn_pen2_more)
        self.btn_add_pen2 = self._tool_button(
            self._create_shape_icon("plus", color_override=QColor("#64748b")),
            t("Thêm bút máy mới (nhóm 2)"),
        )
        self.btn_add_pen2.clicked.connect(self._add_new_pen2)
        layout.addWidget(self.btn_add_pen2)
        return layout

    def _add_pen_button_to_layout(self, idx):
        """Create a button for pen slot `idx` (group 1), insert into layout before the '+' button."""
        slot = self._pen_slots[idx]
        btn = self._tool_button(
            self._create_shape_icon("pen", color_override=slot["color"]),
            t("Bút {n}").format(n=idx + 1),
            checkable=True,
        )
        btn.clicked.connect(lambda checked, i=idx: self._activate_pen_slot(i))
        insert_pos = self._pen_layout.count() - 2  # before btn_add_pen
        self._pen_layout.insertWidget(insert_pos, btn)
        self._pen_buttons.append(btn)

    def _add_pen2_button_to_layout(self, idx):
        """Create a button for pen slot `idx` (group 2), insert into layout before the '+' button."""
        slot = self._pen2_slots[idx]
        btn = self._tool_button(
            self._create_shape_icon("fountain_pen", color_override=slot["color"]),
            t("Bút máy {n}").format(n=idx + 1),
            checkable=True,
        )
        btn.clicked.connect(lambda checked, i=idx: self._activate_pen2_slot(i))
        insert_pos = self._pen2_layout.count() - 2  # before btn_add_pen2
        self._pen2_layout.insertWidget(insert_pos, btn)
        self._pen2_buttons.append(btn)

    def _add_new_pen(self):
        """Add a new pen slot (group 1) with default color and activate it."""
        if not self._can_add_pen_slot():
            self._show_pen_limit_reached()
            self._queue_toolbar_overflow_refresh()
            return
        color_hex = self._NEW_PEN_COLORS[len(self._pen_slots) % len(self._NEW_PEN_COLORS)]
        new_slot = {"color": QColor(color_hex), "width": 3, "opacity": 100, "style_idx": 0}
        self._pen_slots.append(new_slot)
        idx = len(self._pen_slots) - 1
        self._add_pen_button_to_layout(idx)
        self._activate_pen_slot(idx)
        self._apply_plan_restrictions()
        self._refresh_toolbar_overflow()
        self._queue_toolbar_overflow_refresh()

    def _add_new_pen2(self):
        """Add a new pen slot (group 2) with default color and activate it."""
        if not self._can_add_pen_slot():
            self._show_pen_limit_reached()
            self._queue_toolbar_overflow_refresh()
            return
        color_hex = self._NEW_PEN_COLORS[(len(self._pen2_slots) + 3) % len(self._NEW_PEN_COLORS)]
        new_slot = {"color": QColor(color_hex), "width": 16, "opacity": 100, "style_idx": 0}
        self._pen2_slots.append(new_slot)
        idx = len(self._pen2_slots) - 1
        self._add_pen2_button_to_layout(idx)
        self._activate_pen2_slot(idx)
        self._apply_plan_restrictions()
        self._refresh_toolbar_overflow()
        self._queue_toolbar_overflow_refresh()

    # ── Highlight tools ──────────────────────────────────────────────────

    def _build_highlight_tools(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._highlight_layout = layout
        self._highlight_buttons = []
        for i in range(len(self._highlight_slots)):
            self._add_highlight_button_to_layout(i)
        self.btn_highlight_more = self._tool_button(
            self._create_shape_icon("highlight", color_override=self._highlight_slots[self._active_highlight_slot]["color"]),
            t("Chọn bút dạ quang"),
            checkable=True,
            popup_mode=QToolButton.ToolButtonPopupMode.InstantPopup,
        )
        self.btn_highlight_more.setMenu(QMenu(self))
        self.btn_highlight_more.menu().setStyleSheet(MENU_STYLE)
        self.btn_highlight_more.setVisible(False)
        layout.addWidget(self.btn_highlight_more)
        self.btn_add_highlight = self._tool_button(
            self._create_shape_icon("plus", color_override=QColor("#64748b")),
            t("Thêm bút dạ quang mới"),
        )
        self.btn_add_highlight.clicked.connect(self._add_new_highlight)
        layout.addWidget(self.btn_add_highlight)
        self.btn_highlight = self._highlight_buttons[0]
        self.btn_highlight2 = self._highlight_buttons[1] if len(self._highlight_buttons) > 1 else self._highlight_buttons[0]
        return layout

    def _add_highlight_button_to_layout(self, idx):
        """Create a button for highlight slot `idx`, insert into layout before the '+' button."""
        slot = self._highlight_slots[idx]
        btn = self._tool_button(
            self._create_shape_icon("highlight", color_override=slot["color"]),
            t("Dạ quang {n}").format(n=idx + 1),
            checkable=True,
        )
        btn.clicked.connect(lambda checked, i=idx: self._activate_highlight_slot(i))
        insert_pos = self._highlight_layout.count() - 2  # before btn_add_highlight
        self._highlight_layout.insertWidget(insert_pos, btn)
        self._highlight_buttons.append(btn)

    def _add_new_highlight(self):
        if not self._can_add_pen_slot():
            self._show_pen_limit_reached()
            self._queue_toolbar_overflow_refresh()
            return
        color_hex = self._NEW_HIGHLIGHT_COLORS[len(self._highlight_slots) % len(self._NEW_HIGHLIGHT_COLORS)]
        new_slot = {"color": QColor(color_hex), "width": 15, "opacity": 50}
        self._highlight_slots.append(new_slot)
        idx = len(self._highlight_slots) - 1
        self._add_highlight_button_to_layout(idx)
        self._activate_highlight_slot(idx)
        self._apply_plan_restrictions()
        self._refresh_toolbar_overflow()
        self._queue_toolbar_overflow_refresh()

    # ── Erase / Selection tools ──────────────────────────────────────────

    def _build_erase_tools(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.btn_eraser = self._tool_button(
            self._create_shape_icon("eraser"),
            t("Xoá nét"),
            checkable=True,
        )
        self.btn_eraser.clicked.connect(lambda: self._set_mode(DrawMode.ERASER))
        layout.addWidget(self.btn_eraser)
        return layout

    def _build_selection_tools(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.btn_select_rect = self._tool_button(
            self._create_shape_icon("select_rect"),
            "ជ្រើសរើស / កែសម្រួល (Select/Edit - S)",
            checkable=True,
        )
        self.btn_select_rect.clicked.connect(lambda: self._set_mode(DrawMode.SELECT_RECT))
        layout.addWidget(self.btn_select_rect)
        self.btn_select_free = self._tool_button(
            self._create_shape_icon("select_free"),
            "ជ្រើសរើសសេរី (Lasso)",
            checkable=True,
        )
        self.btn_select_free.clicked.connect(lambda: self._set_mode(DrawMode.SELECT_FREE))
        layout.addWidget(self.btn_select_free)
        self.btn_insert_image = self._tool_button(
            self._create_shape_icon("image"),
            "បញ្ចូលរូបភាព (Ctrl+I)",
        )
        self.btn_insert_image.clicked.connect(self._insert_image)
        layout.addWidget(self.btn_insert_image)
        return layout

    # ── Stroke / Fill tools ──────────────────────────────────────────────

    def _build_stroke_tools(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.spin_size = QSpinBox()
        self.spin_size.setRange(1, 200)
        self.spin_size.setValue(3)
        self.spin_size.setPrefix("\u2195 ")
        self.spin_size.setToolTip(t("Kích cỡ bút / tẩy"))
        self.spin_size.valueChanged.connect(self._on_size_change)

        self.combo_stroke = QComboBox()
        self.combo_stroke.setObjectName("comboStroke")
        self.combo_stroke.setToolTip(t("Kiểu nét vẽ"))
        self.combo_stroke.setIconSize(QSize(40, 12))
        for label, style, pattern, icon_kind in STROKE_STYLES:
            self.combo_stroke.addItem(self._create_stroke_icon(icon_kind), t(label), (style, pattern))
            self.combo_stroke.setItemData(self.combo_stroke.count() - 1, t(label), Qt.ItemDataRole.ToolTipRole)
        self.combo_stroke.currentIndexChanged.connect(self._on_stroke_style_change)

        self.btn_color = self._tool_button(self._color_icon(QColor("black")), t("Chọn màu nét"))
        self.btn_color.clicked.connect(self._choose_color)

        self.spin_opacity = QSpinBox()
        self.spin_opacity.setRange(0, 100)
        self.spin_opacity.setValue(100)
        self.spin_opacity.setSuffix(" %")
        self.spin_opacity.setFixedWidth(72)
        self.spin_opacity.setToolTip(t("Độ mờ nét"))
        self.spin_opacity.valueChanged.connect(self._on_opacity_change)

        self.btn_stroke_props = self._tool_button(
            self._create_stroke_icon(STROKE_STYLES[0][3], QSize(30, 14)),
            t("Thuộc tính nét"),
            popup_mode=QToolButton.ToolButtonPopupMode.InstantPopup,
        )
        self.btn_stroke_props.setObjectName("btnStrokeProps")
        self.btn_stroke_props.setMenu(self._build_stroke_props_menu())
        layout.addWidget(self.btn_stroke_props)

        self.combo_fill = QComboBox()
        self.combo_fill.setObjectName("comboFill")
        self.combo_fill.setToolTip(t("Kiểu tô miền"))
        self.combo_fill.setIconSize(QSize(40, 18))
        for label, style_key in FILL_STYLES:
            self.combo_fill.addItem(
                self._create_fill_icon(style_key, QColor("#06b6d4"), QSize(44, 18)),
                t(label),
                style_key,
            )
            self.combo_fill.setItemData(self.combo_fill.count() - 1, t(label), Qt.ItemDataRole.ToolTipRole)
        self.combo_fill.currentIndexChanged.connect(self._on_fill_style_change)

        self.btn_fill_color = self._tool_button(self._color_icon(self.canvas.engine.get_active_fill_color()), t("Chọn màu tô miền"))
        self.btn_fill_color.clicked.connect(self._choose_fill_color)

        self.spin_fill_opacity = QSpinBox()
        self.spin_fill_opacity.setRange(0, 100)
        self.spin_fill_opacity.setValue(self.canvas.engine.get_active_fill_opacity())
        self.spin_fill_opacity.setSuffix(" %")
        self.spin_fill_opacity.setFixedWidth(72)
        self.spin_fill_opacity.setToolTip(t("Độ mờ tô miền"))
        self.spin_fill_opacity.valueChanged.connect(self._on_fill_opacity_change)

        self.btn_fill_props = self._tool_button(
            self._create_fill_icon("solid", self.canvas.engine.get_active_fill_color(), QSize(30, 18)),
            t("Thuộc tính tô miền"),
            popup_mode=QToolButton.ToolButtonPopupMode.InstantPopup,
        )
        self.btn_fill_props.setObjectName("btnFillProps")
        self.btn_fill_props.setMenu(self._build_fill_props_menu())
        layout.addWidget(self.btn_fill_props)

        self.btn_size_slider = None
        self.btn_stroke_style = None
        self.btn_opacity_slider = None
        self._sync_compact_toolbar_controls()
        return layout

    def _build_stroke_props_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            MENU_STYLE
            + 'QWidget { background:#1e293b; color:#f8fafc; }'
            + 'QLabel { background:transparent; color:#cbd5e1; font-size:11px; font-weight:600; }'
        )
        panel = QWidget(menu)
        grid = QGridLayout(panel)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        size_spin = QSpinBox(panel)
        size_spin.setRange(self.spin_size.minimum(), self.spin_size.maximum())
        size_spin.setPrefix(self.spin_size.prefix())
        size_spin.setSuffix(self.spin_size.suffix())
        size_spin.setFixedWidth(88)
        size_spin.setToolTip(t('Kích cỡ bút / tẩy'))
        size_spin.valueChanged.connect(self.spin_size.setValue)
        stroke_combo = QComboBox(panel)
        stroke_combo.setObjectName('comboStroke')
        stroke_combo.setIconSize(QSize(40, 12))
        stroke_combo.setToolTip(t('Kiểu nét vẽ'))
        for label, style, pattern, icon_kind in STROKE_STYLES:
            stroke_combo.addItem(self._create_stroke_icon(icon_kind), t(label), (style, pattern))
            stroke_combo.setItemData(stroke_combo.count() - 1, t(label), Qt.ItemDataRole.ToolTipRole)
        stroke_combo.currentIndexChanged.connect(self.combo_stroke.setCurrentIndex)
        color_btn = QToolButton(panel)
        color_btn.setIcon(self._color_icon(self.canvas.engine.get_active_color()))
        color_btn.setIconSize(QSize(18, 18))
        color_btn.setToolTip(t('Chọn màu nét'))
        color_btn.clicked.connect(lambda: (self._choose_color(), color_btn.setIcon(self._color_icon(self.canvas.engine.get_active_color()))))
        opacity_spin = QSpinBox(panel)
        opacity_spin.setRange(self.spin_opacity.minimum(), self.spin_opacity.maximum())
        opacity_spin.setValue(self.spin_opacity.value())
        opacity_spin.setSuffix(self.spin_opacity.suffix())
        opacity_spin.setFixedWidth(88)
        opacity_spin.setToolTip(t('Độ mờ nét'))
        opacity_spin.valueChanged.connect(self.spin_opacity.setValue)

        def sync_controls():
            size_spin.blockSignals(True)
            size_spin.setValue(self.spin_size.value())
            size_spin.blockSignals(False)
            stroke_combo.blockSignals(True)
            stroke_combo.setCurrentIndex(self.combo_stroke.currentIndex())
            stroke_combo.blockSignals(False)
            color_btn.setIcon(self._color_icon(self.canvas.engine.get_active_color()))
            opacity_spin.blockSignals(True)
            opacity_spin.setValue(self.spin_opacity.value())
            opacity_spin.blockSignals(False)

        menu.aboutToShow.connect(sync_controls)
        rows = [
            (t('Kích cỡ'), size_spin),
            (t('Kiểu nét'), stroke_combo),
            (t('Màu nét'), color_btn),
            (t('Độ mờ'), opacity_spin),
        ]
        for row, (lbl_text, widget) in enumerate(rows):
            lbl = QLabel(lbl_text)
            grid.addWidget(lbl, row, 0)
            grid.addWidget(widget, row, 1)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        return menu

    def _build_fill_props_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            MENU_STYLE
            + 'QWidget { background:#1e293b; color:#f8fafc; }'
            + 'QLabel { background:transparent; color:#cbd5e1; font-size:11px; font-weight:600; }'
        )
        panel = QWidget(menu)
        grid = QGridLayout(panel)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        fill_combo = QComboBox(panel)
        fill_combo.setObjectName('comboFill')
        fill_combo.setIconSize(QSize(40, 18))
        fill_combo.setToolTip(t('Kiểu tô miền'))
        for label, style_key in FILL_STYLES:
            fill_combo.addItem(self._create_fill_icon(style_key, QColor('#06b6d4'), QSize(44, 18)), t(label), style_key)
            fill_combo.setItemData(fill_combo.count() - 1, t(label), Qt.ItemDataRole.ToolTipRole)
        fill_combo.currentIndexChanged.connect(self.combo_fill.setCurrentIndex)
        fill_color_btn = QToolButton(panel)
        fill_color_btn.setIcon(self._color_icon(self.canvas.engine.get_active_fill_color()))
        fill_color_btn.setIconSize(QSize(18, 18))
        fill_color_btn.setToolTip(t('Chọn màu tô miền'))
        fill_color_btn.clicked.connect(lambda: (self._choose_fill_color(), fill_color_btn.setIcon(self._color_icon(self.canvas.engine.get_active_fill_color()))))
        fill_opacity_spin = QSpinBox(panel)
        fill_opacity_spin.setRange(self.spin_fill_opacity.minimum(), self.spin_fill_opacity.maximum())
        fill_opacity_spin.setValue(self.spin_fill_opacity.value())
        fill_opacity_spin.setSuffix(self.spin_fill_opacity.suffix())
        fill_opacity_spin.setFixedWidth(88)
        fill_opacity_spin.setToolTip(t('Độ mờ tô miền'))
        fill_opacity_spin.valueChanged.connect(self.spin_fill_opacity.setValue)

        def sync_controls():
            fill_combo.blockSignals(True)
            fill_combo.setCurrentIndex(self.combo_fill.currentIndex())
            fill_combo.blockSignals(False)
            fill_color_btn.setIcon(self._color_icon(self.canvas.engine.get_active_fill_color()))
            fill_opacity_spin.blockSignals(True)
            fill_opacity_spin.setValue(self.spin_fill_opacity.value())
            fill_opacity_spin.blockSignals(False)

        menu.aboutToShow.connect(sync_controls)
        rows = [
            (t('Kiểu tô'), fill_combo),
            (t('Màu tô'), fill_color_btn),
            (t('Độ mờ'), fill_opacity_spin),
        ]
        for row, (lbl_text, widget) in enumerate(rows):
            lbl = QLabel(lbl_text)
            grid.addWidget(lbl, row, 0)
            grid.addWidget(widget, row, 1)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        return menu

    def _legacy_stroke_style_menu(self):
        return self._build_stroke_props_menu()

    # ── Line / Curve / Geometry / Polygon / Free / Type tools ────────────

    def _build_line_tools(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        modes = [
            ("line", DrawMode.LINE, "Đường thẳng"),
            ("arrow", DrawMode.ARROW, "Mũi tên"),
            ("arrow_double", DrawMode.ARROW_DOUBLE, "Mũi tên đôi"),
            ("arrow_closed", DrawMode.ARROW_CLOSED, "Mũi tên đóng"),
        ]
        self._line_buttons = []
        for icon_name, mode, tooltip in modes:
            btn = self._tool_button(self._create_shape_icon(icon_name), t(tooltip), checkable=True)
            btn.clicked.connect(lambda checked, m=mode: self._set_mode(m))
            layout.addWidget(btn)
            self._line_buttons.append(btn)
        return layout

    def _build_curve_tools(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        modes = [
            ("bezier", DrawMode.BEZIER, "Đường cong Bézier"),
            ("circle", DrawMode.CIRCLE, "Hình tròn"),
            ("semicircle", DrawMode.SEMICIRCLE, "Bán nguyệt"),
            ("ellipse", DrawMode.ELLIPSE, "Hình elip"),
        ]
        self._curve_buttons = []
        for icon_name, mode, tooltip in modes:
            btn = self._tool_button(self._create_shape_icon(icon_name), t(tooltip), checkable=True)
            btn.clicked.connect(lambda checked, m=mode: self._set_mode(m))
            layout.addWidget(btn)
            self._curve_buttons.append(btn)
        return layout

    def _build_geometry_tools(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        btn_mid = self._tool_button(self._create_shape_icon("midpoint"), t("Trung điểm"), checkable=True)
        btn_mid.clicked.connect(lambda: self._select_geometry_tool('midpoint_2'))
        layout.addWidget(btn_mid)
        btn_bisect = self._tool_button(self._create_shape_icon("perpendicular_bisector"), t("Đường trung trực"), checkable=True)
        btn_bisect.clicked.connect(lambda: self._select_geometry_tool('perpendicular_bisector'))
        layout.addWidget(btn_bisect)
        return layout

    def _build_polygon_tools(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        modes = [
            ("rectangle", DrawMode.RECTANGLE, "Hình chữ nhật"),
            ("triangle", DrawMode.TRIANGLE, "Hình tam giác"),
            ("parallelogram", DrawMode.PARALLELOGRAM, "Hình bình hành"),
        ]
        self._polygon_buttons = []
        for icon_name, mode, tooltip in modes:
            btn = self._tool_button(self._create_shape_icon(icon_name), t(tooltip), checkable=True)
            btn.clicked.connect(lambda checked, m=mode: self._set_mode(m))
            layout.addWidget(btn)
            self._polygon_buttons.append(btn)
        return layout

    def _build_free_tools(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        btn_poly = self._tool_button(self._create_shape_icon("free_polygon"), t("Hình đa giác tự do"), checkable=True)
        btn_poly.clicked.connect(lambda: self._select_free_tool('free_polygon'))
        layout.addWidget(btn_poly)
        btn_curve = self._tool_button(self._create_shape_icon("free_curve"), t("Đường cong tự do"), checkable=True)
        btn_curve.clicked.connect(lambda: self._select_free_tool('freehand_sketch'))
        layout.addWidget(btn_curve)
        return layout

    def _build_type_tools(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        btn_type = self._tool_button(self._create_shape_icon("type"), t("Nhập văn bản"), checkable=True)
        btn_type.clicked.connect(lambda: self._set_mode(DrawMode.TYPE))
        layout.addWidget(btn_type)
        return layout

    # ── Page / Delete / AI / File tools ──────────────────────────────────

    def _build_page_tools(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.btn_prev = self._tool_button(self._create_shape_icon("prev"), t("Trang trước"))
        self.btn_prev.clicked.connect(self._prev_slide)
        layout.addWidget(self.btn_prev)
        self.lbl_slide = QLabel("1 / 1")
        self.lbl_slide.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_slide.setStyleSheet("font-weight:600; min-width:44px; color:#475569; font-size:11px;")
        layout.addWidget(self.lbl_slide)
        self.btn_next = self._tool_button(self._create_shape_icon("next"), t("Trang sau / thêm trang"))
        self.btn_next.clicked.connect(self._next_slide)
        layout.addWidget(self.btn_next)
        return layout

    def _build_delete_page_tools(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.btn_delete_page = self._tool_button(self._create_shape_icon("delete_page"), t("Xóa trang hiện tại"))
        self.btn_delete_page.clicked.connect(self._delete_page)
        layout.addWidget(self.btn_delete_page)
        return layout

    def _build_view_tools(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.btn_zoom_out = self._tool_button(self._create_shape_icon("zoom_out"), t("បង្រួម (Zoom Out)"))
        self.btn_zoom_out.clicked.connect(self._zoom_out_canvas)
        layout.addWidget(self.btn_zoom_out)

        self.btn_zoom_pct = QToolButton()
        self.btn_zoom_pct.setText("100%")
        self.btn_zoom_pct.setToolTip(t("កម្រិតពង្រីក-បង្រួម / កំណត់ទំហំស្លាយ (ចុចដើម្បីជ្រើសរើស)"))
        self.btn_zoom_pct.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_zoom_pct.setStyleSheet("""
            QToolButton {
                font-weight: 600;
                font-size: 11px;
                color: #334155;
                background: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 2px 4px;
                min-width: 44px;
            }
            QToolButton:hover {
                background: #e2e8f0;
                color: #0f172a;
            }
            QToolButton::menu-indicator {
                image: none;
                width: 0px;
            }
        """)

        menu = QMenu(self.btn_zoom_pct)
        menu.setStyleSheet(MENU_STYLE)

        act_fit = menu.addAction(t("⊡ សមល្មមផ្ទាំង (Fit Window)"))
        act_fit.triggered.connect(self._fit_canvas_window)

        act_fit_w = menu.addAction(t("↔ សមល្មមទទឹង (Fit Width)"))
        act_fit_w.triggered.connect(self._fit_canvas_width)

        act_fit_h = menu.addAction(t("↕ សមល្មមកម្ពស់ (Fit Height)"))
        act_fit_h.triggered.connect(self._fit_canvas_height)

        menu.addSeparator()

        for pct in (50, 75, 100, 125, 150, 200, 300):
            label = f"{pct}%" if pct != 100 else f"100% ({t('ដើម')})"
            act = menu.addAction(label)
            act.triggered.connect(lambda checked=False, p=pct: self._set_canvas_zoom(p / 100.0))

        menu.addSeparator()
        act_size = menu.addAction(t("📐 កំណត់ទំហំស្លាយ & Preamble..."))
        act_size.triggered.connect(self._open_preamble_dialog)

        self.btn_zoom_pct.setMenu(menu)
        layout.addWidget(self.btn_zoom_pct)

        self.btn_zoom_in = self._tool_button(self._create_shape_icon("zoom_in"), t("ពង្រីក (Zoom In)"))
        self.btn_zoom_in.clicked.connect(self._zoom_in_canvas)
        layout.addWidget(self.btn_zoom_in)

        self.btn_zoom_fit = self._tool_button(self._create_shape_icon("zoom_fit"), t("សមល្មមផ្ទាំង (Fit Window)"))
        self.btn_zoom_fit.clicked.connect(self._fit_canvas_window)
        layout.addWidget(self.btn_zoom_fit)

        self.btn_toggle_grid = self._tool_button(self._create_shape_icon("grid"), "ក្រឡាការ៉ូ / បន្ទាត់ក្រឡា (Writing Grid)")
        self.btn_toggle_grid.setCheckable(True)
        self.btn_toggle_grid.setChecked(getattr(self.canvas, "show_grid", True) if hasattr(self, "canvas") else True)
        self.btn_toggle_grid.clicked.connect(self._toggle_grid)
        layout.addWidget(self.btn_toggle_grid)

        if hasattr(self, "canvas") and hasattr(self.canvas, "zoom_changed"):
            self.canvas.zoom_changed.connect(self._on_canvas_zoom_updated)

        return layout

    def _toggle_grid(self) -> None:
        if hasattr(self, "canvas"):
            current = getattr(self.canvas, "show_grid", True)
            new_state = not current
            self.canvas.show_grid = new_state
            if hasattr(self, "btn_toggle_grid"):
                self.btn_toggle_grid.setChecked(new_state)
            self.canvas.update()

    def _zoom_in_canvas(self) -> None:
        if hasattr(self, "canvas") and hasattr(self.canvas, "zoom_in"):
            self.canvas.zoom_in()

    def _zoom_out_canvas(self) -> None:
        if hasattr(self, "canvas") and hasattr(self.canvas, "zoom_out"):
            self.canvas.zoom_out()

    def _fit_canvas_window(self) -> None:
        if hasattr(self, "canvas") and hasattr(self.canvas, "fit_to_window"):
            self.canvas.fit_to_window()

    def _fit_canvas_width(self) -> None:
        if hasattr(self, "canvas") and hasattr(self.canvas, "fit_to_width"):
            self.canvas.fit_to_width()

    def _fit_canvas_height(self) -> None:
        if hasattr(self, "canvas") and hasattr(self.canvas, "fit_to_height"):
            self.canvas.fit_to_height()

    def _set_canvas_zoom(self, zoom: float) -> None:
        if hasattr(self, "canvas") and hasattr(self.canvas, "set_zoom_level"):
            self.canvas.set_zoom_level(zoom)

    def _on_canvas_zoom_updated(self, zoom: float) -> None:
        if hasattr(self, "btn_zoom_pct"):
            pct = int(round(zoom * 100))
            self.btn_zoom_pct.setText(f"{pct}%")

    def _open_preamble_dialog(self) -> None:
        from dialogs.latex_preamble_dialog import LatexPreambleDialog
        dlg = LatexPreambleDialog(self, canvas=getattr(self, "canvas", None))
        dlg.exec()

    def _build_ai_tools(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.btn_ai = self._tool_button(
            self._create_shape_icon("ai"),
            t("Soạn câu hỏi AI từ vùng đã chọn (Ctrl+G)\nQuét chọn nội dung mẫu rồi bấm để Gemini sinh các câu cùng chủ đề."),
        )
        self.btn_ai.clicked.connect(self._run_ai_questions)
        layout.addWidget(self.btn_ai)
        self.btn_tikz_ai = self._tool_button(
            self._create_shape_icon("tikz_ai"),
            t("TikZ AI từ vùng đã chọn\nGemini vẽ lại vùng quét bằng mã TikZ, cho sửa và biên dịch lại."),
        )
        self.btn_tikz_ai.clicked.connect(self._run_tikz_ai)
        layout.addWidget(self.btn_tikz_ai)
        self.btn_handwriting_ai = self._tool_button(
            self._create_shape_icon("handwriting_ai"),
            t("AI chữ viết tay từ vùng đã chọn\nGemini đọc nội dung rồi tạo ảnh viết tay đè lên vùng quét."),
        )
        self.btn_handwriting_ai.clicked.connect(self._run_handwriting_ai)
        layout.addWidget(self.btn_handwriting_ai)
        self.btn_gemini_settings = self._tool_button(
            self._create_shape_icon("key"),
            "កំណត់គណនី Gemini Pro (API Key & Model)",
        )
        self.btn_gemini_settings.clicked.connect(lambda: self._open_gemini_settings_dialog())
        layout.addWidget(self.btn_gemini_settings)
        return layout

    def _build_file_tools(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        actions = [
            ("btn_insert_file", self._create_shape_icon("import"), "Chèn", self._insert_file),
            ("btn_export_pdf", self._create_shape_icon("save"), "Xuất PDF (Ctrl+S)", self._export_pdf),
            ("btn_open_settings", self._create_shape_icon("gear"), "Cài đặt bảng", self._open_settings),
        ]
        for attr, icon, tooltip, slot in actions:
            btn = self._tool_button(icon, t(tooltip))
            setattr(self, attr, btn)
            btn.clicked.connect(slot)
            layout.addWidget(btn)
        return layout

    # ── Dynamic tool menu collapse ───────────────────────────────────────

    def _set_dynamic_tools_collapsed(self, collapsed):
        """Switch pen/highlight groups to dropdown when toolbar is too narrow."""
        collapsed = bool(collapsed)
        changed = collapsed != bool(getattr(self, "_dynamic_tools_collapsed", False))
        self._dynamic_tools_collapsed = collapsed
        for btn in getattr(self, "_pen_buttons", []):
            self._set_visible_if_needed(btn, not collapsed)
        for btn in getattr(self, "_pen2_buttons", []):
            self._set_visible_if_needed(btn, not collapsed)
        for btn in getattr(self, "_highlight_buttons", []):
            self._set_visible_if_needed(btn, not collapsed)
        pen_more = getattr(self, "btn_pen_more", None)
        if pen_more:
            pen_more.setVisible(collapsed)
        pen2_more = getattr(self, "btn_pen2_more", None)
        if pen2_more:
            pen2_more.setVisible(collapsed)
        hl_more = getattr(self, "btn_highlight_more", None)
        if hl_more:
            hl_more.setVisible(collapsed)
        if changed:
            self._refresh_dynamic_tool_menus()

    def _refresh_dynamic_tool_menus(self):
        '''Làm mới menu động cho các công cụ tuỳ chỉnh.'''
        pass  # Dynamic menus are refreshed when custom tools change

    def _make_dynamic_tool_menu_signature(self):
        def _slot_signature(slot):
            color = QColor(slot.get('color', '#000000'))
            return (
                color.name(QColor.NameFormat.HexArgb) if color.isValid() else '',
                int(slot.get('width', 0) or 0),
                int(slot.get('opacity', 0) or 0),
                int(slot.get('style_idx', 0) or 0),
            )

        return (
            getattr(self, '_active_pen_slot', 0),
            getattr(self, '_active_pen2_slot', 0),
            getattr(self, '_active_highlight_slot', 0),
            tuple(_slot_signature(s) for s in getattr(self, '_pen_slots', [])),
            tuple(_slot_signature(s) for s in getattr(self, '_pen2_slots', [])),
            tuple(_slot_signature(s) for s in getattr(self, '_highlight_slots', [])),
        )

    # ── Helpers used by _tool_group ──────────────────────────────────────

    def _expanded_toolbar_left_width(self):
        content = getattr(self, "_toolbar_left_content", None)
        if content:
            return content.sizeHint().width()
        return 0

    def _toolbar_available_width(self):
        toolbar = getattr(self, "_toolbar", None)
        if toolbar:
            return toolbar.width()
        return 0

    def _toolbar_left_viewport_width(self):
        scroller = getattr(self, "_toolbar_left_scroller", None)
        if scroller:
            return scroller.viewport().width()
        return 0

    def _toolbar_right_width(self):
        width = int(getattr(self, "_toolbar_right_extra_spacing", 0))
        for w in getattr(self, "_toolbar_right_widgets", []):
            if w and w.isVisible():
                width += w.sizeHint().width()
        return width

    def _toolbar_spacing_width(self):
        row = getattr(self, "_toolbar_row", None)
        if row:
            return row.spacing()
        return 6

    def _spin_arrow_pngs(self):
        return (None, None)
