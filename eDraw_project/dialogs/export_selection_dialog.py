"""Hộp thoại chọn định dạng xuất vùng chọn: PNG, PDF, hoặc copy thẳng vào clipboard."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core.i18n import t


class ExportSelectionDialog(QDialog):
    PNG = "png"
    PDF = "pdf"
    COPY_PNG = "copy_png"

    def __init__(self, parent=None, sel_width: int = 0, sel_height: int = 0) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Xuất vùng chọn"))
        self.setMinimumWidth(440)
        self.chosen_format: str | None = None
        self._build_ui(sel_width, sel_height)

    def _build_ui(self, sel_width: int, sel_height: int) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        if sel_width > 0 and sel_height > 0:
            info = QLabel(t("Kích thước vùng chọn: {w} × {h} px", w=sel_width, h=sel_height))
            info.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(info)

        desc = QLabel(t("Chọn định dạng xuất:"))
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_png = QPushButton()
        self.btn_png.setText(t("PNG\n(ảnh chất lượng cao nhất)"))
        self.btn_png.setMinimumHeight(72)
        self.btn_png.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_png.setToolTip(t("Lưu vùng chọn thành ảnh PNG không mất dữ liệu"))
        self.btn_png.clicked.connect(lambda: self._choose(self.PNG))
        btn_row.addWidget(self.btn_png)

        self.btn_pdf = QPushButton()
        self.btn_pdf.setText(t("PDF\n(ảnh dạng vector)"))
        self.btn_pdf.setMinimumHeight(72)
        self.btn_pdf.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pdf.setToolTip(t("Lưu vùng chọn vào file PDF, trang vừa khít nội dung"))
        self.btn_pdf.clicked.connect(lambda: self._choose(self.PDF))
        btn_row.addWidget(self.btn_pdf)

        self.btn_copy = QPushButton()
        self.btn_copy.setText(t("Copy PNG\n(vào clipboard)"))
        self.btn_copy.setMinimumHeight(72)
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.setToolTip(t("Sao chép ảnh PNG vùng chọn thẳng vào clipboard"))
        self.btn_copy.clicked.connect(lambda: self._choose(self.COPY_PNG))
        btn_row.addWidget(self.btn_copy)

        layout.addLayout(btn_row)

        btn_cancel = QPushButton(t("Hủy"))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

    def _choose(self, fmt: str) -> None:
        self.chosen_format = fmt
        self.accept()
