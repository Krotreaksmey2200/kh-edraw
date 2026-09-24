"""
dialogs/ai_question_dialog.py
Dialog for specifying question counts per type for Gemini to generate from selected region.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.i18n import t


class AIQuestionDialog(QDialog):
    """Dialog for specifying how many questions of each type to generate."""

    def __init__(self, parent=None, default_counts: dict[str, int] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Soạn câu hỏi AI · Chế độ [C]"))
        self.setMinimumWidth(520)
        self._build_ui(default_counts or {})

    def _build_ui(self, default_counts: dict[str, int]) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 14, 16, 14)

        intro = QLabel(
            t(
                "Gemini sẽ đọc nội dung vùng bạn vừa khoanh, nhận diện chủ đề rồi sinh các câu hỏi mới theo từng loại bên dưới. Mỗi câu sau khi sinh sẽ được biên dịch LaTeX và chèn ảnh ở một trang trình chiếu mới."
            )
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#475569;")
        root.addWidget(intro)

        type_box = QWidget()
        grid = QGridLayout(type_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)

        self.spin_choice = self._make_count_spin(default_counts.get("choice", 0))
        self.spin_tf = self._make_count_spin(default_counts.get("tf", 0))
        self.spin_short = self._make_count_spin(default_counts.get("short", 0))
        self.spin_long = self._make_count_spin(default_counts.get("long", 0))

        items = [
            (t("Trắc nghiệm 4 lựa chọn"), self.spin_choice),
            (t("Trắc nghiệm Đúng/Sai"), self.spin_tf),
            (t("Trả lời ngắn"), self.spin_short),
            (t("Tự luận"), self.spin_long),
        ]
        for col, (label_text, spin) in enumerate(items):
            label = QLabel(label_text)
            label.setStyleSheet("color:#334155; font-weight:600;")
            grid.addWidget(label, 0, col, alignment=Qt.AlignmentFlag.AlignHCenter)
            grid.addWidget(spin, 1, col, alignment=Qt.AlignmentFlag.AlignHCenter)

        root.addWidget(type_box)

        form = QFormLayout()
        form.setSpacing(8)

        self.edit_topic = QLineEdit()
        self.edit_topic.setPlaceholderText(
            t("Tùy chọn — VD: hàm số bậc hai, lượng giác, hình không gian...")
        )
        form.addRow(t("Gợi ý chủ đề:"), self.edit_topic)
        root.addLayout(form)

        self.lbl_total = QLabel()
        self.lbl_total.setStyleSheet("color:#0f172a; font-weight:600;")
        for spin in (self.spin_choice, self.spin_tf, self.spin_short, self.spin_long):
            spin.valueChanged.connect(self._update_total_label)
        self._update_total_label()
        root.addWidget(self.lbl_total)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._btn_ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._btn_ok.setText(t("Sinh câu hỏi"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("Hủy"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _make_count_spin(initial: int = 0) -> QSpinBox:
        s = QSpinBox()
        s.setRange(0, 30)
        s.setValue(int(initial or 0))
        s.setFixedWidth(86)
        return s

    def _update_total_label(self) -> None:
        total = (
            self.spin_choice.value()
            + self.spin_tf.value()
            + self.spin_short.value()
            + self.spin_long.value()
        )
        self.lbl_total.setText(t("Tổng số câu sẽ sinh: {total}", total=total))
        if hasattr(self, "_btn_ok"):
            self._btn_ok.setEnabled(total > 0)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "choice": int(self.spin_choice.value()),
            "tf": int(self.spin_tf.value()),
            "short": int(self.spin_short.value()),
            "long": int(self.spin_long.value()),
        }

    def get_counts(self) -> dict[str, int]:
        return self.counts

    @property
    def total_count(self) -> int:
        return sum(self.counts.values())

    @property
    def topic_hint(self) -> str:
        return self.edit_topic.text().strip()
