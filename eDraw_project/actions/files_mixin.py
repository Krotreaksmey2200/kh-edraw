"""
actions/files_mixin.py
Image clipboard, PDF import/export, settings dialog, login, reset.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QMarginsF, QMimeData, QRect, QSizeF, Qt
from PyQt6.QtGui import QColor, QImage, QImageReader, QPageLayout, QPageSize, QPainter, QPdfWriter, QPixmap
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QToolTip

from core.app_settings import load as settings_load
from core.drawing_engine import DrawMode
from core.i18n import t
from dialogs.settings_dialog import BoardSettingsDialog


class FilesMixin:
    """Image / PDF / settings / login / reset / load+apply settings."""

    def _load_and_apply_settings(self):
        """Load QSettings and update canvas + sync UI controls."""
        loaded = settings_load(self.canvas)
        self._enforce_plan_restricted_settings()
        self._sync_ui_for_mode(self.canvas.mode)

    def _copy_slot(self, slot: dict) -> dict:
        copied = dict(slot)
        if "color" in copied:
            copied["color"] = QColor(copied["color"])
        return copied

    def _ensure_default_slots(self, slots: list[dict], defaults: list[dict], min_count: int) -> list[dict]:
        if not slots:
            slots = []
        while len(slots) < min_count:
            default = defaults[len(slots) % len(defaults)]
            slots.append(self._copy_slot(default))
        return slots

    def _set_image_pixmap(self, pix: QPixmap) -> bool:
        if pix.isNull():
            return False
        self.canvas.set_floating_image(pix)
        return True

    def _paste_image_from_clipboard(self):
        """Paste image directly from clipboard: copied image, screenshot, or image file."""
        cb = QApplication.clipboard()
        mime = cb.mimeData()
        if mime.hasImage():
            image = QImage(mime.imageData())
            if not image.isNull():
                self.canvas.set_floating_image(QPixmap.fromImage(image))
                return
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if path:
                    self._insert_image_path(path)
                    return

    def _insert_file(self):
        filters = t(
            "PDF và ảnh (*.pdf *.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;"
            "PDF Files (*.pdf);;"
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;"
            "All Files (*)"
        )
        path, _ = QFileDialog.getOpenFileName(self, t("Chèn"), "", filters)
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if suffix == ".pdf":
            self._import_pdf_path(path)
            return
        self._insert_image_path(path)

    def _insert_image(self):
        filters = "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;All Files (*)"
        path, _ = QFileDialog.getOpenFileName(self, "ជ្រើសរើសរូបភាព", "", filters)
        if not path:
            return
        self._insert_image_path(path)

    def _insert_image_path(self, path: str):
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = reader.read()
        if not img.isNull():
            self.canvas.insert_image_pixmap(QPixmap.fromImage(img))

    def _export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, t("Lưu PDF"), "", "PDF Files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        writer = QPdfWriter(path)
        writer.setResolution(300)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageOrientation(QPageLayout.Orientation.Landscape)
        painter = QPainter(writer)
        for i, slide in enumerate(self.canvas._slides):
            if i > 0:
                writer.newPage()
            rect = writer.pageLayout().paintRectPixels(writer.resolution())
            self.canvas.render_slide(painter, rect, slide)
        painter.end()

    def _export_selection(self):
        """Export current selection region as PNG / PDF / clipboard (Ctrl+E)."""
        pix = self.canvas.sel_pixmap_for_export()
        if pix.isNull():
            return
        from dialogs.export_selection_dialog import ExportSelectionDialog
        dlg = ExportSelectionDialog(pix, self)
        dlg.exec()

    def _export_selection_as_png(self, pix: QPixmap):
        path, _ = QFileDialog.getSaveFileName(self, t("Lưu PNG"), "", "PNG Files (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if pix.save(path, "PNG"):
            QToolTip.showText(QCursor.pos(), t("✔ Đã xuất PNG: {path}", path=path), self.canvas, QRect(), 4000)
            return
        QMessageBox.critical(self, t("Lỗi"), t("Không thể lưu file PNG."))

    def _export_selection_copy_png(self, pix: QPixmap):
        """Copy selection as PNG directly to clipboard."""
        image = QImage(pix.size(), QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(0, 0, pix)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        png_data = buffer.data()
        buffer.close()
        mime = QMimeData()
        mime.setImageData(image)
        mime.setData("image/png", png_data)
        QApplication.clipboard().setMimeData(mime)
        QToolTip.showText(QCursor.pos(), t("✔ Đã sao chép ảnh PNG vào clipboard."), self.canvas, QRect(), 3000)

    def _export_selection_as_pdf(self, pix: QPixmap):
        path, _ = QFileDialog.getSaveFileName(self, t("Lưu PDF"), "", "PDF Files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        dpi = 150
        w_mm = (pix.width() / dpi) * 25.4
        h_mm = (pix.height() / dpi) * 25.4
        writer = QPdfWriter(path)
        writer.setResolution(dpi)
        writer.setPageSize(QPageSize(QSizeF(w_mm, h_mm), QPageSize.Unit.Millimeter))
        writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
        painter = QPainter(writer)
        rect = writer.pageLayout().paintRectPixels(writer.resolution())
        painter.drawPixmap(rect, pix)
        painter.end()
        QToolTip.showText(QCursor.pos(), t("✔ Đã xuất PDF: {path}", path=path), self.canvas, QRect(), 4000)

    def _import_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, t("Nhập PDF"), "", "PDF Files (*.pdf)")
        if not path:
            return
        self._import_pdf_path(path)

    def _import_pdf_path(self, path: str):
        pass

    def _open_settings(self):
        BoardSettingsDialog(self.canvas, self, on_reset=self._reset_to_defaults).exec()

    def _login_google(self):
        from core.auth import is_logged_in, login_with_google, logout
        if is_logged_in():
            choice = QMessageBox.question(
                self,
                t("Đăng xuất"),
                t("Bạn đã đăng nhập Google. Đăng xuất khỏi tài khoản hiện tại?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice == QMessageBox.StandardButton.Yes:
                logout()
                self.statusBar().showMessage(t("Đã đăng xuất. Ứng dụng sẽ đóng."), 5000)
                QMessageBox.information(self, t("Đã đăng xuất"), t("Bạn đã đăng xuất. Vui lòng đăng nhập lại ở lần mở ứng dụng kế tiếp."))
                QApplication.quit()
            return
        try:
            self.statusBar().showMessage(t("Đang mở trình duyệt để đăng nhập Google..."), 5000)
            QApplication.processEvents()
            id_token, _creds = login_with_google()
            if id_token:
                self.statusBar().showMessage(t("Đăng nhập Google thành công!"), 5000)
                QMessageBox.information(self, t("Thành công"), t("Đã đăng nhập Google thành công và lưu Refresh Token."))
            else:
                self.statusBar().showMessage(t("Đăng nhập bị hủy hoặc thất bại."), 5000)
        except Exception as e:
            QMessageBox.critical(self, t("Lỗi đăng nhập"), t("Không thể đăng nhập Google:\n{error}", error=e))
            self.statusBar().showMessage(t("Lỗi đăng nhập Google."), 5000)

    def _reset_to_defaults(self):
        """Reset entire application to initial state: 2 group-1 pens, 1 group-2 pen, 1 highlight."""
        DEFAULT_PENS = [
            {"color": QColor(Qt.GlobalColor.black), "width": 3, "opacity": 100, "style_idx": 0},
            {"color": QColor("#2563eb"), "width": 3, "opacity": 100, "style_idx": 0},
        ]
        DEFAULT_PENS2 = [
            {"color": QColor("#e11d48"), "width": 3, "opacity": 100, "style_idx": 0},
        ]
        DEFAULT_HIGHLIGHTS = [
            {"color": QColor("#eab308"), "width": 30, "opacity": 50},
        ]
        while len(self._pen_buttons) > len(DEFAULT_PENS):
            btn = self._pen_buttons.pop()
            btn.setParent(None)
            btn.deleteLater()
        while len(getattr(self, "_pen2_buttons", [])) > len(DEFAULT_PENS2):
            btn = self._pen2_buttons.pop()
            btn.setParent(None)
            btn.deleteLater()
        while len(self._highlight_buttons) > len(DEFAULT_HIGHLIGHTS):
            btn = self._highlight_buttons.pop()
            btn.setParent(None)
            btn.deleteLater()
        self._pen_slots = [self._copy_slot(s) for s in DEFAULT_PENS]
        self._pen2_slots = [self._copy_slot(s) for s in DEFAULT_PENS2]
        self._highlight_slots = [self._copy_slot(s) for s in DEFAULT_HIGHLIGHTS]
        self._active_pen_slot = 0
        self._active_pen2_slot = 0
        self._active_highlight_slot = 0
        if self._pen_buttons:
            self._activate_pen_slot(0)
        self._refresh_toolbar_overflow()
        self._queue_toolbar_overflow_refresh()

    def _enforce_plan_restricted_settings(self):
        if getattr(self, "is_pro", lambda: False)():
            return
        self.canvas.texstudio_layout_mode = "inline"
        self.canvas.editable_text_mode = False
        apply_type_settings = getattr(self.canvas, "apply_texstudio_type_settings", None)
        if callable(apply_type_settings):
            apply_type_settings()
