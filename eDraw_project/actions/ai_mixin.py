"""
actions/ai_mixin.py
AI flows: create AI drawing tools + generate questions/images from selected region.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from core.app_settings import load_gemini_api_key, load_gemini_model, load_handwriting_font
from core.drawing_engine import DrawMode
from core.i18n import t
from dialogs.ai_question_dialog import AIQuestionDialog
from dialogs.gemini_settings_dialog import GeminiSettingsDialog


class AIMixin:
    """Create AI drawing tools, generate questions, TikZ, and handwriting images from selected region."""

    def _open_gemini_settings_dialog(self, reason=None):
        """Open the shared Gemini settings dialog."""
        dlg = GeminiSettingsDialog(self, reason=reason)
        accepted = dlg.exec() == GeminiSettingsDialog.DialogCode.Accepted
        if accepted:
            self.statusBar().showMessage("បានរក្សាទុកការកំណត់ Gemini Pro រួចរាល់។", 5000)
        return accepted

    def _handle_ai_error(self, title: str, message: str) -> None:
        """Handle AI errors gracefully, prompting to configure Gemini Pro if quota/key issues occur."""
        err_lower = str(message).lower()
        is_key_or_quota = any(
            k in err_lower
            for k in (
                "429",
                "resource_exhausted",
                "quota",
                "rate limit",
                "key",
                "invalid",
                "unregistered",
                "permission",
                "not found",
                "404",
            )
        )
        if is_key_or_quota:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(title or "កំហុស Gemini AI")
            box.setText("<b>កំហុសក្នុងការហៅ Gemini AI</b>")
            box.setInformativeText(
                "គណនីរបស់អ្នកអាចអស់ Quota ឬមិនទាន់បានកំណត់ API Key គណនី Gemini Pro នៅឡើយ។\n\n"
                f"ព័ត៌មានលម្អិត៖ {message[:250]}\n\n"
                "តើអ្នកចង់បើកផ្ទាំងកំណត់ដើម្បីបញ្ចូល API Key គណនី Gemini Pro ដែរឬទេ?"
            )
            btn_cfg = box.addButton("កំណត់ API Key Gemini Pro", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("បោះបង់", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == btn_cfg:
                self._open_gemini_settings_dialog("សូមបញ្ចូល API Key នៃគណនី Gemini Pro របស់អ្នក៖")
        else:
            QMessageBox.critical(self, title or "កំហុស Gemini AI", message)

    def _ensure_gemini_config(self, reason=None):
        """Ensure Gemini API key exists before using AI features."""
        api_key = load_gemini_api_key().strip()
        if not api_key:
            if not self._open_gemini_settings_dialog(reason):
                return None
            api_key = load_gemini_api_key().strip()
        if not api_key:
            return None
        return (api_key, load_gemini_model())

    def _open_handwriting_settings_dialog(self, reason=None):
        """Open the handwriting-specific AI settings dialog."""
        from dialogs.handwriting_settings_dialog import HandwritingSettingsDialog
        dlg = HandwritingSettingsDialog(self, reason=reason)
        accepted = dlg.exec() == HandwritingSettingsDialog.DialogCode.Accepted
        if accepted:
            self.statusBar().showMessage(t("Đã lưu cài đặt chữ viết tay."), 5000)
        return accepted

    def _ensure_handwriting_config(self, reason=None):
        """Ensure Gemini OCR key exists; handwriting images are rendered locally."""
        api_key = load_gemini_api_key().strip()
        if not api_key:
            if not self._open_handwriting_settings_dialog(reason):
                return None
            api_key = load_gemini_api_key().strip()
        if not api_key:
            return None
        return (api_key, load_gemini_model(), load_handwriting_font())

    def _open_ai_tool_dialog(self, tool_type=None):
        """Open dialog to enter prompt → call Gemini → load new tool."""
        from dialogs.curve_tool_dialog import CurveToolDialog
        dlg = CurveToolDialog(self, tool_type=tool_type)
        if dlg.exec() == CurveToolDialog.DialogCode.Accepted:
            prompt = dlg.get_prompt()
            if prompt:
                self._start_curve_tool_generation(prompt, tool_type or "curve")

    def _start_curve_tool_generation(self, prompt, tool_type="curve"):
        """Start background thread to generate a curve tool via Gemini."""
        config = self._ensure_gemini_config(t("Thiết lập Gemini trước khi tạo công cụ AI."))
        if not config:
            return
        api_key, model = config
        from core.custom_curve_tool import CustomCurveToolWorker, start_worker
        self._curve_tool_thread = None
        self._curve_tool_worker = None
        worker = CustomCurveToolWorker(api_key, model, tool_type, prompt)
        thread = start_worker(self, worker)
        worker.finished.connect(self._on_curve_tool_ready)
        worker.failed.connect(self._on_curve_tool_failed)
        thread.finished.connect(self._on_curve_tool_thread_done)
        self._curve_tool_thread = thread
        self._curve_tool_worker = worker
        if hasattr(self, "_curve_add_action"):
            self._curve_add_action.setEnabled(False)
        if hasattr(self, "_line_add_action"):
            self._line_add_action.setEnabled(False)
        if hasattr(self, "_geometry_add_action"):
            self._geometry_add_action.setEnabled(False)
        if hasattr(self, "_polygon_add_action"):
            self._polygon_add_action.setEnabled(False)
        if hasattr(self, "_free_add_action"):
            self._free_add_action.setEnabled(False)
        thread.start()

    def _open_curve_tool_log_window(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(t("Tạo công cụ vẽ AI · Tiến trình"))
        dlg.resize(640, 320)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(10, 10, 10, 10)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setStyleSheet("QPlainTextEdit { font-family:Consolas,monospace; font-size:12px; }")
        layout.addWidget(view)
        dlg._view = view
        dlg.setModal(False)
        dlg.show()
        return dlg

    def _curve_tool_log_append(self, message):
        text = str(message)
        self.statusBar().showMessage(text, 6000)
        log_dlg = getattr(self, "_curve_tool_log", None)
        if log_dlg and hasattr(log_dlg, "_view"):
            log_dlg._view.appendPlainText(text)

    def _on_curve_tool_ready(self, tool) -> None:
        """Worker đã sinh xong tool dict {name, description, code, fn}."""
        tool_type = getattr(self._curve_tool_worker, "tool_type", "curve")
        try:
            installed_name = self._install_custom_tool(tool, tool_type)
            if installed_name:
                self._curve_tool_log_append(
                    t(
                        "✓ Đã thêm công cụ '{installed_name}'. Bạn có thể vẽ ngay.",
                        installed_name=installed_name,
                    )
                )
                self.statusBar().showMessage(
                    f"Đã thêm công cụ AI '{installed_name}'.",
                    6000,
                )
                self._show_tool_ready_dialog(installed_name, tool_type)
        except Exception as exc:
            self._on_curve_tool_failed(f"Lỗi nạp công cụ: {exc}")

    def _show_tool_ready_dialog(self, name, tool_type):
        """Show success dialog with icon preview of the newly created AI tool."""
        installed_tool = self.canvas.engine.custom_tools.get(name)
        if not installed_tool:
            return
        icon = self._create_tool_preview_icon(installed_tool["fn"], installed_tool["n_points"], tool_type, size=72)
        dlg = QDialog(self)
        dlg.setWindowTitle(t("Công cụ AI sẵn sàng"))
        dlg.setFixedWidth(360)
        root = QVBoxLayout(dlg)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(16)
        lbl_icon = QLabel()
        lbl_icon.setPixmap(icon.pixmap(72, 72))
        lbl_icon.setFixedSize(72, 72)
        top.addWidget(lbl_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        lbl_name = QLabel(f"<b style='font-size:14px'>AI · {name}</b>")
        lbl_name.setTextFormat(Qt.TextFormat.RichText)
        text_col.addWidget(lbl_name)
        desc = installed_tool.get("description", "")
        if desc:
            lbl_desc = QLabel(desc)
            lbl_desc.setWordWrap(True)
            lbl_desc.setStyleSheet("color:#475569; font-size:12px;")
            text_col.addWidget(lbl_desc)
        type_label = {
            "line": t("Đoạn nối"),
            "geometry": t("Điểm/Đường đặc biệt"),
            "polygon": t("Đa giác"),
            "free": t("Tự do"),
            "curve": t("Đường cong"),
        }.get(tool_type, t("Đường cong"))
        n_points = installed_tool["n_points"]
        point_label = t("tự do") if int(n_points) == -1 else str(n_points)
        lbl_type = QLabel(t("Nhóm: {group}  ·  Điểm nhấp: {points}", group=type_label, points=point_label))
        lbl_type.setStyleSheet("color:#94a3b8; font-size:11px;")
        text_col.addWidget(lbl_type)
        top.addLayout(text_col, 1)
        root.addLayout(top)
        btn = QPushButton(t("Bắt đầu vẽ"))
        btn.setDefault(True)
        btn.setFixedHeight(34)
        btn.setStyleSheet(
            "QPushButton { background:#9333ea; color:#fff; border-radius:6px; font-weight:bold; }"
            "QPushButton:hover { background:#7e22ce; }"
        )
        btn.clicked.connect(dlg.accept)
        root.addWidget(btn)
        dlg.exec()

    def _on_curve_tool_failed(self, message):
        self._curve_tool_log_append(t("Lỗi: {message}", message=message))
        self._handle_ai_error(t("Lỗi tạo công cụ"), message)
        self.statusBar().showMessage(t("Không tạo được công cụ AI."), 6000)

    def _on_curve_tool_thread_done(self):
        self._curve_tool_thread = None
        self._curve_tool_worker = None
        for attr in ("_curve_add_action", "_line_add_action", "_geometry_add_action", "_polygon_add_action", "_free_add_action"):
            action = getattr(self, attr, None)
            if action:
                action.setEnabled(True)
        self._apply_plan_restrictions()

    # ── AI Questions ─────────────────────────────────────────────────────

    def _run_ai_questions(self):
        has_source = self.canvas.has_ai_selection_source() if hasattr(self.canvas, "has_ai_selection_source") else self.canvas.has_selection()
        if not has_source:
            self._open_gemini_settings_dialog(
                t("Thiết lập Gemini để soạn câu hỏi AI. Sau đó hãy khoanh vùng nội dung mẫu và bấm Gemini lần nữa.")
            )
            self._set_mode(DrawMode.SELECT_RECT)
            self.statusBar().showMessage(t("✦ Khoanh vùng nội dung mẫu rồi bấm AI (✦) lần nữa để Gemini sinh câu hỏi"), 10000)
            return
        config = self._ensure_gemini_config(t("Thiết lập Gemini trước khi sinh câu hỏi từ vùng đã chọn."))
        if not config:
            return
        api_key, model = config
        dlg = AIQuestionDialog(self)
        if dlg.exec() != AIQuestionDialog.DialogCode.Accepted:
            return
        counts = dlg.get_counts()
        mapped_counts = {
            "choice": counts.get("choice", 0) or counts.get("trac_nghiem", 0),
            "tf": counts.get("tf", 0) or counts.get("dung_hinh", 0),
            "short": counts.get("short", 0) or counts.get("dien_khuyet", 0),
            "long": counts.get("long", 0) or counts.get("tu_luan", 0),
        }
        if sum(mapped_counts.values()) <= 0:
            self.statusBar().showMessage("សូមជ្រើសរើសយ៉ាងហោចណាស់ ១ សំណួរដើម្បីបង្កើត។", 5000)
            return
        topic_hint = getattr(dlg, "topic_hint", "")
        self._ai_target_rect = QRectF(self.canvas._selection_rect) if self.canvas._selection_rect and not self.canvas._selection_rect.isEmpty() else None
        self._ai_target_slide = self.canvas._current_slide
        source_pix = self.canvas.ai_selection_source_pixmap()
        if source_pix is None or source_pix.isNull() or source_pix.width() < 5 or source_pix.height() < 5:
            self.statusBar().showMessage("សូមគូរ ឬជ្រើសរើសតំបន់លើក្តារខៀនជាមុនសិន។", 5000)
            return
        from core.ai_question import AIQuestionWorker, start_worker
        self._ai_thread = None
        self._ai_worker = None
        worker = AIQuestionWorker(api_key, model, source_pix, mapped_counts, topic_hint=topic_hint)
        worker.finished.connect(self._on_ai_images_ready)
        worker.failed.connect(self._on_ai_questions_failed)
        worker.progress.connect(lambda msg: self.statusBar().showMessage(msg, 5000))
        if hasattr(self, "btn_ai"):
            self.btn_ai.setEnabled(False)
        thread = start_worker(self, worker)
        thread.finished.connect(self._on_ai_thread_done)
        self._ai_thread = thread
        self._ai_worker = worker

    def _open_ai_log_window(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("ដំណើរការបង្កើតសំណួរ AI")
        dlg.resize(680, 360)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(10, 10, 10, 10)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setStyleSheet("QPlainTextEdit { font-family:Consolas,monospace; font-size:12px; }")
        layout.addWidget(view)
        dlg._view = view
        dlg.setModal(False)
        dlg.show()
        return dlg

    def _ai_log_append(self, message):
        text = str(message)
        self.statusBar().showMessage(text, 8000)
        log_dlg = getattr(self, "_ai_log", None)
        if log_dlg and hasattr(log_dlg, "_view"):
            log_dlg._view.appendPlainText(text)

    def _on_ai_images_ready(self, images: list) -> None:
        """Worker completed Gemini + LaTeX compile, placing standalone questions on the current slide at the selected area."""
        if not images:
            self._ai_log_append("មិនមានរូបភាពសំណួរណាឡើយ។")
            QMessageBox.warning(
                self,
                "មិនមានសំណួរ",
                "ប្រព័ន្ធមិនបានបង្កើតរូបភាពសំណួរណាឡើយ។ សូមពិនិត្យមើលផ្ទាំងដំណើរការសម្រាប់ព័ត៌មានបន្ថែម។",
            )
            return

        from PyQt6.QtCore import Qt, QPointF, QRectF
        from PyQt6.QtGui import QPixmap
        from models.elements import ImageElement
        from core.drawing_engine import DrawMode

        log_dlg = getattr(self, "_ai_log", None)
        if log_dlg is not None:
            log_dlg.close()
            self._ai_log = None

        target_rect = getattr(self, "_ai_target_rect", None)
        slide = getattr(self, "_ai_target_slide", self.canvas._current_slide)
        if slide not in self.canvas._slides:
            slide = self.canvas._current_slide

        if target_rect is not None and not target_rect.isEmpty():
            curr_x = target_rect.left()
            curr_y = target_rect.top()
            avail_w = max(100.0, target_rect.width())
        else:
            sw = getattr(slide, "width", 1080)
            avail_w = sw * 0.85
            curr_x = (sw - avail_w) / 2
            curr_y = max(40.0, self.canvas._scroll_y + 40.0)

        new_elements = []
        for img in images:
            if img is None or img.isNull():
                continue
            pix = QPixmap.fromImage(img)
            # Scale to fit available width
            scale = 1.0
            if pix.width() > avail_w:
                scale = avail_w / pix.width()
            elif pix.width() < avail_w * 0.7:
                scale = min(2.0, (avail_w * 0.9) / pix.width())

            el = ImageElement.make(
                source=pix,
                pos=QPointF(curr_x, curr_y),
                scale_x=scale,
                scale_y=scale,
                rotation=0.0,
            )
            slide.add_element(el)
            new_elements.append(el)
            curr_y += pix.height() * scale + 16.0

        if hasattr(slide, "_stroke_pixmap"):
            slide._stroke_pixmap.fill(Qt.GlobalColor.transparent)
        slide.save_state()

        if new_elements:
            self.canvas.mode = DrawMode.SELECT_RECT
            self.canvas._selected_elements = new_elements
            union_rect = QRectF()
            for el in new_elements:
                eb = self.canvas._element_bounds(el)
                union_rect = union_rect.united(eb) if not union_rect.isEmpty() else eb
            self.canvas._selection_rect = union_rect.adjusted(-6, -6, 6, 6)

        self.canvas.update()
        msg = f"បានបញ្ចូល {len(new_elements)} សំណួរទៅលើផ្ទាំងដែលបានជ្រើសរើសដោយជោគជ័យ។"
        self._ai_log_append(msg)
        self.statusBar().showMessage(msg, 6000)

    def _on_ai_questions_failed(self, message):
        self._ai_log_append(f"កំហុស AI៖ {message}")
        self._handle_ai_error("កំហុស Gemini AI", message)
        self.statusBar().showMessage("កំហុសក្នុងការទាក់ទង Gemini។", 6000)

    def _on_ai_thread_done(self):
        self._ai_thread = None
        self._ai_worker = None
        if hasattr(self, "btn_ai"):
            self.btn_ai.setEnabled(True)

    # ── Handwriting AI ───────────────────────────────────────────────────

    def _run_handwriting_ai(self):
        has_source = self.canvas.has_ai_selection_source() if hasattr(self.canvas, "has_ai_selection_source") else self.canvas.has_selection()
        if not has_source:
            self._open_handwriting_settings_dialog(
                t("Thiết lập Gemini để tạo ảnh chữ viết tay. Sau đó hãy quét chọn vùng cần chuyển và bấm AI chữ viết tay lần nữa.")
            )
            self._set_mode(DrawMode.SELECT_RECT)
            self.statusBar().showMessage(t("Quét chọn vùng bảng rồi bấm AI chữ viết tay lần nữa để tạo ảnh viết tay."), 10000)
            return
        config = self._ensure_handwriting_config(t("Thiết lập Gemini trước khi tạo ảnh chữ viết tay."))
        if not config:
            return
        api_key, model, font = config
        source_pix = self.canvas.ai_selection_source_pixmap()
        if source_pix is None or source_pix.isNull() or source_pix.width() < 5 or source_pix.height() < 5:
            self.statusBar().showMessage(t("Vui lòng vẽ hoặc chọn nội dung trên bảng trước khi dùng AI."), 5000)
            return
        from core.handwriting_ai import HandwritingAIWorker, start_handwriting_ai_worker
        self._handwriting_ai_thread = None
        self._handwriting_ai_worker = None
        worker = HandwritingAIWorker(api_key, model, source_pix, handwriting_font=font)
        worker.finished.connect(self._on_handwriting_ai_ready)
        worker.failed.connect(self._on_handwriting_ai_failed)
        if hasattr(self, "btn_handwriting_ai"):
            self.btn_handwriting_ai.setEnabled(False)
        res = start_handwriting_ai_worker(self, worker)
        thread = res[0] if isinstance(res, tuple) else res
        thread.finished.connect(self._on_handwriting_ai_thread_done)
        self._handwriting_ai_thread = thread
        self._handwriting_ai_worker = worker

    def _open_handwriting_ai_log_window(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(t("AI chữ viết tay · Tiến trình"))
        dlg.resize(680, 360)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(10, 10, 10, 10)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setStyleSheet("QPlainTextEdit { font-family:Consolas,monospace; font-size:12px; }")
        layout.addWidget(view)
        dlg._view = view
        dlg.setModal(False)
        dlg.show()
        return dlg

    def _handwriting_ai_log_append(self, message):
        text = str(message)
        self.statusBar().showMessage(text, 8000)
        log_dlg = getattr(self, "_handwriting_ai_log", None)
        if log_dlg and hasattr(log_dlg, "_view"):
            log_dlg._view.appendPlainText(text)

    def _on_handwriting_ai_ready(self, payload) -> None:
        from PyQt6.QtGui import QImage
        if isinstance(payload, QImage):
            self._place_handwriting_ai_image(payload)
            return

        if not isinstance(payload, dict) or payload.get("content") is None:
            self._on_handwriting_ai_failed(t("Luồng xử lý không trả về dữ liệu chữ viết tay."))
            return

        content = payload.get("content")
        try:
            block_text = " | ".join(
                str(getattr(block, "text", "")).strip() and str(block.text).replace("\n", " ")
                for block in getattr(content, "blocks", [])[:8]
                if str(getattr(block, "text", "")).strip()
            )
            main_text = str(getattr(content, "main_text", "") or "").replace("\n", " / ")
            if main_text:
                self._handwriting_ai_log_append(t("OCR nội dung chính: {text}", text=main_text[:500]))
            if block_text:
                self._handwriting_ai_log_append(t("OCR các khối: {text}", text=block_text[:700]))
        except Exception:
            pass

        self._render_handwriting_ai_payload(payload)

    def _render_handwriting_ai_payload(self, payload) -> None:
        self._handwriting_ai_render_pending = True
        self._handwriting_ai_log_append(t("Kết xuất từng khối; công thức toán dùng MathJax nếu có."))

        try:
            from core.handwriting_ai import build_handwriting_mathjax_body
            built = build_handwriting_mathjax_body(
                payload["content"],
                int(payload.get("width") or 0),
                int(payload.get("height") or 0),
                handwriting_font=str(payload.get("handwriting_font") or ""),
                source_png_bytes=payload.get("png_bytes"),
                transparent_background=True,
                preserve_source_overlay=False,
            )
        except Exception as exc:
            self._handwriting_ai_log_append(t("Không dựng được HTML MathJax: {error}", error=str(exc)[:180]))
            self._fallback_render_handwriting_ai_payload(payload)
            return

        if built is None:
            self._fallback_render_handwriting_ai_payload(payload)
            return

        html_body, render_w, render_h, has_mathjax = built
        self._handwriting_ai_log_append(t("Kết xuất qua MathJax shell của chế độ Gõ chữ: {w} x {h} px.", w=render_w, h=render_h))

        if hasattr(self.canvas, "render_handwriting_html_pixmap"):
            def fallback_from_shell() -> None:
                self._handwriting_ai_log_append(t("MathJax shell của chế độ Gõ chữ không kết xuất được, chuyển sang bộ kết xuất dự phòng."))
                self._fallback_render_handwriting_ai_payload(payload)

            started = self.canvas.render_handwriting_html_pixmap(
                html_body,
                render_w,
                render_h,
                has_mathjax,
                self._place_handwriting_ai_pixmap,
                fallback_from_shell,
            )
            if started:
                return

        self._fallback_render_handwriting_ai_payload(payload)

    def _fallback_render_handwriting_ai_payload(self, payload) -> None:
        self._handwriting_ai_log_append(t("MathJax không khả dụng, dùng bộ kết xuất cục bộ dự phòng."))
        try:
            from core.handwriting_ai import render_handwriting_image
            content = payload["content"]
            image = render_handwriting_image(
                content.main_text,
                int(payload.get("width") or 0),
                int(payload.get("height") or 0),
                labels=content.labels,
                blocks=content.blocks,
                handwriting_font=str(payload.get("handwriting_font") or ""),
                source_png_bytes=payload.get("png_bytes"),
                transparent_background=True,
                preserve_source_overlay=False,
            )
            self._place_handwriting_ai_image(image)
        except Exception as exc:
            self._handwriting_ai_render_pending = False
            self._on_handwriting_ai_failed(str(exc))

    def _place_handwriting_ai_image(self, image):
        from PyQt6.QtGui import QPixmap
        pix = QPixmap.fromImage(image)
        self._place_handwriting_ai_pixmap(pix)

    def _place_handwriting_ai_pixmap(self, pixmap):
        self._handwriting_ai_render_pending = False
        if hasattr(self, "btn_handwriting_ai"):
            self.btn_handwriting_ai.setEnabled(True)
        target = getattr(self, "_handwriting_ai_target", None)
        if hasattr(self.canvas, "replace_ai_selection_target_with_floating_pixmap"):
            ok = self.canvas.replace_ai_selection_target_with_floating_pixmap(pixmap, target)
        elif hasattr(self.canvas, "replace_ai_selection_target_with_pixmap"):
            ok = self.canvas.replace_ai_selection_target_with_pixmap(pixmap, target)
        else:
            ok = self.canvas.replace_ai_selection_with_pixmap(pixmap)
        log_dlg = getattr(self, "_handwriting_ai_log", None)
        if log_dlg and hasattr(log_dlg, "_view"):
            log_dlg._view.appendPlainText(t("✓ Đã đặt ảnh chữ viết tay lên bảng."))

    def _on_handwriting_ai_failed(self, message):
        self._handwriting_ai_render_pending = False
        self._handwriting_ai_target = None
        if hasattr(self, "btn_handwriting_ai"):
            self.btn_handwriting_ai.setEnabled(True)
        self._handwriting_ai_log_append(t("Lỗi AI chữ viết tay: {message}", message=message))
        self._handle_ai_error(t("Lỗi AI chữ viết tay"), message)
        self.statusBar().showMessage(t("Lỗi khi tạo ảnh chữ viết tay."), 6000)

    def _on_handwriting_ai_thread_done(self):
        self._handwriting_ai_thread = None
        self._handwriting_ai_worker = None
        if hasattr(self, "btn_handwriting_ai"):
            if not getattr(self, "_handwriting_ai_render_pending", False):
                self.btn_handwriting_ai.setEnabled(True)

    # ── TikZ AI ──────────────────────────────────────────────────────────

    def _run_tikz_ai(self):
        has_source = self.canvas.has_ai_selection_source() if hasattr(self.canvas, "has_ai_selection_source") else self.canvas.has_selection()
        if not has_source:
            self._open_gemini_settings_dialog(
                t("Thiết lập Gemini để dùng TikZ AI. Sau đó hãy quét chọn vùng cần vẽ lại và bấm TikZ AI lần nữa.")
            )
            self._set_mode(DrawMode.SELECT_RECT)
            self.statusBar().showMessage(t("Quét chọn vùng bảng rồi bấm TikZ AI lần nữa để Gemini tạo mã TikZ."), 10000)
            return
        config = self._ensure_gemini_config(t("Thiết lập Gemini trước khi dùng TikZ AI."))
        if not config:
            return
        api_key, model = config
        source_pix = self.canvas.ai_selection_source_pixmap()
        if source_pix is None or source_pix.isNull() or source_pix.width() < 5 or source_pix.height() < 5:
            self.statusBar().showMessage(t("Vui lòng vẽ hoặc chọn nội dung trên bảng trước khi dùng AI."), 5000)
            return
        self._tikz_ai_target = getattr(self.canvas, "_ai_selection_target", None)
        from core.tikz_ai import TikzAIWorker, start_tikz_ai_worker
        self._tikz_ai_thread = None
        worker = TikzAIWorker(
            api_key, model, source_pix,
            width_px=source_pix.width(),
            height_px=source_pix.height()
        )
        worker.finished.connect(self._on_tikz_ai_ready)
        worker.failed.connect(self._on_tikz_ai_failed)
        if hasattr(self, "btn_tikz_ai"):
            self.btn_tikz_ai.setEnabled(False)
        thread = start_tikz_ai_worker(self, worker)
        thread.finished.connect(self._on_tikz_ai_thread_done)
        self._tikz_ai_thread = thread
        self._tikz_ai_worker = worker

    def _open_tikz_ai_log_window(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(t("TikZ AI · Tiến trình"))
        dlg.resize(680, 360)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(10, 10, 10, 10)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setStyleSheet("QPlainTextEdit { font-family:Consolas,monospace; font-size:12px; }")
        layout.addWidget(view)
        dlg._view = view
        dlg.setModal(False)
        dlg.show()
        return dlg

    def _tikz_ai_log_append(self, message):
        text = str(message)
        self.statusBar().showMessage(text, 8000)
        log_dlg = getattr(self, "_tikz_ai_log", None)
        if log_dlg and hasattr(log_dlg, "_view"):
            log_dlg._view.appendPlainText(text)

    def _on_tikz_ai_ready(self, *args, **kwargs) -> None:
        code = ""
        image = None
        if len(args) >= 2:
            code, image = args[0], args[1]
        elif len(args) == 1:
            if isinstance(args[0], str):
                code = args[0]
            else:
                image = args[0]
        if not code and hasattr(self, "_tikz_ai_worker"):
            code = getattr(self._tikz_ai_worker, "_last_code", "")

        self._tikz_ai_log_append(t("Hoàn tất TikZ AI. Mở cửa sổ chỉnh sửa..."))
        log_dlg = getattr(self, "_tikz_ai_log", None)
        if log_dlg is not None:
            log_dlg.close()
            self._tikz_ai_log = None

        from dialogs.tikz_ai_dialog import TikzAIDialog
        dlg = TikzAIDialog(self, code=code, image=image, push_callback=self._push_tikz_image_to_canvas)
        self._tikz_ai_dialog = dlg
        dlg.setModal(False)
        dlg.show()
        self.statusBar().showMessage(t("TikZ AI đã sẵn sàng."), 6000)

    def _push_tikz_image_to_canvas(self, pixmap):
        target = getattr(self, "_tikz_ai_target", None)
        if hasattr(self.canvas, "replace_ai_selection_target_with_floating_pixmap"):
            ok = self.canvas.replace_ai_selection_target_with_floating_pixmap(pixmap, target)
        elif hasattr(self.canvas, "replace_ai_selection_target_with_pixmap"):
            ok = self.canvas.replace_ai_selection_target_with_pixmap(pixmap, target)
        else:
            ok = self.canvas.replace_ai_selection_with_pixmap(pixmap)
        if ok:
            self._tikz_ai_target = None
            self.statusBar().showMessage(t("Đã thay vùng chọn bằng hình TikZ."), 6000)
        return ok

    def _on_tikz_ai_failed(self, message):
        self._tikz_ai_log_append(t("Lỗi TikZ AI: {message}", message=message))
        self._handle_ai_error(t("Lỗi TikZ AI"), message)
        self.statusBar().showMessage(t("Lỗi khi tạo TikZ AI."), 6000)

    def _on_tikz_ai_thread_done(self):
        self._tikz_ai_thread = None
        self._tikz_ai_worker = None
        if hasattr(self, "btn_tikz_ai"):
            self.btn_tikz_ai.setEnabled(True)
