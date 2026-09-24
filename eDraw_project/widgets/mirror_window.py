"""Read-only mirror window for showing the live eDraw board on a second display."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import QMainWindow, QWidget

from widgets.canvas import Canvas


class MirrorCanvas(QWidget):
    """Paints a scaled, non-interactive copy of the source canvas viewport."""

    def __init__(self, source: Canvas, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source = source
        self.setMinimumSize(640, 360)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCursor(self._build_pen_hand_cursor())
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(16)
        self._update_timer.timeout.connect(self.update)
        source.view_changed.connect(self._schedule_update)

    def _schedule_update(self) -> None:
        if not self._update_timer.isActive():
            self._update_timer.start()

    @staticmethod
    def _draw_pen_hand_cursor(painter: QPainter, pos: QPointF, scale: float = 1.0) -> None:
        painter.save()
        painter.translate(pos)
        painter.scale(scale, scale)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        skin = QColor('#f4c7a1')
        skin_shadow = QColor('#d7956f')
        pen_color = QColor('#2563eb')
        pen_tip = QColor('#111827')
        painter.setPen(QPen(skin_shadow, 1.2))
        painter.setBrush(skin)
        painter.drawRoundedRect(QRectF(6, 10, 13, 12), 5, 5)
        finger_pen = QPen(skin_shadow, 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(finger_pen)
        painter.drawLine(QPointF(8, 12), QPointF(5, 6))
        painter.drawLine(QPointF(11, 11), QPointF(11, 4))
        painter.drawLine(QPointF(15, 12), QPointF(17, 6))
        thumb = QPainterPath(QPointF(7, 18))
        thumb.cubicTo(QPointF(2, 16), QPointF(1, 20), QPointF(6, 23))
        painter.setPen(QPen(skin_shadow, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(thumb)
        painter.setPen(QPen(pen_color, 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(18, 7), QPointF(27, 25))
        painter.setPen(QPen(QColor('#93c5fd'), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(17, 8), QPointF(25, 24))
        painter.setPen(QPen(pen_tip, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(25, 23), QPointF(29, 30))
        painter.restore()

    @classmethod
    def _build_pen_hand_cursor(cls) -> QCursor:
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        cls._draw_pen_hand_cursor(painter, QPointF(0, 0), 1)
        painter.end()
        return QCursor(pixmap, 4, 4)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._source.board_color)
        source_size = self._source.size()
        if source_size.width() <= 0 or source_size.height() <= 0:
            return
        frame = QPixmap(source_size)
        frame.fill(self._source.board_color)
        frame_painter = QPainter(frame)
        self._source._draw_full(frame_painter, QRect(QPoint(0, 0), source_size))
        frame_painter.end()
        target_size = source_size.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRect(
            (self.width() - target_size.width()) // 2,
            (self.height() - target_size.height()) // 2,
            target_size.width(),
            target_size.height(),
        )
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(target, frame)
        cursor_pos = self._source.mirror_cursor_pos
        if not cursor_pos:
            return
        if not QRect(QPoint(0, 0), source_size).contains(cursor_pos.toPoint()):
            return
        scale = target.width() / max(source_size.width(), 1)
        mirrored_pos = QPointF(
            target.left() + cursor_pos.x() * scale,
            target.top() + cursor_pos.y() * scale,
        )
        self._draw_pen_hand_cursor(painter, mirrored_pos, max(0.8, min(1.6, scale * 1.15)))


class MirrorWindow(QMainWindow):
    """Top-level mirror window intended for moving to a second monitor."""

    def __init__(self, source: Canvas, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Mirror eDraw')
        self.setWindowIcon(source.window().windowIcon())
        self.setCentralWidget(MirrorCanvas(source, self))
        self._sc_fullscreen = QShortcut(QKeySequence('F11'), self, activated=self.toggle_fullscreen)
        self.resize(QSize(1280, 720))

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            return
        self.showFullScreen()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
            event.accept()
            return
        super().keyPressEvent(event)
