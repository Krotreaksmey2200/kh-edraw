"""Hop thoai nhap ngu canh bo sung cho TikZ AI."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from core.i18n import t


class TikzContextDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("TikZ AI · Ngữ cảnh"))
        self.setMinimumWidth(560)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        intro = QLabel(
            t(
                "Bổ sung mô tả nếu hình có ý nghĩa đặc thù, ví dụ: biểu đồ Venn, miền nghiệm, vector, góc vuông, nét đứt..."
            )
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#475569;")
        root.addWidget(intro)

        self.edit_context = QPlainTextEdit()
        self.edit_context.setPlaceholderText(t("Tùy chọn — để trống nếu không cần."))
        self.edit_context.setMinimumHeight(120)
        self.edit_context.setStyleSheet(
            "QPlainTextEdit { font-family: Segoe UI, Arial, sans-serif; font-size: 12px; border:1px solid #cbd5e1; border-radius:6px; padding:6px; }"
        )
        root.addWidget(self.edit_context)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("Tạo TikZ"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("Hủy"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @property
    def context_text(self) -> str:
        return self.edit_context.toPlainText().strip()
