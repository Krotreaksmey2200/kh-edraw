"""
ui/account_mixin.py
Avatar/account button for MainWindow + blinking update badge.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QToolButton

from core.i18n import t


class AccountMixin:
    """Google avatar + tooltip + disk cache + blinking update badge."""

    _update_available: bool = False
    _pending_release = None
    _blink_visible: bool = True
    _blink_timer: QTimer | None = None

    AVATAR_SIZE = 28

    def _build_account_button(self) -> QToolButton:
        """Standalone avatar button (not belonging to any tool group)."""
        self._update_available = False
        self._pending_release = None
        self._blink_visible = True
        self._blink_timer = None
        size = self.AVATAR_SIZE
        self.btn_account = QToolButton()
        self.btn_account.setIcon(self._create_avatar_icon(size))
        self.btn_account.setIconSize(QSize(size, size))
        self.btn_account.setFixedSize(size + 4, size + 4)
        self.btn_account.setAutoRaise(True)
        self.btn_account.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_account.setStyleSheet(
            f"QToolButton {{ padding:0; border:none; background:transparent; border-radius:{(size + 4) // 2}px; }}"
            " QToolButton:hover { background:#eef2ff; }"
        )
        self.btn_account.setToolTip(self._account_tooltip())
        self.btn_account.clicked.connect(self._on_account_clicked)
        return self.btn_account

    def _on_account_clicked(self):
        """Show update dialog if a new version is available, otherwise handle login/logout."""
        if self._update_available and self._pending_release:
            from dialogs.update_dialog import UpdateDialog
            dlg = UpdateDialog(self._pending_release, self)
            dlg.exec()
            return
        self._login_google()

    def _clear_update_badge(self):
        """Turn off badge and stop timer — used when 'Don't remind again' is chosen."""
        self._update_available = False
        self._pending_release = None
        self._blink_visible = True
        if self._blink_timer:
            self._blink_timer.stop()
            self._blink_timer = None
        self._refresh_account_button()

    def _set_update_available(self, release):
        """Call from main thread when UpdateChecker finds a new version."""
        self._update_available = True
        self._pending_release = release
        self._blink_visible = True
        btn = getattr(self, "btn_account", None)
        if btn and not self._blink_timer:
            self._blink_timer = QTimer(self)
            self._blink_timer.timeout.connect(self._blink_badge)
            self._blink_timer.start(800)
        self._refresh_account_button()

    def _blink_badge(self):
        """Toggle badge visibility and repaint icon."""
        self._blink_visible = not self._blink_visible
        btn = getattr(self, "btn_account", None)
        if btn:
            btn.setIcon(self._create_avatar_icon(self.AVATAR_SIZE))

    def _account_tooltip(self) -> str:
        if self._user_email:
            return t(
                "Tài khoản: {email}\nGói: {plan}\nNhấp để đăng xuất.",
                email=self._user_email,
                plan=self._user_plan,
            )
        return t("Đăng nhập / Đăng xuất Google")

    @staticmethod
    def _avatar_cache_path(uid=None) -> str:
        cache_dir = os.path.join(os.path.expanduser("~"), ".edraw", "avatars")
        os.makedirs(cache_dir, exist_ok=True)
        if not uid:
            uid = "anon"
        return os.path.join(cache_dir, f"{uid}.png")

    def _avatar_cache_keys(self) -> list[str]:
        keys = []
        for value in (self._user_uid, self._user_email):
            if value:
                value = value.strip()
                if value and value not in keys:
                    keys.append(value)
        if not keys:
            keys.append("anon")
        return keys

    def _load_cached_avatar_pixmap(self):
        for key in self._avatar_cache_keys():
            cache = self._avatar_cache_path(key)
            pix = QPixmap()
            if os.path.isfile(cache) and pix.load(cache):
                return pix
        return None

    def _load_user_avatar_pixmap(self):
        cached = self._load_cached_avatar_pixmap()
        if cached:
            return cached
        return None

    def _create_avatar_icon(self, size: int) -> QIcon:
        """Circular avatar: real photo → initials → silhouette. Red badge when update available."""
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        ring_w = max(2, int(size * 0.08))
        rect = QRectF(ring_w / 2, ring_w / 2, size - ring_w, size - ring_w)
        inner = rect.adjusted(ring_w / 2, ring_w / 2, -ring_w / 2, -ring_w / 2)
        path = QPainterPath()
        path.addEllipse(inner)
        p.save()
        p.setClipPath(path)
        avatar_pix = self._load_user_avatar_pixmap()
        if avatar_pix and not avatar_pix.isNull():
            p.drawPixmap(QRectF(inner), avatar_pix, QRectF(avatar_pix.rect()))
        else:
            bg = QLinearGradient(inner.topLeft(), inner.bottomRight())
            bg.setColorAt(0, QColor("#6366f1"))
            bg.setColorAt(1, QColor("#8b5cf6"))
            p.setBrush(bg)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(inner)
            p.setPen(QColor("#ffffff"))
            p.setFont(QFont("Arial", max(8, int(size * 0.38)), QFont.Weight.Bold))
            text = (self._user_email or "A")[0].upper()
            p.drawText(inner, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()
        p.setPen(QPen(QColor("#e2e8f0"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)
        p.end()
        from PyQt6.QtGui import QIcon as QIconReturn
        return QIconReturn(pix)

    def _draw_update_badge(self, p: QPainter, size: int):
        """Draw a red flame badge in the top-right corner of the avatar."""
        if not getattr(self, "_update_available", False):
            return
        if not getattr(self, "_blink_visible", True):
            return
        bd = max(16, int(size * 0.48))
        br = bd / 2
        bx = float(size - br - 1)
        by = float(br + 1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(bx - br - 1.5, by - br - 1.5, bd + 3, bd + 3))
        grad = QLinearGradient(bx, by - br, bx, by + br)
        grad.setColorAt(0, QColor("#dc2626"))
        grad.setColorAt(1, QColor("#f97316"))
        p.setBrush(grad)
        p.drawEllipse(QRectF(bx - br, by - br, bd, bd))
        clip = QPainterPath()
        clip.addEllipse(QRectF(bx - br, by - br, bd, bd))
        p.save()
        p.setClipPath(clip)
        fw = br * 0.68
        fh = br * 1.18
        flame = QPainterPath()
        flame.moveTo(bx, by - fh * 0.5)
        flame.cubicTo(bx + fw * 0.65, by - fh * 0.1, bx + fw * 0.6, by + fh * 0.3, bx, by + fh * 0.5)
        flame.cubicTo(bx - fw * 0.6, by + fh * 0.3, bx - fw * 0.65, by - fh * 0.1, bx, by - fh * 0.5)
        p.setBrush(QColor("#ffffff"))
        p.drawPath(flame)
        inner_r = br * 0.22
        inner_grad = QLinearGradient(bx, by - inner_r, bx, by + inner_r)
        inner_grad.setColorAt(0, QColor(255, 255, 255, 180))
        inner_grad.setColorAt(1, QColor(255, 220, 100, 80))
        p.setBrush(inner_grad)
        p.drawEllipse(QRectF(bx - inner_r, by - inner_r * 0.3, inner_r * 2, inner_r * 2))
        p.restore()

    def _refresh_account_button(self):
        """Redraw avatar + tooltip after plan/email/photo change."""
        btn = getattr(self, "btn_account", None)
        if btn:
            btn.setIcon(self._create_avatar_icon(self.AVATAR_SIZE))
            btn.setToolTip(self._account_tooltip())
