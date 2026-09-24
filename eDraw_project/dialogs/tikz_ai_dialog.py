"""Cua so sua ma TikZ AI va preview anh bien dich."""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.i18n import t
from core.tikz_ai import render_tikz_latex_to_qimage


class TikzAIDialog(QDialog):
    """Editor trai + preview phai cho ma TikZ do Gemini sinh."""

    def __init__(
        self,
        parent=None,
        *,
        code: str = "",
        image=None,
        push_callback: Callable[[QPixmap], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._push_callback = push_callback
        self._preview_pixmap = None

        self.setWindowTitle("TikZ AI")
        self.resize(1180, 760)
        self.setMinimumSize(900, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(code or "")
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setStyleSheet(
            "QPlainTextEdit { font-family: Consolas, 'Courier New', monospace; "
            "font-size: 12px; border: 1px solid #cbd5e1; border-radius: 6px; "
            "padding: 6px; background: #ffffff; color: #0f172a; }"
        )
        splitter.addWidget(self.editor)

        preview_host = QWidget()
        preview_layout = QVBoxLayout(preview_host)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)

        preview_top = QHBoxLayout()
        preview_top.setContentsMargins(0, 0, 0, 0)
        preview_top.setSpacing(8)

        self.btn_compile = QPushButton(t("Biên dịch lại"))
        self.btn_compile.setMinimumHeight(28)
        preview_top.addWidget(self.btn_compile, 0, Qt.AlignmentFlag.AlignLeft)

        self.status_label = QLabel(t("Sẵn sàng"))
        self.status_label.setStyleSheet("color:#475569; font-size:12px;")
        preview_top.addWidget(self.status_label, 1)

        preview_layout.addLayout(preview_top)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(360, 300)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview_label.setStyleSheet(
            "QLabel { background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; color:#64748b; }"
        )
        self.preview_label.setText(t("Chưa có ảnh"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview_label)
        preview_layout.addWidget(scroll, 1)

        splitter.addWidget(preview_host)
        splitter.setSizes([560, 620])

        actions = QHBoxLayout()
        actions.setSpacing(8)
        root.addLayout(actions)

        self.btn_copy_code = QPushButton(t("Sao chép mã"))
        self.btn_copy_image = QPushButton(t("Sao chép hình"))
        self.btn_push = QPushButton(t("Đẩy xuống bảng"))
        self.btn_close = QPushButton(t("Đóng"))

        for btn in (self.btn_copy_code, self.btn_copy_image, self.btn_push, self.btn_close):
            btn.setMinimumHeight(30)
            actions.addWidget(btn)

        actions.addStretch(1)

        self.btn_compile.clicked.connect(self._compile_current)
        self.btn_copy_code.clicked.connect(self._copy_code)
        self.btn_copy_image.clicked.connect(self._copy_image)
        self.btn_push.clicked.connect(self._push_to_canvas)
        self.btn_close.clicked.connect(self.close)

        if image is not None and not image.isNull():
            self._set_preview_pixmap(QPixmap.fromImage(image))
        self._update_buttons()

    def _set_busy(self, busy: bool) -> None:
        self.btn_compile.setEnabled(not busy)
        self.btn_push.setEnabled(not busy and self._preview_pixmap is not None)
        if busy:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()

    def _set_preview_pixmap(self, pixmap: QPixmap) -> None:
        self._preview_pixmap = pixmap
        shown = pixmap.scaled(
            760,
            680,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setText("")
        self.preview_label.setPixmap(shown)
        self.status_label.setText(
            t("Ảnh: {width} x {height} px", width=pixmap.width(), height=pixmap.height())
        )
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_image = self._preview_pixmap is not None and not self._preview_pixmap.isNull()
        self.btn_copy_image.setEnabled(has_image)
        self.btn_push.setEnabled(has_image and self._push_callback is not None)

    def _compile_current(self) -> None:
        self._set_busy(True)
        self.status_label.setText(t("Đang biên dịch TikZ..."))
        QGuiApplication.processEvents()
        try:
            image = render_tikz_latex_to_qimage(
                self.editor.toPlainText(),
                log_fn=lambda msg: self.status_label.setText(str(msg)),
            )
            self._set_preview_pixmap(QPixmap.fromImage(image))
        except Exception as exc:
            self.status_label.setText(t("Biên dịch thất bại"))
            QMessageBox.critical(self, t("Lỗi biên dịch TikZ"), str(exc))
        finally:
            self._set_busy(False)

    def _copy_code(self) -> None:
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.status_label.setText(t("Đã sao chép mã TikZ."))

    def _copy_image(self) -> None:
        if self._preview_pixmap is None or self._preview_pixmap.isNull():
            return
        QApplication.clipboard().setPixmap(self._preview_pixmap)
        self.status_label.setText(t("Đã sao chép hình."))

    def _push_to_canvas(self) -> None:
        if self._preview_pixmap is None or self._preview_pixmap.isNull():
            return
        if self._push_callback is None:
            return
        if self._push_callback(self._preview_pixmap):
            QApplication.clipboard().setText(self.editor.toPlainText())
            self.status_label.setText(t("Đã sao chép mã và đẩy hình xuống bảng."))
            self.close()
        else:
            QMessageBox.warning(
                self,
                t("Không có vùng chọn"),
                t("Không còn vùng chọn để thay thế. Hãy quét chọn lại vùng trên bảng."),
            )
