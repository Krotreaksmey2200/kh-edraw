"""
dialogs/gemini_settings_dialog.py
Shared settings dialog for all AI features (Gemini API key + model).
Fully localized in Khmer with native support for Gemini Pro accounts.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from PyQt6.QtCore import QObject, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.app_settings import (
    DEFAULT_GEMINI_MODEL,
    load_gemini_api_key,
    load_gemini_model,
    save_gemini_api_key,
    save_gemini_model,
)
from core.i18n import t


class _GeminiKeyTestWorker(QObject):
    finished = pyqtSignal(bool, str)

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__()
        self._api_key = api_key
        self._model = model

    def run(self) -> None:
        key = self._api_key.strip()
        if not key:
            self.finished.emit(False, "សូមបញ្ចូល API Key ជាមុនសិន។")
            return

        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={urllib.parse.quote(key)}"
        req = urllib.request.Request(url, headers={"User-Agent": "eDraw/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                models = body.get("models", [])
                if models:
                    self.finished.emit(True, f"ការតភ្ជាប់ជោគជ័យ! រកឃើញ {len(models)} ម៉ូឌែល Gemini។")
                else:
                    self.finished.emit(True, "ការតភ្ជាប់ជោគជ័យ! API Key ត្រឹមត្រូវ។")
        except urllib.error.HTTPError as exc:
            err_msg = f"HTTP {exc.code}"
            try:
                body = json.loads(exc.read().decode("utf-8", errors="replace"))
                msg = body.get("error", {}).get("message")
                if msg:
                    err_msg = f"{err_msg}: {msg}"
            except Exception:
                pass
            self.finished.emit(False, err_msg)
        except Exception as exc:
            self.finished.emit(False, str(exc))


class GeminiSettingsDialog(QDialog):
    """Configuration dialog for Gemini API Key and Gemini Pro models."""

    PRO_MODELS = [
        ("gemini-pro-latest", "Gemini Pro (ម៉ូឌែល Pro ចុងក្រោយបង្អស់ - សម្រាប់គណនី Pro)"),
        ("gemini-3.1-pro-preview", "Gemini 3.1 Pro (ឆ្លាតវៃកម្រិតខ្ពស់បំផុត)"),
        ("gemini-flash-latest", "Gemini Flash (ល្បឿនលឿន)"),
        ("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite (សន្សំសំចៃ Quota & លឿន)"),
        ("gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite"),
    ]

    def __init__(self, parent=None, reason: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ការកំណត់ Gemini Pro / AI")
        self.setMinimumWidth(520)
        self._test_thread = None
        self._test_worker = None
        self._build_ui(reason)

    def _build_ui(self, reason: str | None = None) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # Header card
        header = QFrame()
        header.setStyleSheet("background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px;")
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(6, 6, 6, 6)
        h_layout.setSpacing(4)

        title_lbl = QLabel("⚙️ កំណត់គណនី Gemini Pro (Google AI)")
        title_lbl.setStyleSheet("font-weight:bold; font-size:13px; color:#1e293b;")
        h_layout.addWidget(title_lbl)

        intro_text = reason or (
            "បញ្ចូល Gemini API Key (គណនី Gemini Pro) របស់អ្នកដើម្បីដំណើរការមុខងារ AI ទាំងអស់ "
            "ដូចជា ការបង្កើតសំណួរ AI, TikZ AI និង AI អក្សរសរសេរដៃ។"
        )
        intro = QLabel(intro_text)
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#475569; font-size:11.5px;")
        h_layout.addWidget(intro)
        root.addWidget(header)

        form = QFormLayout()
        form.setSpacing(10)

        # API Key field
        self.edit_key = QLineEdit(load_gemini_api_key())
        self.edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_key.setPlaceholderText("បិទភ្ជាប់ Gemini API Key (AIzaSy...) នៅទីនេះ")
        self.edit_key.setStyleSheet("padding:6px 8px; border:1px solid #cbd5e1; border-radius:6px; font-size:12px;")

        key_row = QHBoxLayout()
        key_row.addWidget(self.edit_key, 1)

        self.btn_show = QPushButton("បង្ហាញ")
        self.btn_show.setCheckable(True)
        self.btn_show.setFixedWidth(64)
        self.btn_show.setStyleSheet("padding:6px; border:1px solid #cbd5e1; border-radius:6px;")
        self.btn_show.toggled.connect(self._toggle_key_visible)
        key_row.addWidget(self.btn_show)

        form.addRow("Gemini API Key:", key_row)

        # Model Selector combo
        self.combo_model = QComboBox()
        self.combo_model.setEditable(True)
        self.combo_model.setStyleSheet("padding:6px 8px; border:1px solid #cbd5e1; border-radius:6px; font-size:12px;")
        
        current_model = load_gemini_model() or DEFAULT_GEMINI_MODEL
        matched_idx = -1
        for idx, (m_id, m_label) in enumerate(self.PRO_MODELS):
            self.combo_model.addItem(f"{m_id} - {m_label}", m_id)
            if m_id == current_model:
                matched_idx = idx

        if matched_idx >= 0:
            self.combo_model.setCurrentIndex(matched_idx)
        else:
            self.combo_model.addItem(current_model, current_model)
            self.combo_model.setCurrentIndex(self.combo_model.count() - 1)

        form.addRow("ម៉ូឌែល Gemini:", self.combo_model)
        root.addLayout(form)

        # Test Connection & Get Key row
        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)

        self.btn_test = QPushButton("🔍 សាកល្បងតភ្ជាប់ (Test Connection)")
        self.btn_test.setStyleSheet("background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; border-radius:6px; padding:6px 12px; font-weight:500;")
        self.btn_test.clicked.connect(self._test_connection)
        actions_row.addWidget(self.btn_test)

        self.btn_get_key = QPushButton("🔑 យក API Key ពី Google")
        self.btn_get_key.setStyleSheet("background:#f8fafc; color:#475569; border:1px solid #cbd5e1; border-radius:6px; padding:6px 10px;")
        self.btn_get_key.clicked.connect(self._open_ai_studio_link)
        actions_row.addWidget(self.btn_get_key)
        actions_row.addStretch()

        root.addLayout(actions_row)

        # Status Label for connection test
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size:11.5px; padding:2px;")
        root.addWidget(self.lbl_status)

        # Bottom Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._btn_ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._btn_ok.setText("រក្សាទុកការកំណត់")
        self._btn_ok.setStyleSheet("background:#2563eb; color:white; border-radius:6px; padding:6px 16px; font-weight:bold;")
        btn_cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        btn_cancel.setText("បោះបង់")
        btn_cancel.setStyleSheet("border:1px solid #cbd5e1; border-radius:6px; padding:6px 14px;")

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _toggle_key_visible(self, checked: bool) -> None:
        self.edit_key.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self.btn_show.setText("លាក់" if checked else "បង្ហាញ")

    def _open_ai_studio_link(self) -> None:
        QDesktopServices.openUrl(QUrl("https://aistudio.google.com/app/apikey"))

    def _test_connection(self) -> None:
        if self._test_thread is not None:
            try:
                if self._test_thread.isRunning():
                    return
            except RuntimeError:
                self._test_thread = None
        key = self.api_key
        if not key:
            self.lbl_status.setText("⚠️ សូមបញ្ចូល Gemini API Key មុននឹងធ្វើតេស្ត។")
            self.lbl_status.setStyleSheet("color:#b45309; font-weight:500;")
            return

        self.btn_test.setEnabled(False)
        self.btn_test.setText("កំពុងតភ្ជាប់…")
        self.lbl_status.setText("🔄 កំពុងសាកល្បងតភ្ជាប់ទៅកាន់ Google Gemini API...")
        self.lbl_status.setStyleSheet("color:#475569;")

        thread = QThread(self)
        worker = _GeminiKeyTestWorker(key, self.model)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_test_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._test_thread = thread
        self._test_worker = worker
        thread.start()

    def _on_test_finished(self, success: bool, message: str) -> None:
        self._test_thread = None
        self._test_worker = None
        self.btn_test.setEnabled(True)
        self.btn_test.setText("🔍 សាកល្បងតភ្ជាប់ (Test Connection)")
        if success:
            self.lbl_status.setText(f"✓ {message}")
            self.lbl_status.setStyleSheet("color:#16a34a; font-weight:bold; font-size:12px;")
        else:
            self.lbl_status.setText(f"✗ មិនអាចតភ្ជាប់បាន: {message}")
            self.lbl_status.setStyleSheet("color:#dc2626; font-size:11.5px;")

    def accept(self) -> None:
        if not self.api_key:
            QMessageBox.warning(
                self,
                "ខ្វះ API Key",
                "សូមបញ្ចូល Gemini API Key មុនពេលរក្សាទុកការកំណត់។",
            )
            return
        save_gemini_api_key(self.api_key)
        save_gemini_model(self.model)
        super().accept()

    @property
    def api_key(self) -> str:
        return self.edit_key.text().strip()

    @property
    def model(self) -> str:
        idx = self.combo_model.currentIndex()
        if idx >= 0:
            data = self.combo_model.itemData(idx)
            if data:
                return str(data).strip()
        text = self.combo_model.currentText().strip()
        if " - " in text:
            text = text.split(" - ")[0].strip()
        return text.removeprefix("models/").strip() or DEFAULT_GEMINI_MODEL
