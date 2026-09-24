"""
actions/custom_tools_mixin.py
Custom AI tools: install, edit code, rename, delete, persistence.
"""
from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

from core.app_settings import load_custom_tools, save_custom_tools
from core.i18n import t


class CustomToolsMixin:
    """Register, rename, edit code, delete and load/save AI drawing tools."""

    def _install_custom_tool(self, tool, tool_type, *, enforce_quota=True, persist=True, activate=True):
        """Register tool into engine, add action to menu, and activate immediately.

        Second-layer protection: re-checks quota in case of direct calls.
        """
        name = tool.get("name", "unnamed")
        tool["tool_type"] = tool_type
        self.canvas.engine.custom_tools[name] = tool
        if persist:
            self._save_custom_tools()
        if activate:
            if tool_type == "line" and hasattr(self, "_select_custom_line"):
                self._select_custom_line(name)
            elif tool_type == "geometry" and hasattr(self, "_select_geometry_tool"):
                self._select_geometry_tool(name)
            elif tool_type == "polygon" and hasattr(self, "_select_custom_polygon"):
                self._select_custom_polygon(name)
            elif tool_type == "free" and hasattr(self, "_select_free_tool"):
                self._select_free_tool(name)
            else:
                if hasattr(self, "_select_custom_curve"):
                    self._select_custom_curve(name)
        return name

    def _edit_custom_tool_code(self, name):
        """Open dialog to edit the Python code of a tool."""
        if not self.can_edit_custom_tool_code():
            QMessageBox.information(self, t("Cần gói PRO"), t("Chỉ gói PRO được xem và sửa code của công cụ AI."))
            self.statusBar().showMessage(t("Yêu cầu tài khoản PRO để sửa code."), 4000)
            return
        tool = self.canvas.engine.custom_tools.get(name)
        if not tool:
            return
        from dialogs.code_editor_dialog import CodeEditorDialog
        dlg = CodeEditorDialog(self, tool.get("code", ""), name)
        if dlg.exec() == CodeEditorDialog.DialogCode.Accepted:
            if dlg.compiled_tool:
                new_tool = dlg.compiled_tool
                new_tool["name"] = name
                new_tool["tool_type"] = tool.get("tool_type", "curve")
                if new_tool["tool_type"] == "free" and int(new_tool.get("n_points", 0)) != -1:
                    QMessageBox.warning(
                        self,
                        t("N_POINTS không hợp lệ"),
                        t("Công cụ nhóm Tự do phải khai báo `# N_POINTS: -1`."),
                    )
                    return
                self.canvas.engine.custom_tools[name] = new_tool
                self._save_custom_tools()
                desc = t(new_tool.get("description", "")) or t("Công cụ AI: {name}", name=name)
                for actions_dict in (
                    self._custom_curve_actions,
                    self._custom_line_actions,
                    self._custom_geometry_actions,
                    self._custom_polygon_actions,
                    self._custom_free_actions,
                ):
                    action = actions_dict.get(name)
                    if action:
                        action.setToolTip(desc)
                if self._current_custom_tool_name == name:
                    family_btn = {
                        "line": self.btn_line_family,
                        "geometry": self.btn_geometry_family,
                        "polygon": self.btn_polygon_family,
                        "free": self.btn_free_family,
                    }.get(new_tool["tool_type"], self.btn_curve_family)
                    family_btn.setToolTip(f"AI · {name}\n{desc}")
                self.statusBar().showMessage(t("Đã cập nhật mã cho công cụ '{name}'.", name=name), 3000)

    def _rename_custom_curve_tool(self, old_name):
        """Show dialog to enter a new name for AI tool `old_name`."""
        new_name, ok = QInputDialog.getText(
            self,
            t("Đổi tên công cụ AI"),
            t("Tên mới:"),
            QLineEdit.EchoMode.Normal,
            old_name,
        )
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        if new_name == old_name:
            return
        if new_name in self.canvas.engine.custom_tools:
            QMessageBox.warning(self, t("Trùng tên"), t("Đã có công cụ tên '{name}'.", name=new_name))
            return
        tool = self.canvas.engine.custom_tools.pop(old_name, None)
        if tool:
            tool["name"] = new_name
            self.canvas.engine.custom_tools[new_name] = tool
            self._save_custom_tools()
            self.statusBar().showMessage(t("Đã đổi tên thành '{name}'.", name=new_name), 3000)

    def _delete_custom_curve_tool(self, name):
        """Delete AI tool `name` from engine and menu."""
        ans = QMessageBox.question(
            self,
            t("Xóa công cụ AI"),
            t("Bạn có chắc muốn xóa công cụ '{name}' không?", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.canvas.engine.custom_tools.pop(name, None)
        self._save_custom_tools()
        for actions_dict in (
            self._custom_curve_actions,
            self._custom_line_actions,
            self._custom_geometry_actions,
            self._custom_polygon_actions,
            self._custom_free_actions,
        ):
            action = actions_dict.pop(name, None)
            if action:
                action.deleteLater()
        self.statusBar().showMessage(t("Đã xóa công cụ '{name}'.", name=name), 3000)

    def _init_custom_tools(self):
        """Load and recompile all saved AI tools."""
        tools_list = load_custom_tools()
        if not tools_list:
            return
        try:
            from core.custom_curve_tool import compile_curve_tool
            for item in tools_list:
                code = item.get("code", "")
                tool_type = item.get("tool_type", "curve")
                saved_name = item.get("name")
                if not code:
                    continue
                try:
                    compiled = compile_curve_tool(code)
                    if saved_name:
                        compiled["name"] = saved_name
                    self._install_custom_tool(compiled, tool_type, enforce_quota=True, persist=False, activate=False)
                except Exception as e:
                    print(f"Failed to load custom tool: {e}")
        except ImportError:
            pass

    def _save_custom_tools(self):
        """Write custom tools list back to disk (only serializable parts)."""
        serializable = []
        for name, tool in self.canvas.engine.custom_tools.items():
            entry = {
                "name": name,
                "code": tool.get("source", ""),
                "tool_type": tool.get("tool_type", "curve"),
            }
            if entry["code"]:
                serializable.append(entry)
        save_custom_tools(serializable)
