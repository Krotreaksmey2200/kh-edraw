from __future__ import annotations

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from core.custom_curve_tool import compile_curve_tool
from core.i18n import t


class CodeEditorDialog(QDialog):
    def __init__(self, parent=None, initial_code: str = "", tool_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle(t("Xem / Sửa code công cụ: {name}", name=tool_name))
        self.setMinimumSize(700, 500)
        self.compiled_tool = None
        self._build_ui(initial_code)

    def _build_ui(self, initial_code: str) -> None:
        layout = QVBoxLayout(self)
        info = QLabel(
            t(
                "Bạn có thể tùy biến mã Python của công cụ này.\nHãy đảm bảo mã hợp lệ và giữ lại metadata (# NAME, # DESC, # N_POINTS) ở đầu file."
            )
        )
        info.setStyleSheet("color: #475569;")
        layout.addWidget(info)

        self.editor = QPlainTextEdit()
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(font)
        self.editor.setPlainText(initial_code)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        code = self.editor.toPlainText()
        try:
            tool = compile_curve_tool(code)
            self.compiled_tool = tool
            self.accept()
        except ValueError as e:
            QMessageBox.critical(self, t("Lỗi biên dịch"), str(e))
        except Exception as e:
            QMessageBox.critical(self, t("Lỗi hệ thống"), t("Không thể lưu: {error}", error=e))
