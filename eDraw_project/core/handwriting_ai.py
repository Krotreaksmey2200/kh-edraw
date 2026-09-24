"""Handwriting AI OCR integration via Google Gemini.

Processes canvas screenshots to extract and synthesize handwriting with
accurate formatting, MathJax equation support, and fallback image rendering.
"""

from __future__ import annotations

import base64
import html
import io
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QImage
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from core.i18n import t

logger = logging.getLogger(__name__)

_LOCAL_RENDER_SCALE = 1

_OCR_PROMPT = """You are an OCR and document analysis engine for a digital whiteboard.
Read the handwriting, math equations, diagrams, and text from the image.
Output ONLY a valid JSON object with the following schema:
{
  "main_text": "Full extracted text in reading order",
  "blocks": [
    {
      "text": "Extracted text or equation for this block",
      "x": 0.5,
      "y": 0.5,
      "w": 0.8,
      "h": 0.2,
      "kind": "text"
    }
  ],
  "labels": [
    {
      "text": "Label text",
      "x": 0.3,
      "y": 0.4
    }
  ]
}
Coordinates x, y, w, h are normalized between 0.0 and 1.0 relative to the image size.
x, y represent the center of the block.
Equations should be expressed in clean LaTeX notation.
Do not wrap output in markdown code fences. Output pure JSON only."""

_MATH_OPERATOR_RE = re.compile(
    r"[=+\-*/^_{}\\]|\\(?:frac|sqrt|sum|int|prod|alpha|beta|gamma|theta|pi|le|ge|ne|times|div|pm|cdot|infty)"
)
_MATH_FALLBACK_CHARS = set("+-=*/^_{}()[]|√∫∑∏≤≥≠±×÷·∞⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")

_SUPERSCRIPT_TO_TEX = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "⁺": "+", "⁻": "-", "⁼": "=", "⁽": "(", "⁾": ")",
    "ⁿ": "n", "ⁱ": "i",
}

_SUBSCRIPT_TO_TEX = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "₊": "+", "₋": "-", "₌": "=", "₍": "(", "₎": ")",
    "ₐ": "a", "ₑ": "e", "ₒ": "o", "ₓ": "x", "ₕ": "h",
    "ₖ": "k", "ₗ": "l", "ₘ": "m", "ₙ": "n", "ₚ": "p",
    "ₛ": "s", "ₜ": "t",
}

_SUPERSCRIPT_MAP = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
    "n": "ⁿ", "i": "ⁱ",
}

_SUBSCRIPT_MAP = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
    "a": "ₐ", "e": "ₑ", "o": "ₒ", "x": "ₓ", "h": "ₕ",
    "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ", "p": "ₚ",
    "s": "ₛ", "t": "ₜ",
}


@dataclass
class HandwritingLabel:
    text: str
    x: float
    y: float


@dataclass
class HandwritingBlock:
    text: str
    x: float
    y: float
    w: float
    h: float
    kind: str = "text"


@dataclass
class HandwritingContent:
    main_text: str = ""
    blocks: list[HandwritingBlock] = field(default_factory=list)
    labels: list[HandwritingLabel] = field(default_factory=list)


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def normalize_handwriting_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n\s+", "\n", cleaned)
    return cleaned.strip()


def _to_superscript(value: str) -> str:
    return "".join(_SUPERSCRIPT_MAP.get(c, c) for c in value)


def _to_subscript(value: str) -> str:
    return "".join(_SUBSCRIPT_MAP.get(c, c) for c in value)


def _repair_math_unicode(text: str) -> str:
    if not text:
        return ""
    repaired = text
    for k, v in [
        ("log_", "log"),
        ("lim_", "lim"),
        ("sin_", "sin"),
        ("cos_", "cos"),
        ("tan_", "tan"),
    ]:
        repaired = repaired.replace(k, v)
    return repaired


def _strip_response_fence(text: str) -> str:
    text = (text or "").strip()
    if "```" in text:
        match = re.search(r"```(?:json|latex)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
    return text



def _normalize_block_coords(blocks: list[HandwritingBlock]) -> list[HandwritingBlock]:
    normalized = []
    for b in blocks:
        normalized.append(
            HandwritingBlock(
                text=b.text,
                x=max(0.0, min(1.0, b.x)),
                y=max(0.0, min(1.0, b.y)),
                w=max(0.01, min(1.0, b.w)),
                h=max(0.01, min(1.0, b.h)),
                kind=b.kind,
            )
        )
    return normalized


def _block_edges(block: HandwritingBlock) -> tuple[float, float, float, float]:
    left = block.x - block.w / 2.0
    top = block.y - block.h / 2.0
    right = block.x + block.w / 2.0
    bottom = block.y + block.h / 2.0
    return (left, top, right, bottom)


def _fit_blocks_to_canvas(
    blocks: list[HandwritingBlock],
    width: int,
    height: int,
    padding_x: float = 0.02,
    padding_top: float = 0.02,
    padding_bottom: float = 0.02,
) -> list[HandwritingBlock]:
    """Scale OCR block layout up so generated handwriting uses the selected area."""
    visible = [block for block in blocks if normalize_handwriting_text(block.text)]
    if not visible:
        return blocks
    left = min(_block_edges(block)[0] for block in visible)
    top = min(_block_edges(block)[1] for block in visible)
    right = max(_block_edges(block)[2] for block in visible)
    bottom = max(_block_edges(block)[3] for block in visible)
    source_w = max(0.02, right - left)
    source_h = max(0.02, bottom - top)
    target_left = max(0.0, min(0.22, padding_x / max(1, width)))
    target_top = max(0.0, min(0.22, padding_top / max(1, height)))
    target_right = min(1.0, 1.0 - target_left)
    target_bottom = min(1.0, 1.0 - max(0.0, min(0.22, padding_bottom / max(1, height))))
    target_w = max(0.04, target_right - target_left)
    target_h = max(0.04, target_bottom - target_top)
    scale = min(target_w / source_w, target_h / source_h)
    if scale <= 0:
        return blocks
    fitted_w = source_w * scale
    fitted_h = source_h * scale
    offset_x = target_left + (target_w - fitted_w) / 2.0 - left * scale
    offset_y = target_top + (target_h - fitted_h) / 2.0 - top * scale
    fitted = []
    for block in blocks:
        block_left, block_top, block_right, block_bottom = _block_edges(block)
        new_left = offset_x + block_left * scale
        new_top = offset_y + block_top * scale
        new_right = offset_x + block_right * scale
        new_bottom = offset_y + block_bottom * scale
        fitted.append(
            HandwritingBlock(
                block.text,
                max(0.0, min(1.0, (new_left + new_right) / 2.0)),
                max(0.0, min(1.0, (new_top + new_bottom) / 2.0)),
                max(0.02, min(1.0, new_right - new_left)),
                max(0.02, min(1.0, new_bottom - new_top)),
                block.kind,
            )
        )
    return fitted


from core.handwriting_render import *
class HandwritingAIWorker(QObject):
    """Background worker for handwriting OCR via Gemini."""

    finished = pyqtSignal(object)  # HandwritingContent
    failed = pyqtSignal(str)

    def __init__(
        self,
        api_key: str,
        model: str,
        png_bytes: Any,
        log: Callable[[str], None] = print,
        parent: QObject | None = None,
        handwriting_font: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent)
        from core.gemini_models import ensure_png_bytes
        self.api_key = api_key
        self.model = model
        self.png_bytes = ensure_png_bytes(png_bytes)
        self.log = log
        self.handwriting_font = handwriting_font

    def run(self) -> None:
        try:
            content = extract_text_with_gemini(
                api_key=self.api_key,
                model=self.model,
                png_bytes=self.png_bytes,
                log=self.log,
            )
            self.finished.emit(content)
        except Exception as exc:
            logger.exception("Handwriting AI failed")
            self.failed.emit(str(exc))


def start_handwriting_ai_worker(
    parent: QObject,
    worker: HandwritingAIWorker,
) -> QThread:
    """Move worker to a new QThread."""
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(thread.deleteLater)
    return thread

