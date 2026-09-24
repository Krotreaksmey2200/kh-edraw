"""Màn hình khởi động (Splash Screen) cho eDraw."""
from __future__ import annotations

from pathlib import Path
import sys

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QApplication, QWidget

from core.i18n import t
from core.updater import current_version


def _resource_root() -> Path:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


VERSION_FILE = _resource_root() / 'version.txt'


def _app_version() -> str:
    v = current_version()
    if v:
        return v
    if VERSION_FILE.is_file():
        try:
            raw = VERSION_FILE.read_text(encoding='utf-8').strip()
            if raw:
                return raw
        except Exception:
            pass
    return '1.0.0'


APP_NAME = 'eDraw'
APP_VERSION = _app_version()
FEATURE_HIGHLIGHTS: list[tuple[str, str, str]] = [
    ('gemini', '#f59e0b', 'Gemini AI'),
    ('latex', '#38bdf8', 'LaTeX'),
    ('tikz', '#34d399', 'TikZ'),
    ('handwriting', '#a78bfa', 'Handwriting AI'),
]
AUTHOR_NAME = 'Nguyễn Hữu Điển'
SUPPORT_EMAIL = 'diennh@gmail.com'
FACEBOOK_TEXT = 'fb.com/groups/edraw'
COPYRIGHT = '© 2025 eDraw Team'


class SplashScreen(QWidget):
    """Splash frameless, nền trong suốt, có shadow + animated progress bar."""

    CARD_W = 560
    CARD_H = 370
    SHADOW_PAD = 28
    LOGO_SIZE = 84

    def __init__(self, app_icon: QIcon | None = None) -> None:
        super().__init__(
            None,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        if app_icon is not None and not app_icon.isNull():
            self.setWindowIcon(app_icon)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(
            self.CARD_W + self.SHADOW_PAD * 2,
            self.CARD_H + self.SHADOW_PAD * 2,
        )
        self._status_text = t('Đang khởi động…')
        self._tick = 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()
        self._center_on_screen()

    def show_message(self, text: str) -> None:
        self._status_text = text
        self.update()
        QApplication.processEvents()

    def finish(self, window: QWidget | None = None) -> None:
        self._timer.stop()
        self.close()
        if window is not None:
            window.raise_()
            window.activateWindow()

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.x() + (geo.width() - self.width()) // 2,
            geo.y() + (geo.height() - self.height()) // 2,
        )

    def _on_tick(self) -> None:
        self._tick = (self._tick + 1) % 1000
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        pad = float(self.SHADOW_PAD)
        card = QRectF(pad, pad, float(self.CARD_W), float(self.CARD_H))
        self._paint_shadow(p, card)
        self._paint_card(p, card)
        y = card.top() + 32.0
        y = self._paint_logo(p, card, y)
        y = self._paint_title(p, card, y)
        y = self._paint_version(p, card, y)
        y = self._paint_divider(p, card, y)
        y = self._paint_features(p, card, y)
        self._paint_contact(p, card, y)
        self._paint_progress(p, card)
        p.end()

    def _paint_shadow(self, p: QPainter, card: QRectF) -> None:

        p.setPen(Qt.PenStyle.NoPen)
        for i in range(1, 16):
            alpha = max(4, 42 - i * 2)
            offset = i * 1.2
            r = card.adjusted(-offset, -offset + 3, offset, offset + 7)
            p.setBrush(QColor(2, 6, 23, alpha))
            p.drawRoundedRect(r, 18, 18)

    def _paint_card(self, p: QPainter, card: QRectF) -> None:

        grad = QLinearGradient(card.topLeft(), card.bottomRight())
        grad.setColorAt(0, QColor('#12324a'))
        grad.setColorAt(0.58, QColor('#153955'))
        grad.setColorAt(1, QColor('#1d4d70'))
        p.setBrush(grad)
        p.setPen(QPen(QColor('#2d5a72'), 1))
        p.drawRoundedRect(card, 16, 16)

    def _paint_logo(self, p: QPainter, card: QRectF, y: float) -> float:

        cx = card.center().x()
        size = self.LOGO_SIZE
        rect = QRectF(cx - size / 2, y, size, size)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0, QColor('#29445a'))
        grad.setColorAt(1, QColor('#20384d'))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(rect, 18, 18)
        p.save()
        scale = size / 24
        p.translate(rect.left(), rect.top())
        p.scale(scale, scale)
        pen = QPen(QColor('#8bbcff'), 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(4, 17))
        path.cubicTo(QPointF(8, 4), QPointF(16, 20), QPointF(20, 7))
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#60a5fa'))
        for pt in (QPointF(4, 17), QPointF(8, 4), QPointF(16, 20), QPointF(20, 7)):
            p.drawEllipse(pt, 1.4, 1.4)
        p.restore()
        return rect.bottom()

    def _paint_title(self, p: QPainter, card: QRectF, y: float) -> float:

        f = QFont('Segoe UI', 24, QFont.Weight.Bold)
        f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        p.setFont(f)
        p.setPen(QColor('#ffffff'))
        rect = QRectF(card.left(), y, card.width(), 36)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, APP_NAME)
        return rect.bottom()

    def _paint_version(self, p: QPainter, card: QRectF, y: float) -> float:

        f = QFont('Segoe UI', 9)
        f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        p.setFont(f)
        p.setPen(QColor('#91b6cc'))
        rect = QRectF(card.left(), y, card.width(), 16)
        version_text = f'''v{APP_VERSION}''' if APP_VERSION else ''
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, version_text)
        return rect.bottom()

    def _paint_divider(self, p: QPainter, card: QRectF, y: float) -> float:

        margin_x = 60
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.drawLine(QPointF(card.left() + margin_x, y), QPointF(card.right() - margin_x, y))
        return y

    def _paint_features(self, p: QPainter, card: QRectF, y: float) -> float:
        font = QFont('Arial', 10, QFont.Weight.Medium)
        p.setFont(font)
        fm = p.fontMetrics()
        items = list(FEATURE_HIGHLIGHTS)
        gap = 18.0
        dot_r = 4.0
        dot_text_gap = 8.0
        widths = [fm.horizontalAdvance(label) for _, _, label in items]
        total_w = sum(widths) + (dot_r * 2 + dot_text_gap) * len(items) + gap * (len(items) - 1)
        x = card.center().x() - total_w / 2
        row_h = 22.0
        center_y = y + row_h / 2
        for (kind, color_hex, label), w in zip(items, widths):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color_hex))
            p.drawEllipse(QPointF(x + dot_r, center_y), dot_r, dot_r)
            p.setPen(QColor('#e6f3fb'))
            text_x = x + dot_r * 2 + dot_text_gap
            p.drawText(
                QRectF(text_x, y, w + 1, row_h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )
            x += dot_r * 2 + dot_text_gap + w + gap
        return y + row_h

    def _paint_contact(self, p: QPainter, card: QRectF, y: float) -> None:

        f = QFont('Segoe UI', 9)
        f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        p.setFont(f)
        p.setPen(QColor('#e6f3fb'))
        line1 = f'''{SUPPORT_EMAIL}  ·  {FACEBOOK_TEXT}'''
        p.drawText(QRectF(card.left(), y, card.width(), 16), Qt.AlignmentFlag.AlignCenter, line1)
        f2 = QFont('Segoe UI', 8)
        f2.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        p.setFont(f2)
        p.setPen(QColor('#91b6cc'))
        p.drawText(QRectF(card.left(), y + 18, card.width(), 14), Qt.AlignmentFlag.AlignCenter, COPYRIGHT)

    def _paint_progress(self, p: QPainter, card: QRectF) -> None:

        status_font = QFont('Segoe UI', 9)
        status_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        p.setFont(status_font)
        p.setPen(QColor('#b7d7e8'))
        status_rect = QRectF(card.left(), card.bottom() - 38, card.width(), 16)
        p.drawText(status_rect, Qt.AlignmentFlag.AlignCenter, self._status_text)
        bar_h = 3
        margin_x = 60
        bar = QRectF(card.left() + margin_x, card.bottom() - 18, card.width() - margin_x * 2, bar_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(bar, bar_h / 2, bar_h / 2)
        sweep_w = bar.width() * 0.28
        period = bar.width() + sweep_w
        phase = self._tick * 6 % period
        x_start = bar.left() + phase - sweep_w
        x_end = x_start + sweep_w
        clip_left = max(bar.left(), x_start)
        clip_right = min(bar.right(), x_end)
        if clip_right <= clip_left:
            return None
        sweep = QRectF(clip_left, bar.top(), clip_right - clip_left, bar_h)
        grad = QLinearGradient(sweep.left(), 0, sweep.right(), 0)
        grad.setColorAt(0, QColor('#22c55e'))
        grad.setColorAt(0.5, QColor('#2dd4bf'))
        grad.setColorAt(1, QColor('#38bdf8'))
        p.setBrush(grad)
        p.drawRoundedRect(sweep, bar_h / 2, bar_h / 2)
