"""
models/elements.py
Typed canvas element dataclasses for the Full Object Model.

Every element drawn on a slide is one of:
  StrokeElement       — a brush/pen/highlight/eraser path
  TextElement         — a rendered markdown/LaTeX text block
  ImageElement        — a pasted or stamped raster image
  PythonFigureElement — a code-generated figure (TikZ or edraw backend)

CanvasElement is the union type used throughout the app.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal, Union

from PyQt6.QtCore import QPointF, QSizeF
from PyQt6.QtGui import QColor, QPainterPath, QPixmap


@dataclass
class StrokeElement:
    """A brush/pen/highlight/eraser stroke path."""
    kind: Literal["stroke"] = "stroke"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    path: QPainterPath = field(default_factory=QPainterPath)
    color: QColor = field(default_factory=lambda: QColor("black"))
    width: float = 3.0
    mode: str = "freehand"
    segments: list = field(default_factory=list)

    @staticmethod
    def make(
        path: QPainterPath,
        color: QColor,
        width: float,
        mode: str,
        segments: list | None = None,
    ) -> StrokeElement:
        return StrokeElement(
            kind="stroke",
            id=str(uuid.uuid4()),
            path=path,
            color=color,
            width=width,
            mode=mode,
            segments=segments or [],
        )


@dataclass
class TextElement:
    """A rendered markdown/LaTeX text block."""
    kind: Literal["text"] = "text"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    markdown: str = ""
    anchor: QPointF = field(default_factory=QPointF)
    font_size: int = 24
    color: QColor = field(default_factory=lambda: QColor("black"))
    opacity: int = 100
    _pixmap_cache: QPixmap | None = field(default=None, init=False, repr=False)

    @staticmethod
    def make(
        markdown: str,
        anchor: QPointF,
        font_size: int,
        color: QColor,
        opacity: int = 100,
    ) -> TextElement:
        return TextElement(
            kind="text",
            id=str(uuid.uuid4()),
            markdown=markdown,
            anchor=anchor,
            font_size=font_size,
            color=color,
            opacity=opacity,
        )

    def invalidate_cache(self) -> None:
        self._pixmap_cache = None


@dataclass
class ImageElement:
    """A pasted or stamped raster image."""
    kind: Literal["image"] = "image"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: QPixmap = field(default_factory=QPixmap)
    pos: QPointF = field(default_factory=QPointF)
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0

    @staticmethod
    def make(
        source: QPixmap,
        pos: QPointF,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        rotation: float = 0.0,
    ) -> ImageElement:
        return ImageElement(
            kind="image",
            id=str(uuid.uuid4()),
            source=source,
            pos=pos,
            scale_x=scale_x,
            scale_y=scale_y,
            rotation=rotation,
        )


@dataclass
class PythonFigureElement:
    """A figure produced by running user-authored Python code through a backend.

    The code is recompiled on demand; rendered output is cached in `_pixmap_cache`
    until any of (code, backend, params, target size) changes.  Cache fields are
    deliberately excluded from undo snapshots so an undone-then-redone figure is
    re-rendered freshly rather than re-using a possibly stale QPixmap.
    """

    kind: Literal["python_figure"] = "python_figure"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    code: str = ""
    backend: str = "edraw"
    params: dict[str, float] = field(default_factory=dict)
    param_specs: dict[str, dict] = field(default_factory=dict)
    logical_size: QSizeF = field(default_factory=lambda: QSizeF(400, 300))
    pos: QPointF = field(default_factory=QPointF)
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    opacity: int = 100
    _pixmap_cache: QPixmap | None = field(default=None, init=False, repr=False)
    _cache_key: tuple | None = field(default=None, init=False, repr=False)
    _compiled: object | None = field(default=None, init=False, repr=False)
    _compile_error: str | None = field(default=None, init=False, repr=False)

    @staticmethod
    def make(
        code: str,
        backend: str,
        params: dict,
        param_specs: dict,
        logical_size: QSizeF,
        pos: QPointF,
        *,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        rotation: float = 0.0,
        opacity: int = 100,
    ) -> PythonFigureElement:
        return PythonFigureElement(
            kind="python_figure",
            id=str(uuid.uuid4()),
            code=code,
            backend=backend,
            params=dict(params),
            param_specs=dict(param_specs),
            logical_size=QSizeF(logical_size),
            pos=QPointF(pos),
            scale_x=scale_x,
            scale_y=scale_y,
            rotation=rotation,
            opacity=opacity,
        )

    def invalidate_cache(self) -> None:
        self._pixmap_cache = None
        self._cache_key = None


CanvasElement = Union[StrokeElement, TextElement, ImageElement, PythonFigureElement]


def _color_to_dict(c: QColor) -> dict:
    return {"r": c.red(), "g": c.green(), "b": c.blue(), "a": c.alpha()}


def _color_from_dict(d: dict) -> QColor:
    return QColor(d["r"], d["g"], d["b"], d["a"])


def _pointf_to_dict(p: QPointF) -> dict:
    return {"x": p.x(), "y": p.y()}


def _pointf_from_dict(d: dict) -> QPointF:
    return QPointF(d["x"], d["y"])


def element_to_dict(el: CanvasElement) -> dict:
    """Convert a CanvasElement to a JSON-serialisable dict (no QObjects)."""
    if el.kind == "stroke":
        return {
            "kind": "stroke",
            "id": el.id,
            "color": _color_to_dict(el.color),
            "width": el.width,
            "mode": el.mode,
            "_path_ref": id(el.path),
        }
    if el.kind == "text":
        return {
            "kind": "text",
            "id": el.id,
            "markdown": el.markdown,
            "anchor": _pointf_to_dict(el.anchor),
            "font_size": el.font_size,
            "color": _color_to_dict(el.color),
            "opacity": el.opacity,
        }
    if el.kind == "image":
        return {
            "kind": "image",
            "id": el.id,
            "pos": _pointf_to_dict(el.pos),
            "scale_x": el.scale_x,
            "scale_y": el.scale_y,
            "rotation": el.rotation,
        }
    if el.kind == "python_figure":
        return {
            "kind": "python_figure",
            "id": el.id,
            "code": el.code,
            "backend": el.backend,
            "params": dict(el.params),
            "param_specs": dict(el.param_specs),
            "logical_size": {
                "w": el.logical_size.width(),
                "h": el.logical_size.height(),
            },
            "pos": _pointf_to_dict(el.pos),
            "scale_x": el.scale_x,
            "scale_y": el.scale_y,
            "rotation": el.rotation,
            "opacity": el.opacity,
        }
    raise ValueError(f"Unknown element kind: {el.kind!r}")


def deep_copy_elements(elements: list[CanvasElement]) -> list[CanvasElement]:
    """Return a shallow-copy list with each element replaced by a new instance.

    QPainterPath and QPixmap objects inside are shared (copy-on-write), so this
    is cheap but safe for snapshot purposes.
    """
    out = []
    for el in elements:
        if el.kind == "stroke":
            out.append(StrokeElement(
                kind="stroke",
                id=el.id,
                path=QPainterPath(el.path),
                color=QColor(el.color),
                width=el.width,
                mode=el.mode,
                segments=list(el.segments),
            ))
        elif el.kind == "text":
            out.append(TextElement(
                kind="text",
                id=el.id,
                markdown=el.markdown,
                anchor=QPointF(el.anchor),
                font_size=el.font_size,
                color=QColor(el.color),
                opacity=el.opacity,
            ))
        elif el.kind == "image":
            out.append(ImageElement(
                kind="image",
                id=el.id,
                source=el.source,
                pos=QPointF(el.pos),
                scale_x=el.scale_x,
                scale_y=el.scale_y,
                rotation=el.rotation,
            ))
        elif el.kind == "python_figure":
            out.append(PythonFigureElement(
                kind="python_figure",
                id=el.id,
                code=el.code,
                backend=el.backend,
                params=dict(el.params),
                param_specs=dict(el.param_specs),
                logical_size=QSizeF(el.logical_size),
                pos=QPointF(el.pos),
                scale_x=el.scale_x,
                scale_y=el.scale_y,
                rotation=el.rotation,
                opacity=el.opacity,
            ))
    return out
