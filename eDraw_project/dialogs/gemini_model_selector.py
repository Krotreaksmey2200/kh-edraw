"""Reusable Gemini model dropdown."""
from __future__ import annotations

import re
from typing import Callable

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.gemini_models import GeminiModel, fetch_gemini_generate_models, format_model_label
from core.i18n import t


class _GeminiModelFetchWorker(QObject):
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, api_key: str):
        super().__init__()
        self._api_key = api_key

    def run(self):
        try:
            self.finished.emit(fetch_gemini_generate_models(self._api_key))
        except Exception as exc:
            self.failed.emit(str(exc))


class GeminiModelSelector(QWidget):
    """Combo box that loads models compatible with Gemini generateContent."""

    def __init__(
        self,
        api_key_provider: Callable[[], str],
        initial_model: str = "",
        parent: QWidget | None = None,
        *,
        auto_load: bool = True,
    ) -> None:
        super().__init__(parent)
        self._api_key_provider = api_key_provider
        self._thread = None
        self._worker = None

        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.setMinimumContentsLength(34)
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.btn_refresh = QPushButton(t("Tải danh sách"))
        self.btn_refresh.setFixedWidth(104)
        self.btn_refresh.clicked.connect(self.load_models)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#64748b; font-size:11px;")

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.combo, 1)
        row.addWidget(self.btn_refresh)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.addLayout(row)
        root.addWidget(self.status)

        self._set_initial_model(initial_model)
        if auto_load:
            QTimer.singleShot(0, self.load_models)

    def current_model(self) -> str:
        text = self.combo.currentText().strip()
        idx = self.combo.currentIndex()
        if 0 <= idx < self.combo.count() and text == self.combo.itemText(idx):
            data = self.combo.itemData(idx)
            if data:
                return str(data).strip()
        for item_idx in range(self.combo.count()):
            item_text = self.combo.itemText(item_idx)
            item_data = str(self.combo.itemData(item_idx) or "")
            if text == item_text or text == item_data:
                return item_data.strip()
        match = re.search(r"\(([^()]+)\)\s*$", text)
        if match:
            return match.group(1).strip().removeprefix("models/")
        return text.removeprefix("models/")

    def load_models(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        api_key = (self._api_key_provider() or "").strip()
        if not api_key:
            self.status.setText(t("Nhập khóa API rồi bấm Tải danh sách mô hình."))
            return
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText(t("Đang tải…"))
        self.status.setText(t("Đang tải danh sách mô hình Gemini..."))
        thread = QThread()
        worker = _GeminiModelFetchWorker(api_key)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_models_loaded)
        worker.failed.connect(self._handle_models_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_worker_refs)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _set_initial_model(self, model: str) -> None:
        model_id = (model or "").strip().removeprefix("models/")
        if not model_id:
            return
        self.combo.clear()
        self.combo.addItem(model_id, model_id)
        self.combo.setCurrentIndex(0)

    def _handle_models_loaded(self, models: list[GeminiModel]) -> None:
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText(t("Làm mới"))
        if not models:
            self.status.setText(t("Không tìm thấy mô hình Gemini hỗ trợ generateContent."))
            return
        self._populate_models(models)
        self.status.setText(t("Đã tải {count} mô hình Gemini hỗ trợ generateContent.", count=len(models)))

    def _handle_models_failed(self, message: str) -> None:
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText(t("Tải lại"))
        self.status.setText(t("Không tải được danh sách mô hình Gemini: {error}", error=message[:220]))

    def _clear_worker_refs(self) -> None:
        self._thread = None
        self._worker = None

    def _populate_models(self, models: list[GeminiModel]) -> None:
        current_model = self.current_model()
        self.combo.blockSignals(True)
        self.combo.clear()
        current_index = -1
        for model in models:
            label = format_model_label(model)
            self.combo.addItem(label, model.id)
            idx = self.combo.count() - 1
            self.combo.setItemData(idx, self._tooltip_for_model(model), Qt.ItemDataRole.ToolTipRole)
            if model.id == current_model:
                current_index = idx
        if current_model and current_index < 0:
            self.combo.addItem(t("Mô hình đã lưu: {model}", model=current_model), current_model)
            current_index = self.combo.count() - 1
        self.combo.setCurrentIndex(current_index if current_index >= 0 else 0)
        self.combo.blockSignals(False)

    def _tooltip_for_model(self, model: GeminiModel) -> str:
        input_limit = model.input_token_limit if model.input_token_limit is not None else "N/A"
        output_limit = model.output_token_limit if model.output_token_limit is not None else "N/A"
        lines = [
            model.display_name,
            f"Model ID: {model.id}",
            f"Input limit: {input_limit}",
            f"Output limit: {output_limit}",
            f"Methods: {', '.join(model.methods)}",
        ]
        if model.description:
            lines.append(model.description)
        return "\n".join(str(line) for line in lines)
