"""
dialogs/curve_tool_dialog.py
Hộp thoại nhập prompt → Gemini sinh công cụ vẽ đường cong mới.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from core.i18n import t


class CurveToolDialog(QDialog):
    def __init__(self, parent=None, tool_type: str = "curve"):
        super().__init__(parent)
        self.tool_type = tool_type

        if tool_type == "line":
            self.setWindowTitle(t("Tạo công cụ vẽ đoạn thẳng (AI)"))
        elif tool_type == "geometry":
            self.setWindowTitle(t("Tạo công cụ Điểm/Đường đặc biệt (AI)"))
        elif tool_type == "polygon":
            self.setWindowTitle(t("Tạo công cụ vẽ đa giác (AI)"))
        elif tool_type == "free":
            self.setWindowTitle(t("Tạo công cụ vẽ tự do (AI)"))
        else:
            self.setWindowTitle(t("Tạo công cụ vẽ đường cong (AI)"))

        self.setMinimumWidth(560)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        if self.tool_type == "line":
            intro = QLabel(
                t(
                    'Mô tả công cụ vẽ đoạn thẳng bạn muốn tạo (từ 2 điểm đầu mút). Ví dụ: "ngoặc nhọn nối hai điểm", "đoạn thẳng đứt đoạn đặc biệt", "mũi tên 3 nhánh"...'
                )
            )
            placeholder = t("Mô tả chi tiết công cụ vẽ đoạn thẳng cần tạo...")
        elif self.tool_type == "geometry":
            intro = QLabel(
                t(
                    'Mô tả công cụ dựng điểm/đường đặc biệt từ các điểm cho trước. Ví dụ: "trọng tâm tam giác từ 3 đỉnh", "trực tâm tam giác", "đường phân giác trong tại A của góc BAC", "đường trung trực của AB"...'
                )
            )
            placeholder = t("Mô tả rõ số điểm nhấp, vai trò từng điểm và đối tượng cần dựng...")
        elif self.tool_type == "polygon":
            intro = QLabel(
                t(
                    'Mô tả công cụ vẽ đa giác/hình khép kín bạn muốn tạo. Ví dụ: "hình thoi từ tâm và một đỉnh", "ngũ giác đều từ tâm và một đỉnh", "hình chữ nhật từ 2 góc đối diện"...'
                )
            )
            placeholder = t("Mô tả chi tiết công cụ vẽ đa giác cần tạo...")
        elif self.tool_type == "free":
            intro = QLabel(
                t(
                    'Mô tả công cụ tự do dùng số điểm không cố định. Người dùng nhấp trái để thêm điểm và nhấp phải để kết thúc. Ví dụ: "đa giác tự do", "đường cong mượt đi qua tất cả điểm", "đường bao lồi từ các điểm"...'
                )
            )
            placeholder = t("Mô tả công cụ tự do; AI sẽ khai báo N_POINTS: -1...")
        else:
            intro = QLabel(
                t(
                    'Mô tả công cụ vẽ đường cong bạn muốn tạo. Ví dụ: "hình bình hành ABCD có 3 đỉnh điểm A,B,C", "đường xoắn ốc 3 vòng", "sóng sin với 4 chu kỳ", "đường cong cardioid (hình tim)", "hyperbol giữa 2 điểm"...'
                )
            )
            placeholder = t("Mô tả chi tiết công cụ vẽ đường cong cần tạo...")

        intro.setWordWrap(True)
        intro.setStyleSheet("color:#475569;")
        root.addWidget(intro)

        self.edit_prompt = QPlainTextEdit()
        self.edit_prompt.setPlaceholderText(placeholder)
        self.edit_prompt.setMinimumHeight(140)
        root.addWidget(self.edit_prompt)

        warn = QLabel(
            t(
                "⚠ Mã do AI sinh sẽ được nạp và thực thi trong tiến trình ứng dụng. Hãy đưa ra yêu cầu sao cho xác định rõ ràng giữa giả thiết (số điểm nhấp trên bảng) và kết luận (đường cần vẽ)."
            )
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#b45309; font-size:11px;")
        root.addWidget(warn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._btn_ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._btn_ok.setText(t("Tạo công cụ"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("Huỷ"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @property
    def prompt(self) -> str:
        return self.edit_prompt.toPlainText().strip()
