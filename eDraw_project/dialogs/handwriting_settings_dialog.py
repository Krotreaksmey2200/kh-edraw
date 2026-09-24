"""
dialogs/handwriting_settings_dialog.py
Settings dialog specifically for the handwriting AI feature.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.app_settings import (
    DEFAULT_GEMINI_MODEL,
    HANDWRITING_FONT_CHOICES,
    load_gemini_api_key,
    load_gemini_model,
    load_handwriting_font,
    normalize_handwriting_font,
    save_gemini_api_key,
    save_gemini_model,
    save_handwriting_font,
)
from core.i18n import t
from dialogs.gemini_model_selector import GeminiModelSelector


class HandwritingSettingsDialog(QDialog):
    def __init__(self, parent=None, reason: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Cài đặt chữ viết tay"))
        self.setMinimumWidth(560)
        self._build_ui(reason)

    def _build_ui(self, reason: str | None = None) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        intro_text = reason or t(
            "Cấu hình Gemini để đọc nội dung. Ảnh chữ viết tay được render cục bộ trong ứng dụng."
        )
        intro = QLabel(intro_text)
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#475569;")
        root.addWidget(intro)

        ocr_group = QGroupBox(t("Bước 1 · Đọc nội dung"))
        ocr_form = QFormLayout(ocr_group)
        ocr_form.setSpacing(8)

        self.edit_gemini_key = QLineEdit(load_gemini_api_key())
        self.edit_gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_gemini_key.setPlaceholderText(t("Dán khóa API Gemini vào đây..."))

        key_row = QHBoxLayout()
        key_row.addWidget(self.edit_gemini_key)

        self.btn_show_gemini = QPushButton(t("Hiện"))
        self.btn_show_gemini.setCheckable(True)
        self.btn_show_gemini.setFixedWidth(60)
        self.btn_show_gemini.toggled.connect(
            lambda checked: self._toggle_key_visible(
                self.edit_gemini_key, self.btn_show_gemini, checked
            )
        )
        key_row.addWidget(self.btn_show_gemini)

        ocr_form.addRow(t("Khóa API Gemini:"), key_row)

        self.gemini_model_selector = GeminiModelSelector(
            lambda: self.gemini_api_key, load_gemini_model(), self
        )
        self.edit_gemini_key.editingFinished.connect(
            self.gemini_model_selector.load_models
        )
        ocr_form.addRow(t("Mô hình Gemini:"), self.gemini_model_selector)

        root.addWidget(ocr_group)

        image_group = QGroupBox(t("Bước 2 · Render cục bộ"))
        image_form = QFormLayout(image_group)
        image_form.setSpacing(8)

        self.combo_handwriting_font = QComboBox()
        current_font = load_handwriting_font()
        for font_key, font_label in HANDWRITING_FONT_CHOICES.items():
            self.combo_handwriting_font.addItem(font_label, font_key)
            if font_key == current_font:
                self.combo_handwriting_font.setCurrentIndex(
                    self.combo_handwriting_font.count() - 1
                )

        image_form.addRow(t("Chọn kiểu chữ:"), self.combo_handwriting_font)
        root.addWidget(image_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._btn_ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._btn_ok.setText(t("Lưu cài đặt"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("Hủy"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _toggle_key_visible(
        self, edit: QLineEdit, button: QPushButton, checked: bool
    ) -> None:
        edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        button.setText(t("Ẩn") if checked else t("Hiện"))

    def accept(self) -> None:
        if not self.gemini_api_key:
            QMessageBox.warning(
                self,
                t("Thiếu khóa API"),
                t("Hãy nhập khóa API Gemini trước khi lưu cài đặt."),
            )
            return
        save_gemini_api_key(self.gemini_api_key)
        save_gemini_model(self.gemini_model)
        save_handwriting_font(self.handwriting_font)
        super().accept()

    @property
    def gemini_api_key(self) -> str:
        return self.edit_gemini_key.text().strip()

    @property
    def gemini_model(self) -> str:
        return (
            self.gemini_model_selector.current_model().strip()
            or DEFAULT_GEMINI_MODEL
        )

    @property
    def handwriting_font(self) -> str:
        return normalize_handwriting_font(
            str(self.combo_handwriting_font.currentData() or "")
        )
