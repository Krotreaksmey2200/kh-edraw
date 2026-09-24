"""Helpers vẽ icon vector cho toolbar (mixin của MainWindow)."""
from __future__ import annotations

import math
import os
import tempfile
from typing import Callable

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)


class IconsMixin:
    """Cung cấp các hàm tạo icon vector cho MainWindow."""

    ICON_PALETTE: dict[str, str] = {
        'pen': '#4f46e5',
        'fountain_pen': '#4f46e5',
        'highlight': '#eab308',
        'eraser': '#f59e0b',
        'clear': '#ef4444',
        'trash': '#ef4444',
        'line': '#475569',
        'arrow': '#475569',
        'arrow_double': '#475569',
        'midpoint': '#0f766e',
        'perpendicular_bisector': '#0f766e',
        'brace': '#0f766e',
        'bezier': '#0891b2',
        'circle': '#0891b2',
        'semicircle': '#0891b2',
        'ellipse': '#0891b2',
        'half_ellipse': '#0891b2',
        'parabola': '#0891b2',
        'triangle': '#0891b2',
        'rectangle': '#0891b2',
        'parallelogram': '#0891b2',
        'polygon': '#0891b2',
        'free_polygon': '#0891b2',
        'free_curve': '#0891b2',
        'type': '#2563eb',
        'prev': '#475569',
        'next': '#475569',
        'delete_page': '#ef4444',
        'save': '#10b981',
        'import': '#3b82f6',
        'gear': '#475569',
        'select_rect': '#8b5cf6',
        'select_free': '#8b5cf6',
        'ai': '#9333ea',
        'tikz_ai': '#0f766e',
        'tikz_figure': '#2563eb',
        'python_figure': '#2563eb',
        'figure_code': '#2563eb',
        'handwriting_ai': '#1d4ed8',
        'login': '#3b82f6',
        'zoom_in': '#475569',
        'zoom_out': '#475569',
        'zoom_fit': '#2563eb',
    }

    CYAN = QColor('#06b6d4')

    @staticmethod
    def _spin_arrow_pngs() -> tuple[str, str]:
        tmp = tempfile.gettempdir()
        paths = []
        for is_up in (True, False):
            pix = QPixmap(9, 9)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor('#334155'), 1.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            if is_up:
                path.moveTo(1.5, 5.5)
                path.lineTo(4.5, 3.5)
                path.lineTo(7.5, 5.5)
            else:
                path.moveTo(1.5, 3.5)
                path.lineTo(4.5, 5.5)
                path.lineTo(7.5, 3.5)
            p.drawPath(path)
            p.end()
            fname = os.path.join(tmp, f"edraw_spin_{'up' if is_up else 'dn'}.png")
            pix.save(fname, "PNG")
            paths.append(fname.replace("\\", "/"))
        return (paths[0], paths[1])

    def _icon_color(self, kind: str | None = None) -> QColor:
        if kind and kind in self.ICON_PALETTE:
            return QColor(self.ICON_PALETTE[kind])
        return QColor('#334155')

    def _create_shape_icon(
        self,
        kind: str,
        size: int = 24,
        *,
        color_override: QColor | None = None,
    ) -> QIcon:
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if kind != 'gear' and size != 24:
            scale_factor = size / 24
            p.scale(scale_factor, scale_factor)
        color = color_override if color_override is not None else self._icon_color(kind)
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        if kind == 'pen':
            p.translate(4, 18)
            p.rotate(-35)
            p.drawRoundedRect(QRectF(2, -4, 13, 5), 1.5, 1.5)
            poly = QPolygonF([
                QPointF(15, -4),
                QPointF(21, -1.5),
                QPointF(15, 1)])
            p.setBrush(color)
            p.drawPolygon(poly)
        elif kind == 'fountain_pen':
            p.translate(4, 18)
            p.rotate(-45)
            p.drawRoundedRect(QRectF(0, -3.5, 12, 7), 1.5, 1.5)
            nib_poly = QPolygonF([
                QPointF(12, -3.5),
                QPointF(20, 0),
                QPointF(12, 3.5)])
            p.setBrush(color)
            p.drawPolygon(nib_poly)
            p.setPen(QPen(QColor(255, 255, 255, 200), 1))
            p.drawLine(14, 0, 19, 0)
        elif kind == 'highlight':
            p.translate(4, 18)
            p.rotate(-35)
            p.drawRoundedRect(QRectF(2, -5, 14, 8), 2, 2)
            poly = QPolygonF([
                QPointF(16, -5),
                QPointF(20, -3),
                QPointF(20, 1),
                QPointF(16, 3)])
            p.setBrush(color)
            p.drawPolygon(poly)
            p.setBrush(Qt.GlobalColor.transparent)
            p.drawLine(8, -5, 8, 3)
        elif kind == 'eraser':
            p.translate(12, 12)
            p.rotate(-30)
            p.setBrush(QColor(245, 158, 11, 60))
            p.drawRoundedRect(QRectF(-7, -5, 14, 10), 2, 2)
            p.setBrush(Qt.GlobalColor.transparent)
            p.drawLine(-2, 5, 6, 5)
        elif kind in ('clear', 'trash'):
            p.drawLine(5, 7, 19, 7)
            p.drawLine(9, 7, 9, 5)
            p.drawLine(15, 7, 15, 5)
            p.drawRoundedRect(QRectF(7, 8, 10, 12), 1.5, 1.5)
            p.drawLine(10, 11, 10, 17)
            p.drawLine(14, 11, 14, 17)
        elif kind == 'line':
            p.drawLine(5, 18, 19, 6)
        elif kind == 'arrow':
            p.drawLine(4, 18, 18, 7)
            p.drawLine(18, 7, 13, 8)
            p.drawLine(18, 7, 17, 12)
        elif kind == 'arrow_double':
            p.drawLine(5, 17, 19, 7)
            p.drawLine(19, 7, 14, 8)
            p.drawLine(19, 7, 18, 12)
            p.drawLine(5, 17, 10, 16)
            p.drawLine(5, 17, 6, 12)
        elif kind == 'arrow_closed':
            p.drawLine(4, 18, 18, 7)
            poly = QPolygonF([
                QPointF(18, 7),
                QPointF(13, 8),
                QPointF(17, 12)])
            p.setBrush(color)
            p.drawPolygon(poly)
        elif kind == 'arrow_double_closed':
            p.drawLine(5, 17, 19, 7)
            poly1 = QPolygonF([
                QPointF(19, 7),
                QPointF(14, 8),
                QPointF(18, 12)])
            poly2 = QPolygonF([
                QPointF(5, 17),
                QPointF(10, 16),
                QPointF(6, 12)])
            p.setBrush(color)
            p.drawPolygon(poly1)
            p.drawPolygon(poly2)
        elif kind == 'arrow_stealth':
            p.drawLine(4, 18, 18, 7)
            poly = QPolygonF([
                QPointF(18, 7),
                QPointF(13, 8),
                QPointF(15, 10),
                QPointF(17, 12)])
            p.setBrush(color)
            p.drawPolygon(poly)
        elif kind == 'arrow_double_stealth':
            p.drawLine(5, 17, 19, 7)
            poly1 = QPolygonF([
                QPointF(19, 7),
                QPointF(14, 8),
                QPointF(16, 10),
                QPointF(18, 12)])
            poly2 = QPolygonF([
                QPointF(5, 17),
                QPointF(10, 16),
                QPointF(8, 14),
                QPointF(6, 12)])
            p.setBrush(color)
            p.drawPolygon(poly1)
            p.drawPolygon(poly2)
        elif kind == 'line_diamond':
            p.drawLine(5, 18, 19, 6)
            p.setBrush(Qt.GlobalColor.transparent)
            p.save()
            p.translate(5, 18)
            p.rotate(45)
            p.drawRect(QRectF(-2.5, -2.5, 5, 5))
            p.restore()
            p.save()
            p.translate(19, 6)
            p.rotate(45)
            p.drawRect(QRectF(-2.5, -2.5, 5, 5))
            p.restore()
        elif kind == 'line_dot':
            p.drawLine(5, 18, 19, 6)
            p.setBrush(Qt.GlobalColor.transparent)
            p.drawEllipse(QPointF(5, 18), 2.5, 2.5)
            p.drawEllipse(QPointF(19, 6), 2.5, 2.5)
        elif kind == 'line_dimension':
            p.drawLine(5, 18, 19, 6)
            p.drawLine(3, 16, 7, 20)
            p.drawLine(17, 4, 21, 8)
        elif kind == 'brace':
            path = QPainterPath(QPointF(4, 7))
            path.quadTo(QPointF(4, 12), QPointF(8, 12))
            path.lineTo(QPointF(10, 12))
            path.quadTo(QPointF(12, 12), QPointF(12, 16))
            path.quadTo(QPointF(12, 12), QPointF(14, 12))
            path.lineTo(QPointF(16, 12))
            path.quadTo(QPointF(20, 12), QPointF(20, 7))
            p.drawPath(path)
        elif kind == 'midpoint':
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#16a34a'))
            p.drawEllipse(QPointF(12, 12), 3, 3)
            p.setPen(QPen(QColor('#f8fafc'), 1.1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(12, 12), 3, 3)
        elif kind == 'perpendicular_bisector':
            p.drawLine(5, 16, 19, 8)
            p.drawLine(8, 5, 16, 19)
            p.setBrush(QColor('#14b8a6'))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(12, 12), 2.2, 2.2)
            p.setPen(QPen(color, 1.1))
            p.drawLine(QPointF(10.2, 9.1), QPointF(12.4, 10.4))
            p.drawLine(QPointF(12.4, 10.4), QPointF(11.1, 12.6))
        elif kind == 'bezier':
            path = QPainterPath(QPointF(4, 17))
            path.cubicTo(QPointF(8, 4), QPointF(16, 20), QPointF(20, 7))
            p.drawPath(path)
            p.setBrush(QColor('#6366f1'))
            p.setPen(Qt.PenStyle.NoPen)
            for pt in (QPointF(4, 17), QPointF(8, 4), QPointF(16, 20), QPointF(20, 7)):
                p.drawEllipse(pt, 1.6, 1.6)
        elif kind == 'circle':
            p.drawEllipse(QRectF(4.5, 4.5, 15, 15))
        elif kind == 'semicircle':
            path = QPainterPath()
            path.arcMoveTo(QRectF(4, 4, 16, 16), 180)
            path.arcTo(QRectF(4, 4, 16, 16), 180, -180)
            p.drawPath(path)
        elif kind == 'ellipse':
            p.drawEllipse(QRectF(3.5, 6.5, 17, 11))
        elif kind == 'half_ellipse':
            path = QPainterPath()
            path.arcMoveTo(QRectF(3, 6, 18, 12), 180)
            path.arcTo(QRectF(3, 6, 18, 12), 180, -180)
            p.drawPath(path)
        elif kind == 'parabola':
            path = QPainterPath(QPointF(4, 16))
            path.quadTo(QPointF(12, 2), QPointF(20, 16))
            p.drawPath(path)
            p.setBrush(QColor('#6366f1'))
            p.setPen(Qt.PenStyle.NoPen)
            for pt in (QPointF(4, 16), QPointF(12, 9), QPointF(20, 16)):
                p.drawEllipse(pt, 1.6, 1.6)
        elif kind == 'triangle':
            poly = QPolygonF([
                QPointF(12, 4),
                QPointF(20, 18),
                QPointF(4, 18)])
            p.drawPolygon(poly)
            p.setBrush(QColor('#6366f1'))
            p.setPen(Qt.PenStyle.NoPen)
            for pt in (QPointF(12, 4), QPointF(20, 18), QPointF(4, 18)):
                p.drawEllipse(pt, 1.6, 1.6)
        elif kind == 'rectangle':
            p.drawRect(QRectF(4, 6, 16, 12))
            p.setBrush(QColor('#6366f1'))
            p.setPen(Qt.PenStyle.NoPen)
            for pt in (QPointF(4, 6), QPointF(20, 6), QPointF(20, 18), QPointF(4, 18)):
                p.drawEllipse(pt, 1.6, 1.6)
        elif kind == 'parallelogram':
            poly = QPolygonF([
                QPointF(7, 6),
                QPointF(21, 6),
                QPointF(17, 18),
                QPointF(3, 18)])
            p.drawPolygon(poly)
            p.setBrush(QColor('#6366f1'))
            p.setPen(Qt.PenStyle.NoPen)
            for pt in (QPointF(7, 6), QPointF(21, 6), QPointF(17, 18), QPointF(3, 18)):
                p.drawEllipse(pt, 1.6, 1.6)
        elif kind == 'free_polygon':
            poly = QPolygonF([
                QPointF(5, 8),
                QPointF(12, 4),
                QPointF(20, 9),
                QPointF(17, 18),
                QPointF(7, 19)])
            p.drawPolygon(poly)
            p.setBrush(QColor('#6366f1'))
            p.setPen(Qt.PenStyle.NoPen)
            for pt in poly:
                p.drawEllipse(pt, 1.5, 1.5)
        elif kind == 'free_curve':
            path = QPainterPath(QPointF(4, 17))
            path.cubicTo(QPointF(7, 5), QPointF(12, 21), QPointF(15, 10))
            path.cubicTo(QPointF(17, 4), QPointF(21, 8), QPointF(20, 16))
            p.drawPath(path)
            p.setBrush(QColor('#6366f1'))
            p.setPen(Qt.PenStyle.NoPen)
            for pt in (QPointF(4, 17), QPointF(8, 9), QPointF(15, 10), QPointF(20, 16)):
                p.drawEllipse(pt, 1.5, 1.5)
        elif kind == 'type':
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            t_path = QPainterPath()
            t_path.addRect(QRectF(3.5, 3.5, 17, 3.5))
            t_path.addRect(QRectF(9.5, 7, 5, 11))
            p.drawPath(t_path)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(7, 20.5), QPointF(17, 20.5))
        elif kind == 'prev':
            pen.setWidthF(2.4)
            p.setPen(pen)
            p.drawLine(15, 5, 8, 12)
            p.drawLine(8, 12, 15, 19)
        elif kind == 'next':
            pen.setWidthF(2.4)
            p.setPen(pen)
            p.drawLine(9, 5, 16, 12)
            p.drawLine(16, 12, 9, 19)
        elif kind == 'save':
            p.setBrush(color)
            path = QPainterPath()
            path.moveTo(5, 5)
            path.lineTo(17, 5)
            path.lineTo(19, 7)
            path.lineTo(19, 19)
            path.lineTo(5, 19)
            path.closeSubpath()
            p.drawPath(path)
            p.setBrush(QColor('#ffffff'))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(QRectF(8, 5, 8, 5))
            p.drawRect(QRectF(8, 13, 8, 6))
            p.setPen(QPen(color, 1.2))
            p.setBrush(QColor('#ffffff'))
            p.drawRect(QRectF(13, 6, 2, 3))
        elif kind == 'import':
            p.setBrush(color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(QRectF(10, 5, 4, 7))
            poly = QPolygonF([
                QPointF(8, 12),
                QPointF(16, 12),
                QPointF(12, 16)])
            p.drawPolygon(poly)
            p.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.GlobalColor.transparent)
            p.drawPolyline(QPolygonF([
                QPointF(6, 14),
                QPointF(6, 19),
                QPointF(18, 19),
                QPointF(18, 14)]))
        elif kind in ('image', 'picture', 'photo'):
            p.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawRoundedRect(QRectF(3, 4, 18, 16), 2, 2)
            p.setBrush(color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(6, 7, 3.5, 3.5))
            p.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.GlobalColor.transparent)
            poly = QPolygonF([QPointF(4, 17), QPointF(9, 12), QPointF(13, 15), QPointF(16, 11), QPointF(20, 15)])
            p.drawPolyline(poly)
        elif kind == 'delete_page':
            p.setPen(QPen(QColor('#475569'), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.GlobalColor.transparent)
            p.drawRect(QRectF(6, 3, 12, 18))
            p.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(9, 9, 15, 15)
            p.drawLine(15, 9, 9, 15)
        elif kind == 'select_rect':
            dpen = QPen(color, 1.6, Qt.PenStyle.DashLine)
            dpen.setCapStyle(Qt.PenCapStyle.RoundCap)
            dpen.setDashPattern([
                4,
                2.5])
            p.setPen(dpen)
            p.drawRect(QRectF(4, 5, 16, 14))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            for cx, cy in ((4, 5), (12, 5), (20, 5), (4, 12), (20, 12), (4, 19), (12, 19), (20, 19)):
                p.drawEllipse(QPointF(cx, cy), 1.6, 1.6)
        elif kind == 'select_free':
            dpen = QPen(color, 1.6, Qt.PenStyle.DashLine)
            dpen.setCapStyle(Qt.PenCapStyle.RoundCap)
            dpen.setDashPattern([
                3.5,
                2.5])
            p.setPen(dpen)
            lasso = QPainterPath(QPointF(12, 4))
            lasso.lineTo(QPointF(19, 8))
            lasso.lineTo(QPointF(20, 15))
            lasso.lineTo(QPointF(15, 20))
            lasso.lineTo(QPointF(7, 20))
            lasso.lineTo(QPointF(4, 14))
            lasso.lineTo(QPointF(5, 7))
            lasso.closeSubpath()
            p.drawPath(lasso)
        elif kind == 'ai':
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            big = QPolygonF([
                QPointF(13, 3),
                QPointF(15, 11),
                QPointF(22, 13),
                QPointF(15, 15),
                QPointF(13, 22),
                QPointF(11, 15),
                QPointF(4, 13),
                QPointF(11, 11)])
            p.drawPolygon(big)
            small = QPolygonF([
                QPointF(5, 4),
                QPointF(6, 6.5),
                QPointF(8.5, 7.5),
                QPointF(6, 8.5),
                QPointF(5, 11),
                QPointF(4, 8.5),
                QPointF(1.5, 7.5),
                QPointF(4, 6.5)])
            p.setBrush(QColor('#c4b5fd'))
            p.drawPolygon(small)
        elif kind == 'tikz_ai':
            p.setPen(QPen(color, 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(QPointF(4, 16))
            path.cubicTo(QPointF(7, 4), QPointF(16, 21), QPointF(20, 8))
            p.drawPath(path)
            tp = QPen(QColor('#0f172a'), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(tp)
            p.drawLine(QPointF(7.5, 5.5), QPointF(16.5, 5.5))
            p.drawLine(QPointF(12, 5.5), QPointF(12, 13.5))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#14b8a6'))
            p.drawEllipse(QPointF(6, 17), 1.7, 1.7)
            p.drawEllipse(QPointF(20, 8), 1.7, 1.7)
        elif kind in ('figure_code', 'tikz_figure', 'python_figure'):
            axis_pen = QPen(QColor('#64748b'), 1.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
            p.setPen(axis_pen)
            p.drawLine(QPointF(4.5, 17), QPointF(20, 17))
            p.drawLine(QPointF(7, 20), QPointF(7, 4))
            curve_pen = QPen(color, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(curve_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(QPointF(5.5, 15.5))
            path.cubicTo(QPointF(8.5, 8), QPointF(13, 20), QPointF(19.5, 6.5))
            p.drawPath(path)
        elif kind == 'handwriting_ai':
            p.setPen(QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(QColor(219, 234, 254, 120))
            p.drawRoundedRect(QRectF(4, 5, 16, 14), 2, 2)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(7, 9), QPointF(17, 9))
            p.drawLine(QPointF(7, 13), QPointF(15, 13))
            script = QPainterPath(QPointF(7, 17))
            script.cubicTo(QPointF(9, 12), QPointF(12, 21), QPointF(15, 16))
            script.cubicTo(QPointF(16.5, 14.5), QPointF(18, 15.5), QPointF(19, 13))
            p.drawPath(script)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#a78bfa'))
            sparkle = QPolygonF([
                QPointF(18, 2.5),
                QPointF(19, 5.4),
                QPointF(21.5, 6.5),
                QPointF(19, 7.6),
                QPointF(18, 10.5),
                QPointF(17, 7.6),
                QPointF(14.5, 6.5),
                QPointF(17, 5.4)])
            p.drawPolygon(sparkle)
        elif kind == 'gear':
            cx = size / 2
            cy = size / 2
            r_out = size * 0.46
            r_in = size * 0.34
            teeth = 8
            total_pts = teeth * 4
            poly = QPolygonF()
            for i in range(total_pts):
                seg = i % 4
                angle = (i / total_pts) * math.pi * 2 - math.pi / 2
                r = r_out if seg in (1, 2) else r_in
                poly.append(QPointF(cx + r * math.cos(angle), cy + r * math.sin(angle)))
            p.setBrush(color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(poly)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.setBrush(QColor(0, 0, 0, 255))
            p.drawEllipse(QPointF(cx, cy), size * 0.15, size * 0.15)
        elif kind == 'plus':
            pen.setWidthF(2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            (cx, cy) = (12, 12)
            p.drawLine(QPointF(cx, 5.5), QPointF(cx, 18.5))
            p.drawLine(QPointF(5.5, cy), QPointF(18.5, cy))
        elif kind == 'zoom_in':
            pen.setWidthF(1.8)
            p.setPen(pen)
            p.setBrush(Qt.GlobalColor.transparent)
            p.drawEllipse(QRectF(3.5, 3.5, 11, 11))
            p.drawLine(QPointF(12.5, 12.5), QPointF(19.5, 19.5))
            p.drawLine(QPointF(6, 9), QPointF(12, 9))
            p.drawLine(QPointF(9, 6), QPointF(9, 12))
        elif kind == 'zoom_out':
            pen.setWidthF(1.8)
            p.setPen(pen)
            p.setBrush(Qt.GlobalColor.transparent)
            p.drawEllipse(QRectF(3.5, 3.5, 11, 11))
            p.drawLine(QPointF(12.5, 12.5), QPointF(19.5, 19.5))
            p.drawLine(QPointF(6, 9), QPointF(12, 9))
        elif kind == 'zoom_fit':
            pen.setWidthF(1.8)
            p.setPen(pen)
            p.setBrush(Qt.GlobalColor.transparent)
            # 4 corner brackets representing fit to window / viewport
            p.drawLine(QPointF(3, 8), QPointF(3, 3))
            p.drawLine(QPointF(3, 3), QPointF(8, 3))
            p.drawLine(QPointF(16, 3), QPointF(21, 3))
            p.drawLine(QPointF(21, 3), QPointF(21, 8))
            p.drawLine(QPointF(3, 16), QPointF(3, 21))
            p.drawLine(QPointF(3, 21), QPointF(8, 21))
            p.drawLine(QPointF(16, 21), QPointF(21, 21))
            p.drawLine(QPointF(21, 21), QPointF(21, 16))
            p.drawRoundedRect(QRectF(7, 7, 10, 10), 1.5, 1.5)
        elif kind == 'login':
            pen.setWidthF(1.8)
            p.setPen(pen)
            p.setBrush(Qt.GlobalColor.transparent)
            p.drawEllipse(QPointF(12, 8), 3.5, 3.5)
            path = QPainterPath()
            path.moveTo(5, 20)
            path.quadTo(12, 12, 19, 20)
            p.drawPath(path)
        elif kind == 'grid':
            pen.setWidthF(1.5)
            p.setPen(pen)
            p.setBrush(Qt.GlobalColor.transparent)
            p.drawRoundedRect(QRectF(3, 3, 18, 18), 2, 2)
            p.drawLine(QPointF(9, 3), QPointF(9, 21))
            p.drawLine(QPointF(15, 3), QPointF(15, 21))
            p.drawLine(QPointF(3, 9), QPointF(21, 9))
            p.drawLine(QPointF(3, 15), QPointF(21, 15))
        elif kind == 'key':
            pen.setWidthF(1.7)
            p.setPen(pen)
            p.setBrush(Qt.GlobalColor.transparent)
            p.drawEllipse(QPointF(8.5, 9), 4.5, 4.5)
            p.drawLine(QPointF(12, 12), QPointF(20.5, 20.5))
            p.drawLine(QPointF(16, 16), QPointF(18.5, 13.5))
            p.drawLine(QPointF(18.5, 18.5), QPointF(21, 16))
        elif kind == 'flag_vi':
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#da251d'))
            p.drawRect(QRectF(2, 5, 20, 14))
            p.setBrush(QColor('#ffcd00'))
            (cx, cy) = (12, 12)
            poly = QPolygonF()
            for i in range(10):
                angle = i * math.pi / 5 - math.pi / 2
                r = 4.5 if i % 2 == 0 else 1.7
                poly.append(QPointF(cx + r * math.cos(angle), cy + r * math.sin(angle)))
            p.drawPolygon(poly)
            p.setPen(QPen(QColor('#334155'), 0.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(2, 5, 20, 14))
        elif kind == 'flag_en':
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#012169'))
            p.drawRect(QRectF(2, 5, 20, 14))
            path = QPainterPath()
            path.addRect(QRectF(2, 5, 20, 14))
            p.setClipPath(path)
            p.setPen(QPen(QColor('#ffffff'), 2))
            p.drawLine(2, 5, 22, 19)
            p.drawLine(2, 19, 22, 5)
            p.setPen(QPen(QColor('#c8102e'), 1))
            p.drawLine(2, 5, 22, 19)
            p.drawLine(2, 19, 22, 5)
            p.setPen(QPen(QColor('#ffffff'), 3.5))
            p.drawLine(12, 5, 12, 19)
            p.drawLine(2, 12, 22, 12)
            p.setPen(QPen(QColor('#c8102e'), 2))
            p.drawLine(12, 5, 12, 19)
            p.drawLine(2, 12, 22, 12)
            p.setClipping(False)
            p.setPen(QPen(QColor('#334155'), 0.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(2, 5, 20, 14))
        p.end()
        return QIcon(pix)

    def _create_tool_preview_icon(
        self,
        fn: Callable[[list[QPointF]], QPainterPath],
        n_points: int,
        tool_type: str = 'curve',
        size: int = 24,
    ) -> QIcon:
        _FALLBACK = {
            'line': 'line',
            'geometry': 'midpoint',
            'polygon': 'triangle',
            'curve': 'bezier',
            'free': 'free_curve',
        }

        def _fallback() -> QIcon:
            return self._create_shape_icon(
                _FALLBACK.get(tool_type, 'bezier'),
                size,
                color_override=QColor('#9333ea'),
            )

        _PTS_CURVE = [
            QPointF(40.0, 280.0),
            QPointF(320.0, 80.0),
            QPointF(180.0, 50.0),
            QPointF(320.0, 180.0),
            QPointF(40.0, 180.0),
            QPointF(180.0, 310.0),
            QPointF(100.0, 100.0),
            QPointF(260.0, 100.0),
            QPointF(100.0, 260.0),
            QPointF(260.0, 260.0),
        ]
        _PTS_LINE = [
            QPointF(40.0, 280.0),
            QPointF(320.0, 80.0),
        ]
        _PTS_POLY = [
            QPointF(180.0, 40.0),
            QPointF(320.0, 260.0),
            QPointF(40.0, 260.0),
            QPointF(100.0, 100.0),
            QPointF(260.0, 100.0),
            QPointF(300.0, 200.0),
            QPointF(180.0, 310.0),
            QPointF(60.0, 200.0),
            QPointF(140.0, 170.0),
            QPointF(220.0, 170.0),
        ]
        _PTS_FREE = [
            QPointF(40.0, 230.0),
            QPointF(90.0, 80.0),
            QPointF(160.0, 160.0),
            QPointF(230.0, 60.0),
            QPointF(320.0, 220.0),
            QPointF(240.0, 300.0),
            QPointF(120.0, 280.0),
        ]

        if tool_type in ('line', 'geometry'):
            src = _PTS_LINE
        elif tool_type == 'polygon':
            src = _PTS_POLY
        elif tool_type == 'free':
            src = _PTS_FREE
        else:
            src = _PTS_CURVE

        point_count = 6 if int(n_points) == -1 else max(0, int(n_points))
        pts = src[:point_count]
        while len(pts) < point_count:
            pts = pts + [src[-1]]

        try:
            path = fn(pts)
        except Exception:
            return _fallback()

        if path is None or path.isEmpty():
            return _fallback()

        br = path.boundingRect()
        if not br.isValid() or (br.width() == 0 and br.height() == 0):
            return _fallback()

        margin = 3.0
        avail = max(1.0, float(size) - 2.0 * margin)
        w = max(br.width(), 0.1)
        h = max(br.height(), 0.1)
        scale = min(avail / w, avail / h)
        tc = size / 2.0

        from PyQt6.QtGui import QTransform
        tr = QTransform()
        tr.translate(tc, tc)
        tr.scale(scale, scale)
        tr.translate(-br.center().x(), -br.center().y())
        scaled = tr.map(path)

        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor('#9333ea'), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(scaled)
        painter.end()
        return QIcon(pix)

    def _create_stroke_icon(self, kind: str, size: QSize = QSize(52, 12)) -> QIcon:
        pix = QPixmap(size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor('#06b6d4'), 2.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if kind == 'dash':
            pen.setStyle(Qt.PenStyle.DashLine)
        elif kind == 'dot':
            pen.setStyle(Qt.PenStyle.DotLine)
        elif kind == 'dashdot':
            pen.setStyle(Qt.PenStyle.DashDotLine)
        elif kind == 'dashdotdot':
            pen.setStyle(Qt.PenStyle.DashDotDotLine)
        elif kind == 'short_dash':
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([4, 4])
        elif kind == 'long_dash':
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([14, 6])
        elif kind == 'sparse_dot':
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([1, 7])
        else:
            pen.setStyle(Qt.PenStyle.SolidLine)
        p.setPen(pen)
        p.drawLine(5, size.height() // 2, size.width() - 5, size.height() // 2)
        p.end()
        return QIcon(pix)

    @staticmethod
    def _pattern_star(cx: float, cy: float, outer: float, inner: float, points: int = 5) -> QPolygonF:
        poly = QPolygonF()
        for i in range(points * 2):
            angle = -math.pi / 2 + i * math.pi / points
            radius = outer if i % 2 == 0 else inner
            poly.append(QPointF(cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
        return poly

    def _create_fill_icon(
        self,
        style_key: str,
        color: QColor | None = None,
        size: QSize = QSize(30, 18),
    ) -> QIcon:
        if not color:
            color = QColor(QColor('#06b6d4'))
        if color.alpha() < 255:
            color = QColor(color.red(), color.green(), color.blue(), 210)
        pix = QPixmap(size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(2, 2, size.width() - 4, size.height() - 4)
        p.setPen(QPen(QColor('#334155'), 1))
        p.setBrush(QColor('#f8fafc'))
        p.drawRoundedRect(rect, 3, 3)
        p.setClipRect(rect.adjusted(1, 1, -1, -1))
        if style_key == 'solid':
            fill = QColor(color)
            fill.setAlpha(170)
            p.fillRect(rect, fill)
        else:
            pen = QPen(color, 1.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            (left, top, right, bottom) = (rect.left(), rect.top(), rect.right(), rect.bottom())
            mid_x = rect.center().x()
            mid_y = rect.center().y()
            if style_key == 'horizontal_lines':
                for y in (top + 4, mid_y, bottom - 4):
                    p.drawLine(QPointF(left, y), QPointF(right, y))
            elif style_key == 'vertical_lines':
                for x in (left + 5, mid_x, right - 5):
                    p.drawLine(QPointF(x, top), QPointF(x, bottom))
            elif style_key == 'north_east_lines':
                for x in range(-size.height(), size.width(), 8):
                    p.drawLine(QPointF(x, bottom), QPointF(x + size.height(), top))
            elif style_key == 'north_west_lines':
                for x in range(0, size.width() + size.height(), 8):
                    p.drawLine(QPointF(x, top), QPointF(x - size.height(), bottom))
            elif style_key == 'grid':
                for y in (top + 4, mid_y, bottom - 4):
                    p.drawLine(QPointF(left, y), QPointF(right, y))
                for x in (left + 5, mid_x, right - 5):
                    p.drawLine(QPointF(x, top), QPointF(x, bottom))
            elif style_key == 'crosshatch':
                for x in range(-size.height(), size.width(), 8):
                    p.drawLine(QPointF(x, bottom), QPointF(x + size.height(), top))
                for x in range(0, size.width() + size.height(), 8):
                    p.drawLine(QPointF(x, top), QPointF(x - size.height(), bottom))
            elif style_key == 'dots':
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color)
                for x in (left + 6, mid_x, right - 6):
                    p.drawEllipse(QPointF(x, mid_y), 1.5, 1.5)
            elif style_key == 'crosshatch_dots':
                p.drawLine(QPointF(left, bottom), QPointF(right, top))
                p.drawLine(QPointF(left, top), QPointF(right, bottom))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color)
                p.drawEllipse(rect.center(), 1.5, 1.5)
            elif style_key == 'fivepointed_stars':
                p.drawPolygon(self._pattern_star(mid_x, mid_y, 5, 2, 5))
            elif style_key == 'sixpointed_stars':
                p.drawPolygon(QPolygonF([
                    QPointF(mid_x, top + 3),
                    QPointF(right - 5, bottom - 3),
                    QPointF(left + 5, bottom - 3)]))
                p.drawPolygon(QPolygonF([
                    QPointF(mid_x, bottom - 3),
                    QPointF(left + 5, top + 3),
                    QPointF(right - 5, top + 3)]))
            elif style_key == 'bricks':
                for y in (top + rect.height() / 3, top + rect.height() * 2 / 3):
                    p.drawLine(QPointF(left, y), QPointF(right, y))
                for x, y0, y1 in ((mid_x, top, top + rect.height() / 3), (left + rect.width() / 4, top + rect.height() / 3, top + rect.height() * 2 / 3), (right - rect.width() / 4, top + rect.height() / 3, top + rect.height() * 2 / 3), (mid_x, top + rect.height() * 2 / 3, bottom)):
                    p.drawLine(QPointF(x, y0), QPointF(x, y1))
            elif style_key == 'checkerboard':
                p.setPen(Qt.PenStyle.NoPen)
                fill = QColor(color)
                fill.setAlpha(170)
                p.setBrush(fill)
                cell_w = rect.width() / 4
                cell_h = rect.height() / 2
                for row in range(2):
                    for col in range(4):
                        if not (row + col) % 2 == 0:
                            continue
                        p.drawRect(QRectF(left + col * cell_w, top + row * cell_h, cell_w, cell_h))
        p.setClipping(False)
        p.setPen(QPen(QColor('#334155'), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 3, 3)
        p.end()
        return QIcon(pix)

    def _color_icon(self, color: QColor, size: int = 24) -> QIcon:
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor('#111827'), 1.6))
        p.setBrush(color)
        p.drawRoundedRect(QRectF(4, 4, size - 8, size - 8), 5, 5)
        p.end()
        return QIcon(pix)
