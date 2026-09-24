"""Image loading and manipulation helpers for floating canvas elements.

Provides the ``ImageHandler`` class which manages a single floating image
(paste from clipboard / load from file) on the canvas — drag, scale, rotate,
crop, flip and stamp operations.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, QRect
from PyQt6.QtGui import QPainter, QPen, QPixmap, QTransform


class ImageHandler:
    """Manage a floating image on the canvas.

    Responsibilities:
    - Position, scale (uniform or non-uniform), rotate.
    - Drag by mouse interaction (press / move / release).
    - Edge-based cropping and edge-based scaling.
    - Bounding-rect calculation for dirty-region repaints.
    - Stamp (composite) the floating image into the target pixmap.
    """

    def __init__(self) -> None:
        self.image: QPixmap | None = None
        self.pos: QPointF = QPointF(50, 50)
        self.scale_x: float = 1.0
        self.scale_y: float = 1.0
        self.rotation: float = 0.0
        self._source_image: QPixmap | None = None
        self._source_crop_rect: QRect = QRect()
        self._dragging: bool = False
        self._drag_offset: QPointF = QPointF()

    @property
    def active(self) -> bool:
        return self.image is not None

    # ------------------------------------------------------------------
    # Setup / Teardown
    # ------------------------------------------------------------------

    def set_image(self, pixmap: QPixmap) -> None:
        self.image = pixmap
        self._source_image = pixmap
        self._source_crop_rect = pixmap.rect()
        self.pos = QPointF(50, 50)
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.rotation = 0.0
        self._dragging = False
        self._drag_offset = QPointF()

    def clear(self) -> None:
        self.image = None
        self._source_image = None
        self._dragging = False
        self._drag_offset = QPointF()

    # ------------------------------------------------------------------
    # Flip
    # ------------------------------------------------------------------

    def flip(self, horizontal: bool = True, anchor: QPointF | None = None) -> None:
        """Flip the image horizontally or vertically around *anchor*."""
        if not self.active:
            return
        center = anchor or self._center()
        if self.image is None:
            return
        if horizontal:
            self.scale_x = -self.scale_x
        else:
            self.scale_y = -self.scale_y
        self._set_center(center)

    # ------------------------------------------------------------------
    # Transform helpers
    # ------------------------------------------------------------------

    def _transform(self) -> QTransform:
        if not self.active:
            return QTransform()
        assert self.image is not None
        w = self.image.width() * self.scale_x
        h = self.image.height() * self.scale_y
        t = QTransform()
        t.translate(self.pos.x(), self.pos.y())
        t.translate(w / 2, h / 2)
        t.rotate(self.rotation)
        t.translate(-w / 2, -h / 2)
        t.scale(self.scale_x, self.scale_y)
        return t

    def bounding_rect(self) -> QRectF:
        if not self.active:
            return QRectF()
        assert self.image is not None
        rect = QRectF(0, 0, self.image.width(), self.image.height())
        return self._transform().mapRect(rect)

    def _center(self) -> QPointF:
        if not self.active:
            return QPointF()
        assert self.image is not None
        return self._transform().map(
            QPointF(self.image.width() / 2, self.image.height() / 2)
        )

    def _set_center(self, center: QPointF) -> None:
        if not self.active:
            return
        self.pos = QPointF(0, 0)
        relative_center = self._center()
        self.pos = QPointF(
            center.x() - relative_center.x(),
            center.y() - relative_center.y(),
        )

    # ------------------------------------------------------------------
    # Rotation / Scaling
    # ------------------------------------------------------------------

    def rotate_around(self, anchor: QPointF, angle_delta: float) -> None:
        """Rotate around *anchor* by *angle_delta* degrees."""
        if not self.active:
            return
        old_center = self._center()
        rad = math.radians(angle_delta)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        dx = old_center.x() - anchor.x()
        dy = old_center.y() - anchor.y()
        new_center = QPointF(
            anchor.x() + dx * cos_a - dy * sin_a,
            anchor.y() + dx * sin_a + dy * cos_a,
        )
        self.rotation = (self.rotation + angle_delta) % 360
        self._set_center(new_center)

    def scale_around(self, anchor: QPointF, factor: float) -> None:
        """Scale around *anchor* by *factor* (clamped to [0.05, 8])."""
        if not self.active or factor <= 0:
            return
        old_center = self._center()
        min_scale = 0.05
        max_scale = 8.0
        if factor > 1:
            actual_factor = min(
                factor,
                max_scale / max(abs(self.scale_x), 0.001),
                max_scale / max(abs(self.scale_y), 0.001),
            )
        else:
            actual_factor = max(
                factor,
                min_scale / max(abs(self.scale_x), 0.001),
                min_scale / max(abs(self.scale_y), 0.001),
            )
        self.scale_x = max(min_scale, min(max_scale, self.scale_x * actual_factor))
        self.scale_y = max(min_scale, min(max_scale, self.scale_y * actual_factor))
        new_center = QPointF(
            anchor.x() + (old_center.x() - anchor.x()) * actual_factor,
            anchor.y() + (old_center.y() - anchor.y()) * actual_factor,
        )
        self._set_center(new_center)

    # ------------------------------------------------------------------
    # Hit testing
    # ------------------------------------------------------------------

    def contains(self, pos: QPointF) -> bool:
        if not self.active:
            return False
        try:
            inv, ok = self._transform().inverted()
            if not ok:
                return self.bounding_rect().contains(pos)
            local = inv.map(pos)
            assert self.image is not None
            return QRectF(0, 0, self.image.width(), self.image.height()).contains(local)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def on_press(
        self,
        pos: QPointF,
        button: Qt.MouseButton,
        alt_held: bool = False,
        shift_held: bool = False,
    ) -> bool:
        if not self.active:
            return False
        if button == Qt.MouseButton.LeftButton:
            if alt_held:
                # Start crop mode
                self._cropping = True
                self._crop_start_pos = pos
                self._original_transform = self._transform()
                self._crop_start_rect = QRect(self._source_crop_rect)
                self._crop_edges = self._detect_crop_edges(pos)
                return True
            if shift_held:
                # Start edge-scale mode
                self._shifting = True
                self._shift_start_pos = pos
                self._original_transform = self._transform()
                self._original_scale_x = self.scale_x
                self._original_scale_y = self.scale_y
                self._scale_edges = self._detect_scale_edges(pos)
                return True
            # Start drag
            center = self._center()
            self._dragging = True
            self._drag_offset = QPointF(pos.x() - center.x(), pos.y() - center.y())
            return True
        return False

    def on_move(
        self,
        pos: QPointF,
        alt_held: bool = False,
        shift_held: bool = False,
    ) -> bool:
        if not self.active:
            return False

        # Crop mode
        if getattr(self, "_cropping", False):
            return self._handle_crop_move(pos)

        # Edge-scale mode
        if getattr(self, "_shifting", False):
            return self._handle_shift_move(pos)

        # Drag mode
        if not self._dragging:
            return False
        self.pos = QPointF(
            pos.x() - self._drag_offset.x(),
            pos.y() - self._drag_offset.y(),
        )
        return True

    def on_release(
        self,
        button: Qt.MouseButton,
        alt_held: bool = False,
        shift_held: bool = False,
    ) -> bool:
        if not self.active:
            return False
        if button == Qt.MouseButton.LeftButton:
            self._dragging = False
            if getattr(self, "_cropping", False):
                self._cropping = False
            if getattr(self, "_shifting", False):
                self._shifting = False
            return True
        return False

    def on_wheel(
        self,
        delta: float,
        shift_held: bool = False,
        anchor: QPointF | None = None,
    ) -> bool:
        if not self.active or delta == 0:
            return False
        zoom_factor = 1.0 + delta * 0.001
        self.scale_around(anchor or self._center(), zoom_factor)
        return True

    # ------------------------------------------------------------------
    # Edge detection for crop / scale
    # ------------------------------------------------------------------

    def _detect_crop_edges(self, pos: QPointF) -> dict[str, bool]:
        if self.image is None:
            return {}
        inv, ok = self._transform().inverted()
        if not ok:
            return {}
        local = inv.map(pos)
        w, h = self.image.width(), self.image.height()
        threshold = max(10, min(w, h) * 0.08)
        edges: dict[str, bool] = {}
        if local.x() < threshold:
            edges["left"] = True
        elif local.x() > w - threshold:
            edges["right"] = True
        if local.y() < threshold:
            edges["top"] = True
        elif local.y() > h - threshold:
            edges["bottom"] = True
        return edges

    def _detect_scale_edges(self, pos: QPointF) -> dict[str, bool]:
        if self.image is None:
            return {}
        inv, ok = self._transform().inverted()
        if not ok:
            return {}
        local = inv.map(pos)
        w, h = self.image.width(), self.image.height()
        threshold = max(10, min(w, h) * 0.12)
        edges: dict[str, bool] = {}
        if local.x() < threshold:
            edges["left"] = True
        elif local.x() > w - threshold:
            edges["right"] = True
        if local.y() < threshold:
            edges["top"] = True
        elif local.y() > h - threshold:
            edges["bottom"] = True
        return edges

    def _handle_crop_move(self, pos: QPointF) -> bool:
        delta = pos - self._crop_start_pos
        inv, ok = self._original_transform.inverted()
        if not ok:
            return False
        local_delta = inv.map(pos) - inv.map(self._crop_start_pos)
        dx = local_delta.x()
        dy = local_delta.y()
        cr = QRect(self._crop_start_rect)
        left, top, width, height = cr.x(), cr.y(), cr.width(), cr.height()
        c_left, c_top = 0, 0

        if self._crop_edges.get("left"):
            left += int(dx)
            width -= int(dx)
            c_left = int(dx)
        elif self._crop_edges.get("right"):
            width += int(dx)
        if self._crop_edges.get("top"):
            top += int(dy)
            height -= int(dy)
            c_top = int(dy)
        elif self._crop_edges.get("bottom"):
            height += int(dy)

        assert self._source_image is not None
        max_w = self._source_image.width()
        max_h = self._source_image.height()
        if width < 10:
            if self._crop_edges.get("left"):
                left -= 10 - width
                c_left -= 10 - width
            width = 10
        if height < 10:
            if self._crop_edges.get("top"):
                top -= 10 - height
                c_top -= 10 - height
            height = 10
        if left < 0:
            width += left
            c_left -= left
            left = 0
        if top < 0:
            height += top
            c_top -= top
            top = 0
        if left + width > max_w:
            width = max_w - left
        if top + height > max_h:
            height = max_h - top

        self._source_crop_rect = QRect(left, top, width, height)
        expected_new_tl_world = self._original_transform.map(QPointF(c_left, c_top))
        assert self._source_image is not None
        self.image = self._source_image.copy(self._source_crop_rect)
        self.pos = QPointF(0, 0)
        t_new_relative = self._transform()
        actual_new_tl_world_relative = t_new_relative.map(QPointF(0, 0))
        self.pos = QPointF(
            expected_new_tl_world.x() - actual_new_tl_world_relative.x(),
            expected_new_tl_world.y() - actual_new_tl_world_relative.y(),
        )
        return True

    def _handle_shift_move(self, pos: QPointF) -> bool:
        inv, ok = self._original_transform.inverted()
        if not ok:
            return False
        local_delta = inv.map(pos) - inv.map(self._shift_start_pos)
        dx = local_delta.x()
        dy = local_delta.y()
        assert self.image is not None
        w = self.image.width()
        h = self.image.height()
        new_scale_x = self._original_scale_x
        new_scale_y = self._original_scale_y
        if self._scale_edges.get("left"):
            new_scale_x = self._original_scale_x - dx / w
        elif self._scale_edges.get("right"):
            new_scale_x = self._original_scale_x + dx / w
        if self._scale_edges.get("top"):
            new_scale_y = self._original_scale_y - dy / h
        elif self._scale_edges.get("bottom"):
            new_scale_y = self._original_scale_y + dy / h
        self.scale_x = max(0.05, new_scale_x)
        self.scale_y = max(0.05, new_scale_y)

        fixed_x = w if self._scale_edges.get("left") else 0
        fixed_y = h if self._scale_edges.get("top") else 0
        fixed_local_pt = QPointF(fixed_x, fixed_y)
        expected_fixed_world = self._original_transform.map(fixed_local_pt)
        self.pos = QPointF(0, 0)
        t_new_relative = self._transform()
        actual_fixed_world_relative = t_new_relative.map(fixed_local_pt)
        self.pos = QPointF(
            expected_fixed_world.x() - actual_fixed_world_relative.x(),
            expected_fixed_world.y() - actual_fixed_world_relative.y(),
        )
        return True

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, painter: QPainter, *, show_box: bool) -> None:
        if not self.active:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setTransform(self._transform(), combine=True)
        assert self.image is not None
        painter.drawPixmap(0, 0, self.image)
        if show_box:
            sx = max(abs(self.scale_x), 0.001)
            sy = max(abs(self.scale_y), 0.001)
            box_pen = QPen(
                Qt.GlobalColor.red,
                max(1, 2 / max(sx, sy)),
                Qt.PenStyle.DashLine,
            )
            painter.setPen(box_pen)
            painter.drawRect(0, 0, self.image.width(), self.image.height())
        painter.restore()

    def stamp(self, target_pixmap: QPixmap) -> None:
        """Composite the floating image into *target_pixmap* and clear."""
        if not self.active:
            return
        p = QPainter(target_pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.draw(p, show_box=False)
        p.end()
        self.clear()
