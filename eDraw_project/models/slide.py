"""
models/slide.py
Manages one drawing page's data: elements list + undo/redo.

Full Object Model:
  elements        — list[CanvasElement], source of truth for all drawn objects
  _stroke_pixmap  — incremental rasterisation cache for StrokeElements only
  _history        — list of (elements snapshot, stroke_pixmap copy) pairs

The `pixmap` property returns _stroke_pixmap for backward-compat callers that
still read slide.pixmap (e.g. export, thumbnail).  canvas.py _draw_full()
composites _stroke_pixmap + TextElement/ImageElement overlays.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPixmap

from models.elements import CanvasElement, StrokeElement, deep_copy_elements

MAX_HISTORY = 40
_DIRTY = object()


class SlideModel:
    """One drawing page: typed element list + incremental stroke cache + undo/redo."""

    def __init__(self, width: int = 1080, height: int = 1528) -> None:
        h = max(height, 1)
        w = max(width, 1)
        self.width: int = w
        self.height: int = h
        self.elements: list[CanvasElement] = []
        self._stroke_pixmap = QPixmap(w, h)
        self._stroke_pixmap.fill(Qt.GlobalColor.transparent)
        self._history: list[tuple[list[CanvasElement], QPixmap]] = [
            ([], self._stroke_pixmap.copy())
        ]
        self._idx: int = 0

    def resize(self, width: int, height: int) -> None:
        w = max(width, 1)
        h = max(height, 1)
        if getattr(self, "width", 0) == w and getattr(self, "height", 0) == h:
            return
        self.width = w
        self.height = h
        new_pm = QPixmap(w, h)
        new_pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(new_pm)
        p.drawPixmap(0, 0, self._stroke_pixmap)
        p.end()
        self._stroke_pixmap = new_pm

    @property
    def pixmap(self) -> QPixmap:
        return self._stroke_pixmap

    @pixmap.setter
    def pixmap(self, value: QPixmap) -> None:
        self._stroke_pixmap = value

    def paint_stroke_onto_cache(self, paint_fn) -> None:
        """Call paint_fn(QPainter) to incrementally add a stroke to the cache.

        The painter is already begun on _stroke_pixmap; the caller should not
        call painter.begin/end.
        """
        p = QPainter(self._stroke_pixmap)
        try:
            paint_fn(p)
            p.end()
        except Exception:
            p.end()
            raise

    def rebuild_stroke_pixmap(self) -> None:
        """Re-rasterise all StrokeElements from scratch into _stroke_pixmap.

        Called after undo/redo or any operation that changes the stroke list.
        Importing canvas drawing logic here would create a circular dependency,
        so callers in canvas.py pass a render function via rebuild_stroke_pixmap_via().
        """
        self._stroke_pixmap.fill(Qt.GlobalColor.transparent)

    def rebuild_stroke_pixmap_via(self, render_fn) -> None:
        """Rebuild stroke pixmap using a caller-supplied render function.

        render_fn(pixmap: QPixmap, elements: list[CanvasElement]) -> None
        The render function should paint all strokes onto the given pixmap.
        """
        self._stroke_pixmap.fill(Qt.GlobalColor.transparent)
        render_fn(self._stroke_pixmap, self.elements)

    def save_state(self) -> None:
        """Snapshot current elements + stroke pixmap into history."""
        if self._idx < len(self._history) - 1:
            self._history = self._history[: self._idx + 1]
        snapshot = (
            deep_copy_elements(self.elements),
            self._stroke_pixmap.copy(),
        )
        self._history.append(snapshot)
        if len(self._history) > MAX_HISTORY:
            self._history.pop(0)
            self._idx = max(0, self._idx - 1)
        else:
            self._idx += 1

    def undo(self) -> bool:
        if self._idx > 0:
            els, pix = self._history[self._idx]
            self.elements = deep_copy_elements(els)
            self._stroke_pixmap = pix.copy()
            return True
        return False

    def redo(self) -> bool:
        if self._idx < len(self._history) - 1:
            els, pix = self._history[self._idx]
            self.elements = deep_copy_elements(els)
            self._stroke_pixmap = pix.copy()
            return True
        return False

    def add_element(self, el: CanvasElement) -> None:
        self.elements.append(el)

    def remove_element(self, element_id: str) -> bool:
        for i, el in enumerate(self.elements):
            if el.id == element_id:
                self.elements.pop(i)
                return True
        return False

    def find_element(self, element_id: str) -> CanvasElement | None:
        for el in self.elements:
            if el.id == element_id:
                return el
        return None

    def clear(self) -> None:
        self.elements.clear()
        self._stroke_pixmap.fill(Qt.GlobalColor.transparent)
        self.save_state()

    def expand_if_needed(self, width: int, height: int) -> bool:
        """Expand pixmap if canvas grows. Returns True if resized."""
        pix = self._stroke_pixmap
        if width <= pix.width() and height <= pix.height():
            return False
        new_w = max(width, pix.width())
        new_h = max(height, pix.height())
        new_pix = QPixmap(new_w, new_h)
        new_pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(new_pix)
        p.drawPixmap(0, 0, pix)
        p.end()
        self._stroke_pixmap = new_pix
        if self._history:
            els, _ = self._history[self._idx]
            self._history[self._idx] = (els, self._stroke_pixmap.copy())
        return True
