"""
actions/modes_mixin.py
Mode selection + UI state sync logic for MainWindow.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QColorDialog,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
)

from core.drawing_engine import DrawMode, PenKind
from core.i18n import t
from ui.constants import CURVE_MODES, FILL_STYLES, LINE_MODES, POLYGON_MODES, STROKE_STYLES


class ModesMixin:
    """Select mode (line/curve/polygon/custom), load pen slot, sync UI."""

    def _select_line_mode(self, mode):
        self._current_line_mode = mode
        self._set_mode(mode)

    def _select_curve_mode(self, mode):
        self._current_curve_mode = mode
        self._set_mode(mode)

    def _select_polygon_mode(self, mode):
        self._current_polygon_mode = mode
        self._set_mode(mode)

    def _select_free_tool(self, name: str):
        """Activate free tool: click many points, right-click to finish."""
        # Check both custom_tools and free_tools
        tool = self.canvas.engine.custom_tools.get(name)
        if not tool:
            tool = self.canvas.engine.free_tools.get(name)
        if not tool:
            return
        self._current_free_tool_name = name
        self._current_custom_tool_name = name
        self.canvas.engine.current_custom_tool = name
        built_in = name in self.canvas.engine.free_tools
        desc = t(tool.get("description", "")) if built_in else tool.get("description", "")
        if not desc:
            desc = t("Công cụ tự do: {name}", name=name)
        if hasattr(self, "btn_free_family"):
            if name == "free_polygon":
                icon = self._create_shape_icon("free_polygon")
            elif name == "freehand_sketch":
                icon = self._create_shape_icon("free_curve")
            else:
                icon = self._create_tool_preview_icon(tool["fn"], tool["n_points"], "free")
            self.btn_free_family.setIcon(icon)
        self._set_free_tool_tooltip(desc)
        mode = DrawMode.CUSTOM_FREE if tool.get('tool_type') == 'free' else DrawMode.CUSTOM_POLYGON
        self._set_mode(mode)

    def _set_free_tool_tooltip(self, desc=None):
        if not hasattr(self, "btn_free_family"):
            return
        if desc is None:
            tool = self.canvas.engine.custom_tools.get(self._current_free_tool_name, {})
            desc = t(tool.get("description", "")) or t("Công cụ tự do")
        self.btn_free_family.setToolTip(desc)

    def _select_custom_curve(self, name: str):
        """Activate AI curve tool named `name`."""
        if name not in self.canvas.engine.custom_tools:
            return
        self._current_curve_mode = DrawMode.CUSTOM_CURVE
        self._current_custom_tool_name = name
        self.canvas.engine.current_custom_tool = name
        tool = self.canvas.engine.custom_tools[name]
        desc = t(tool.get("description", "")) or t("Công cụ AI: {name}", name=name)
        self.btn_curve_family.setIcon(self._create_tool_preview_icon(tool["fn"], tool["n_points"], "curve"))
        self.btn_curve_family.setToolTip(f"AI · {name}\n{desc}")
        self._set_mode(DrawMode.CUSTOM_CURVE)

    def _select_custom_polygon(self, name: str):
        """Activate AI polygon tool named `name`."""
        if name not in self.canvas.engine.custom_tools:
            return
        self._current_polygon_mode = DrawMode.CUSTOM_POLYGON
        self._current_custom_tool_name = name
        self.canvas.engine.current_custom_tool = name
        tool = self.canvas.engine.custom_tools[name]
        desc = t(tool.get("description", "")) or t("Công cụ đa giác AI: {name}", name=name)
        self.btn_polygon_family.setIcon(self._create_tool_preview_icon(tool["fn"], tool["n_points"], "polygon"))
        self.btn_polygon_family.setToolTip(f"AI · {name}\n{desc}")
        self._set_mode(DrawMode.CUSTOM_POLYGON)

    def _select_custom_line(self, name: str):
        """Activate AI line tool named `name`."""
        if name not in self.canvas.engine.custom_tools:
            return
        self._current_line_mode = DrawMode.CUSTOM_LINE
        self._current_custom_tool_name = name
        self.canvas.engine.current_custom_tool = name
        tool = self.canvas.engine.custom_tools[name]
        desc = t(tool.get("description", "")) or t("Công cụ AI: {name}", name=name)
        self.btn_line_family.setIcon(self._create_tool_preview_icon(tool["fn"], tool["n_points"], "line"))
        self.btn_line_family.setToolTip(f"AI · {name}\n{desc}")
        self._set_mode(DrawMode.CUSTOM_LINE)

    def _select_geometry_tool(self, name: str):
        """Activate geometry tool (point/line special), both built-in and AI."""
        tool = self.canvas.engine.custom_tools.get(name)
        if not tool:
            tool = self.canvas.engine.geometry_tools.get(name)
        if not tool:
            return
        self._current_custom_tool_name = name
        self.canvas.engine.current_custom_tool = name
        desc = t(tool.get("description", "")) or t("Công cụ hình học: {name}", name=name)
        if hasattr(self, "btn_geometry_family"):
            if name == "midpoint_2":
                icon = self._create_shape_icon("midpoint")
            elif name == "perpendicular_bisector":
                icon = self._create_shape_icon("perpendicular_bisector")
            else:
                icon = self._create_tool_preview_icon(tool["fn"], tool["n_points"], "geometry")
            self.btn_geometry_family.setIcon(icon)
            self.btn_geometry_family.setToolTip(f"{desc}\n{t('Điểm nhấp: {points}', points=tool['n_points'])}")
        self._set_mode(DrawMode.CUSTOM_GEOMETRY)

    def _activate_pen_slot(self, idx: int):
        """Activate pen group-1 slot and load its settings into the engine."""
        self._active_pen_slot = idx
        self._active_pen_group = 1
        self._load_pen_slot_to_engine(idx)
        self._set_mode(DrawMode.FREEHAND)
        style_idx = self._pen_slots[idx]["style_idx"]
        self.combo_stroke.blockSignals(True)
        self.combo_stroke.setCurrentIndex(style_idx)
        self.combo_stroke.blockSignals(False)
        if hasattr(self, "_sync_compact_toolbar_controls"):
            self._sync_compact_toolbar_controls()
        self._refresh_toolbar_overflow()

    def _activate_pen2_slot(self, idx: int):
        """Activate pen group-2 slot and load its settings into the engine."""
        self._active_pen2_slot = idx
        self._active_pen_group = 2
        self._load_pen2_slot_to_engine(idx)
        self._set_mode(DrawMode.FREEHAND)
        style_idx = self._pen2_slots[idx]["style_idx"]
        self.combo_stroke.blockSignals(True)
        self.combo_stroke.setCurrentIndex(style_idx)
        self.combo_stroke.blockSignals(False)
        if hasattr(self, "_sync_compact_toolbar_controls"):
            self._sync_compact_toolbar_controls()
        self._refresh_toolbar_overflow()

    def _activate_highlight_slot(self, idx: int):
        """Activate highlight slot and load settings into the engine."""
        self._active_highlight_slot = idx
        self._load_highlight_slot_to_engine(idx)
        self._set_mode(DrawMode.HIGHLIGHT)
        self._refresh_toolbar_overflow()

    def _load_pen_slot_to_engine(self, idx: int):
        slot = self._pen_slots[idx]
        self.canvas.engine.pen_kind = PenKind.NORMAL
        self.canvas.engine.pen_color = QColor(slot["color"])
        self.canvas.engine.pen_width = int(slot["width"])
        try:
            opacity = max(0, min(100, int(slot.get("opacity", 100))))
            slot["opacity"] = opacity
            self.canvas.engine.pen_opacity = opacity
            self.canvas.engine.pen_style_idx = int(slot["style_idx"])
            pattern = STROKE_STYLES[slot["style_idx"]][2]
            style = STROKE_STYLES[slot["style_idx"]][1]
            self.canvas.engine.pen_style = style
            self.canvas.engine.pen_dash_pattern = list(pattern) if pattern else None
        except (TypeError, ValueError):
            self.canvas.engine.pen_opacity = 100

    def _load_pen2_slot_to_engine(self, idx: int):
        """Load group-2 pen slot parameters into the engine."""
        slot = self._pen2_slots[idx]
        self.canvas.engine.pen_kind = PenKind.CALLIGRAPHY
        self.canvas.engine.pen_color = QColor(slot["color"])
        self.canvas.engine.pen_width = int(slot["width"])
        try:
            opacity = max(0, min(100, int(slot.get("opacity", 100))))
            slot["opacity"] = opacity
            self.canvas.engine.pen_opacity = opacity
            self.canvas.engine.pen_style_idx = int(slot["style_idx"])
            pattern = STROKE_STYLES[slot["style_idx"]][2]
            style = STROKE_STYLES[slot["style_idx"]][1]
            self.canvas.engine.pen_style = style
            self.canvas.engine.pen_dash_pattern = list(pattern) if pattern else None
        except (TypeError, ValueError):
            self.canvas.engine.pen_opacity = 100

    def _load_highlight_slot_to_engine(self, idx: int):
        slot = self._highlight_slots[idx]
        self.canvas.engine.highlight_color = QColor(slot["color"])
        self.canvas.engine.highlight_width = int(slot["width"])
        self.canvas.engine.highlight_opacity = int(slot["opacity"])

    def _set_mode(self, mode):
        if mode in (DrawMode.SELECT_RECT, DrawMode.SELECT_FREE):
            commit_floating = getattr(self.canvas, "commit_floating_for_selection_mode", None)
            if callable(commit_floating):
                commit_floating()
        self.canvas.mode = mode
        self._sync_ui_for_mode(mode)
        is_eraser = mode == DrawMode.ERASER
        size_tooltip = self._size_tooltip_for_mode(mode)
        self.spin_size.blockSignals(True)
        self.spin_size.setValue(self.canvas.eraser_width if is_eraser else self.canvas.engine.get_active_width())
        self.spin_size.blockSignals(False)
        self.spin_size.setToolTip(t(size_tooltip))

    def _sync_fill_controls_for_mode(self):
        if not hasattr(self, "combo_fill"):
            return
        engine = self.canvas.engine
        style_idx = engine.get_active_fill_style_idx()
        if 0 <= style_idx < self.combo_fill.count():
            self.combo_fill.blockSignals(True)
            self.combo_fill.setCurrentIndex(style_idx)
            self.combo_fill.blockSignals(False)
        if hasattr(self, "spin_fill_opacity"):
            self.spin_fill_opacity.blockSignals(True)
            self.spin_fill_opacity.setValue(engine.get_active_fill_opacity())
            self.spin_fill_opacity.blockSignals(False)
        if hasattr(self, "btn_fill_color"):
            self.btn_fill_color.setIcon(self._color_icon(engine.get_active_fill_color()))

    def _size_tooltip_for_mode(self, mode) -> str:
        if mode == DrawMode.TYPE:
            return t("Kích cỡ Markdown")
        if mode == DrawMode.ERASER:
            return t("Kích cỡ tẩy")
        return t("Kích cỡ bút / tẩy")

    def _sync_ui_for_mode(self, mode):
        """Sync toolbar button check-states and control visibility for the active mode."""
        # Build a mapping of mode -> button(s) that should be checked
        mode_button_map: dict[DrawMode, list] = {}

        # Pen buttons (group 1) -> FREEHAND
        for btn in getattr(self, "_pen_buttons", []):
            mode_button_map.setdefault(DrawMode.FREEHAND, []).append(btn)
        # Pen buttons (group 2) -> FREEHAND
        for btn in getattr(self, "_pen2_buttons", []):
            mode_button_map.setdefault(DrawMode.FREEHAND, []).append(btn)

        # Highlight buttons -> HIGHLIGHT
        for btn in getattr(self, "_highlight_buttons", []):
            mode_button_map.setdefault(DrawMode.HIGHLIGHT, []).append(btn)

        # Eraser
        if hasattr(self, "btn_eraser"):
            mode_button_map.setdefault(DrawMode.ERASER, []).append(self.btn_eraser)

        # Selection tools
        if hasattr(self, "btn_select_rect"):
            mode_button_map.setdefault(DrawMode.SELECT_RECT, []).append(self.btn_select_rect)
        if hasattr(self, "btn_select_free"):
            mode_button_map.setdefault(DrawMode.SELECT_FREE, []).append(self.btn_select_free)

        # Line tools
        line_modes = [DrawMode.LINE, DrawMode.ARROW, DrawMode.ARROW_DOUBLE, DrawMode.ARROW_CLOSED]
        for i, btn in enumerate(getattr(self, "_line_buttons", [])):
            if i < len(line_modes):
                mode_button_map.setdefault(line_modes[i], []).append(btn)

        # Curve tools
        curve_modes = [DrawMode.BEZIER, DrawMode.CIRCLE, DrawMode.SEMICIRCLE, DrawMode.ELLIPSE]
        for i, btn in enumerate(getattr(self, "_curve_buttons", [])):
            if i < len(curve_modes):
                mode_button_map.setdefault(curve_modes[i], []).append(btn)

        # Polygon tools
        polygon_modes = [DrawMode.RECTANGLE, DrawMode.TRIANGLE, DrawMode.PARALLELOGRAM]
        for i, btn in enumerate(getattr(self, "_polygon_buttons", [])):
            if i < len(polygon_modes):
                mode_button_map.setdefault(polygon_modes[i], []).append(btn)

        # Custom modes map to family buttons if they exist
        for custom_mode, btn_attr in [
            (DrawMode.CUSTOM_LINE, "btn_line_family"),
            (DrawMode.CUSTOM_CURVE, "btn_curve_family"),
            (DrawMode.CUSTOM_POLYGON, "btn_polygon_family"),
            (DrawMode.CUSTOM_GEOMETRY, "btn_geometry_family"),
            (DrawMode.CUSTOM_FREE, "btn_free_family"),
        ]:
            if hasattr(self, btn_attr):
                mode_button_map.setdefault(custom_mode, []).append(getattr(self, btn_attr))

        # Type
        # (type button is inline in _build_type_tools, check via attribute)

        # Collect ALL checkable buttons
        all_checkable_buttons = set()
        for btns in mode_button_map.values():
            for btn in btns:
                if btn and btn.isCheckable():
                    all_checkable_buttons.add(btn)

        # Determine which button should be active for the current mode
        active_buttons = set()
        if mode == DrawMode.FREEHAND:
            # Only check the active pen slot button, not all pen buttons
            grp = getattr(self, "_active_pen_group", 1)
            if grp == 2:
                idx = getattr(self, "_active_pen2_slot", 0)
                pen2_btns = getattr(self, "_pen2_buttons", [])
                if 0 <= idx < len(pen2_btns):
                    active_buttons.add(pen2_btns[idx])
            else:
                idx = getattr(self, "_active_pen_slot", 0)
                pen_btns = getattr(self, "_pen_buttons", [])
                if 0 <= idx < len(pen_btns):
                    active_buttons.add(pen_btns[idx])
        elif mode == DrawMode.HIGHLIGHT:
            idx = getattr(self, "_active_highlight_slot", 0)
            hl_btns = getattr(self, "_highlight_buttons", [])
            if 0 <= idx < len(hl_btns):
                active_buttons.add(hl_btns[idx])
        elif mode in mode_button_map:
            for btn in mode_button_map[mode]:
                active_buttons.add(btn)

        # Apply checked states
        for btn in all_checkable_buttons:
            should_be_checked = btn in active_buttons
            if btn.isChecked() != should_be_checked:
                btn.blockSignals(True)
                btn.setChecked(should_be_checked)
                btn.blockSignals(False)

        # Sync stroke/fill controls
        self._sync_fill_controls_for_mode()

        # Update opacity spinbox
        if hasattr(self, "spin_opacity"):
            self.spin_opacity.blockSignals(True)
            if mode == DrawMode.HIGHLIGHT:
                self.spin_opacity.setValue(self.canvas.engine.highlight_opacity)
            else:
                self.spin_opacity.setValue(self.canvas.engine.get_active_opacity())
            self.spin_opacity.blockSignals(False)

        # Update color button
        if hasattr(self, "btn_color"):
            if mode == DrawMode.HIGHLIGHT:
                self.btn_color.setIcon(self._color_icon(self.canvas.engine.highlight_color))
            else:
                self.btn_color.setIcon(self._color_icon(self.canvas.engine.get_active_color()))


    def _on_size_change(self, val):
        if self.canvas.mode == DrawMode.ERASER:
            self.canvas.eraser_width = val
        else:
            self.canvas.engine.set_active_width(val)
            if self.canvas.mode == DrawMode.FREEHAND:
                grp = getattr(self, "_active_pen_group", 1)
                if grp == 2:
                    self._pen2_slots[self._active_pen2_slot]["width"] = val
                else:
                    self._pen_slots[self._active_pen_slot]["width"] = val
            elif self._active_tool_follows_pen():
                self._sync_active_pen_slot_from_engine()
            elif self.canvas.mode == DrawMode.HIGHLIGHT:
                self._highlight_slots[self._active_highlight_slot]["width"] = val
        if hasattr(self.canvas, "apply_width_to_selection"):
            self.canvas.apply_width_to_selection(val)
        if hasattr(self, "_sync_compact_toolbar_controls"):
            self._sync_compact_toolbar_controls()

    def _on_stroke_style_change(self, idx):
        style, pattern = self.combo_stroke.itemData(idx)
        self.canvas.set_pen_style(style, pattern, idx)
        if self.canvas.mode == DrawMode.FREEHAND:
            grp = getattr(self, "_active_pen_group", 1)
            if grp == 2:
                self._pen2_slots[self._active_pen2_slot]["style_idx"] = idx
            else:
                self._pen_slots[self._active_pen_slot]["style_idx"] = idx
        elif self._active_tool_follows_pen():
            self._sync_active_pen_slot_from_engine()
        if hasattr(self, "_sync_compact_toolbar_controls"):
            self._sync_compact_toolbar_controls()

    def _on_stroke_style_change_from_menu(self, idx, style, pattern):
        self.canvas.set_pen_style(style, pattern, idx)
        if self.canvas.mode == DrawMode.FREEHAND:
            grp = getattr(self, "_active_pen_group", 1)
            if grp == 2:
                self._pen2_slots[self._active_pen2_slot]["style_idx"] = idx
            else:
                self._pen_slots[self._active_pen_slot]["style_idx"] = idx
        elif self._active_tool_follows_pen():
            self._sync_active_pen_slot_from_engine()
        if hasattr(self, "_sync_compact_toolbar_controls"):
            self._sync_compact_toolbar_controls()
        if hasattr(self, "combo_stroke"):
            self.combo_stroke.blockSignals(True)
            self.combo_stroke.setCurrentIndex(idx)
            self.combo_stroke.blockSignals(False)

    def _on_fill_style_change(self, idx):
        if not (0 <= idx < len(FILL_STYLES)):
            return
        _label, style_key = FILL_STYLES[idx]
        self.canvas.engine.set_active_fill_style(style_key, idx)
        self.canvas.update()
        if hasattr(self, "_sync_compact_toolbar_controls"):
            self._sync_compact_toolbar_controls()

    def _on_opacity_change(self, val):
        val = max(0, min(100, int(val)))
        self.canvas.engine.set_active_opacity(val)
        if self.canvas.mode == DrawMode.FREEHAND:
            grp = getattr(self, "_active_pen_group", 1)
            if grp == 2:
                self._pen2_slots[self._active_pen2_slot]["opacity"] = val
            else:
                self._pen_slots[self._active_pen_slot]["opacity"] = val
        elif self._active_tool_follows_pen():
            self._sync_active_pen_slot_from_engine()
        elif self.canvas.mode == DrawMode.HIGHLIGHT:
            self._highlight_slots[self._active_highlight_slot]["opacity"] = val
        if hasattr(self, "_sync_compact_toolbar_controls"):
            self._sync_compact_toolbar_controls()

    def _on_fill_opacity_change(self, val):
        self.canvas.engine.set_active_fill_opacity(val)
        engine = self.canvas.engine
        is_curve_mode = getattr(engine, "_is_curve_mode", None)
        is_polygon_mode = getattr(engine, "_is_polygon_mode", None)
        is_fill_mode = False
        if callable(is_curve_mode) and is_curve_mode():
            is_fill_mode = True
        elif callable(is_polygon_mode) and is_polygon_mode():
            is_fill_mode = True
        if is_fill_mode and hasattr(engine, "set_active_fill_enabled"):
            engine.set_active_fill_enabled(val > 0)
        self.canvas.update()
        if hasattr(self, "_sync_compact_toolbar_controls"):
            self._sync_compact_toolbar_controls()

    def _choose_color(self):
        color = QColorDialog.getColor(self.canvas.engine.get_active_color(), self, t("Chọn màu"))
        if not color.isValid():
            return
        self.canvas.pen_color = color
        self.btn_color.setIcon(self._color_icon(color))
        if self.canvas.mode == DrawMode.FREEHAND:
            grp = getattr(self, "_active_pen_group", 1)
            if grp == 2:
                self._pen2_slots[self._active_pen2_slot]["color"] = QColor(color)
                self._pen2_buttons[self._active_pen2_slot].setIcon(
                    self._create_shape_icon("fountain_pen", color_override=color)
                )
            else:
                self._pen_slots[self._active_pen_slot]["color"] = QColor(color)
                self._pen_buttons[self._active_pen_slot].setIcon(
                    self._create_shape_icon("pen", color_override=color)
                )
        elif self._active_tool_follows_pen():
            self._sync_active_pen_slot_from_engine()
        elif self.canvas.mode == DrawMode.HIGHLIGHT:
            self._highlight_slots[self._active_highlight_slot]["color"] = QColor(color)
            self._highlight_buttons[self._active_highlight_slot].setIcon(
                self._create_shape_icon("highlight", color_override=color)
            )
        if hasattr(self.canvas, "apply_color_to_selection"):
            self.canvas.apply_color_to_selection(color)
        self._refresh_toolbar_overflow()

    def _choose_fill_color(self):
        color = QColorDialog.getColor(self.canvas.engine.get_active_fill_color(), self, t("Chọn màu tô miền"))
        if not color.isValid():
            return
        self.canvas.engine.set_active_fill_color(color)
        if hasattr(self, "btn_fill_color"):
            self.btn_fill_color.setIcon(self._color_icon(color))
        self.canvas.update()
        if hasattr(self, "_sync_compact_toolbar_controls"):
            self._sync_compact_toolbar_controls()

    def _toggle_curve_fill(self):
        focus = self.focusWidget()
        if isinstance(focus, (QPlainTextEdit, QTextEdit)):
            return
        if isinstance(focus, QLineEdit) and isinstance(focus.parentWidget(), QAbstractSpinBox):
            return
        engine = self.canvas.engine
        is_curve_mode = getattr(engine, "_is_curve_mode", None)
        is_polygon_mode = getattr(engine, "_is_polygon_mode", None)
        is_curve = callable(is_curve_mode) and is_curve_mode()
        is_polygon = callable(is_polygon_mode) and is_polygon_mode()
        if not is_curve and is_polygon:
            self.statusBar().showMessage(t("Ctrl+F chỉ bật/tắt tô miền cho nhóm Đường cong/Đa giác"), 2500)
            return
        current = bool(engine.get_active_fill_enabled()) if hasattr(engine, "get_active_fill_enabled") else False
        enabled = not current
        engine.set_active_fill_enabled(enabled)
        if enabled and engine.get_active_fill_opacity() <= 0:
            engine.set_active_fill_opacity(35)
            if hasattr(self, "spin_fill_opacity"):
                self.spin_fill_opacity.blockSignals(True)
                self.spin_fill_opacity.setValue(engine.get_active_fill_opacity())
                self.spin_fill_opacity.blockSignals(False)
        if hasattr(self, "_sync_fill_controls_for_mode"):
            self._sync_fill_controls_for_mode()
        if hasattr(self, "_sync_compact_toolbar_controls"):
            self._sync_compact_toolbar_controls()
        self.canvas.update()
        group = t("đường cong") if is_curve else t("đa giác")
        state = t("bật") if enabled else t("tắt")
        self.statusBar().showMessage(t("Tô miền {group}: {state}", group=group, state=state), 2500)

    def _toggle_free_close(self):
        focus = self.focusWidget()
        if isinstance(focus, (QPlainTextEdit, QTextEdit)):
            return
        if isinstance(focus, QLineEdit) and isinstance(focus.parentWidget(), QAbstractSpinBox):
            return
        engine = self.canvas.engine
        if engine.mode != DrawMode.CUSTOM_FREE:
            self.statusBar().showMessage(t("Ctrl+J chỉ bật/tắt nối điểm đầu-cuối cho nhóm Tự do"), 2500)
            return
        enabled = not bool(getattr(engine, "free_close_enabled", True))
        engine.free_close_enabled = enabled
        if hasattr(self, "_set_free_tool_tooltip"):
            self._set_free_tool_tooltip()
        self.canvas.update()
        state = t("bật") if enabled else t("tắt")
        self.statusBar().showMessage(t("Nối điểm đầu-cuối: {state}", state=state), 2500)

    def _toggle_border_visible(self):
        focus = self.focusWidget()
        if isinstance(focus, (QPlainTextEdit, QTextEdit)):
            return
        if isinstance(focus, QLineEdit) and isinstance(focus.parentWidget(), QAbstractSpinBox):
            return
        engine = self.canvas.engine
        is_toggle_mode = getattr(engine, "is_border_toggle_mode", None)
        if not callable(is_toggle_mode) or is_toggle_mode():
            self.statusBar().showMessage(t("Ctrl+B chỉ bật/tắt biên cho nhóm Đường cong/Đa giác/Tự do"), 2500)
            return
        enabled = not bool(engine.get_active_border_enabled())
        engine.set_active_border_enabled(enabled)
        if hasattr(self, "_sync_compact_toolbar_controls"):
            self._sync_compact_toolbar_controls()
        self.canvas.update()
        if engine.mode == DrawMode.CUSTOM_FREE:
            group = t("tự do")
        else:
            is_polygon_mode = getattr(engine, "_is_polygon_mode", None)
            group = t("đa giác") if callable(is_polygon_mode) and is_polygon_mode() else t("đường cong")
        state = t("hiện") if enabled else t("ẩn")
        self.statusBar().showMessage(t("Biên {group}: {state}", group=group, state=state), 2500)

    def _active_tool_follows_pen(self) -> bool:
        follows = getattr(self.canvas.engine, "_active_tool_follows_pen", None)
        if callable(follows):
            return bool(follows())
        return False

    def _sync_active_pen_slot_from_engine(self):
        """Sync changes from the engine back to the active pen slot."""
        if getattr(self, "_active_pen_group", 1) == 2:
            if not self._pen2_slots:
                return
            slot = self._pen2_slots[self._active_pen2_slot]
            button = self._pen2_buttons[self._active_pen2_slot]
            icon_kind = "fountain_pen"
        else:
            if not self._pen_slots:
                return
            slot = self._pen_slots[self._active_pen_slot]
            button = self._pen_buttons[self._active_pen_slot]
            icon_kind = "pen"
        color = QColor(self.canvas.engine.pen_color)
        slot["color"] = color
        slot["width"] = int(self.canvas.engine.pen_width)
        slot["opacity"] = int(self.canvas.engine.pen_opacity)
        slot["style_idx"] = int(getattr(self.canvas.engine, "pen_style_idx", 0))
        button.setIcon(self._create_shape_icon(icon_kind, color_override=color))
        self._refresh_toolbar_overflow()

    def _set_tool_attrs_follow_pen(self, enabled: bool):
        engine = self.canvas.engine
        was_enabled = bool(getattr(engine, "tool_attrs_follow_pen", False))
        engine.tool_attrs_follow_pen = bool(enabled)
        if not was_enabled and enabled:
            engine.reset_tool_attrs_to_defaults()
        self._set_mode(self.canvas.mode)
        self.canvas.update()
