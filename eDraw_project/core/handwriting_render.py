"""Handwriting AI Rendering Engine."""
from __future__ import annotations
import base64
import html
import io
import json
import logging
import math
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from core.i18n import t
from core.handwriting_ai import (
    HandwritingBlock,
    HandwritingContent,
    HandwritingLabel,
    _SUPERSCRIPT_MAP,
    _SUBSCRIPT_MAP,
    _SUPERSCRIPT_TO_TEX,
    _SUBSCRIPT_TO_TEX,
    _MATH_OPERATOR_RE,
    _MATH_FALLBACK_CHARS,
    _LOCAL_RENDER_SCALE,
    _resource_root,
    normalize_handwriting_text,
    _to_superscript,
    _to_subscript,
    _repair_math_unicode,
    _fit_blocks_to_canvas,
)

logger = logging.getLogger(__name__)


def _merge_block_group(group: list[HandwritingBlock]) -> HandwritingBlock:
    if len(group) == 1:
        return group[0]
    sorted_group = sorted(group, key=lambda b: (b.x - b.w / 2.0))
    merged_text = " ".join(b.text.strip() for b in sorted_group if b.text.strip())
    left = min(_block_edges(b)[0] for b in sorted_group)
    top = min(_block_edges(b)[1] for b in sorted_group)
    right = max(_block_edges(b)[2] for b in sorted_group)
    bottom = max(_block_edges(b)[3] for b in sorted_group)
    return HandwritingBlock(
        text=merged_text,
        x=(left + right) / 2.0,
        y=(top + bottom) / 2.0,
        w=max(0.02, right - left),
        h=max(0.02, bottom - top),
        kind=group[0].kind,
    )


def _merge_inline_blocks(blocks: list[HandwritingBlock]) -> list[HandwritingBlock]:
    if len(blocks) <= 1:
        return blocks
    sorted_blocks = sorted(blocks, key=lambda b: (b.y, b.x))
    merged = []
    current_group = [sorted_blocks[0]]
    for next_block in sorted_blocks[1:]:
        prev_block = current_group[-1]
        prev_left, prev_top, prev_right, prev_bottom = _block_edges(prev_block)
        next_left, next_top, next_right, next_bottom = _block_edges(next_block)
        vertical_overlap = max(
            0.0, min(prev_bottom, next_bottom) - max(prev_top, next_top)
        )
        min_h = min(prev_block.h, next_block.h)
        horizontal_gap = next_left - prev_right
        if (
            vertical_overlap >= min_h * 0.45
            and -min_h * 0.25 <= horizontal_gap <= min_h * 1.6
            and prev_block.kind == next_block.kind
        ):
            current_group.append(next_block)
        else:
            merged.append(_merge_block_group(current_group))
            current_group = [next_block]
    if current_group:
        merged.append(_merge_block_group(current_group))
    return merged


def _block_has_system_marker(block: HandwritingBlock) -> bool:
    return _line_has_system_brace(block.text)


def _merge_system_block_group(group: list[HandwritingBlock]) -> HandwritingBlock:
    if len(group) == 1:
        return group[0]
    sorted_group = sorted(group, key=lambda b: b.y)
    merged_text = "\n".join(b.text.strip() for b in sorted_group if b.text.strip())
    left = min(_block_edges(b)[0] for b in sorted_group)
    top = min(_block_edges(b)[1] for b in sorted_group)
    right = max(_block_edges(b)[2] for b in sorted_group)
    bottom = max(_block_edges(b)[3] for b in sorted_group)
    return HandwritingBlock(
        text=merged_text,
        x=(left + right) / 2.0,
        y=(top + bottom) / 2.0,
        w=max(0.02, right - left),
        h=max(0.02, bottom - top),
        kind="system",
    )


def _merge_system_blocks(blocks: list[HandwritingBlock]) -> list[HandwritingBlock]:
    if len(blocks) <= 1:
        return blocks
    result = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if _block_has_system_marker(b):
            group = [b]
            j = i + 1
            while j < len(blocks) and _is_system_equation_line(blocks[j].text):
                group.append(blocks[j])
                j += 1
            if len(group) >= 2:
                result.append(_merge_system_block_group(group))
                i = j
                continue
        result.append(b)
        i += 1
    return result


def _append_integral_differential(block: HandwritingBlock, differential: HandwritingBlock) -> HandwritingBlock:
    left1, top1, right1, bottom1 = _block_edges(block)
    left2, top2, right2, bottom2 = _block_edges(differential)
    return HandwritingBlock(
        text=f"{block.text.strip()} {differential.text.strip()}",
        x=(min(left1, left2) + max(right1, right2)) / 2.0,
        y=(min(top1, top2) + max(bottom1, bottom2)) / 2.0,
        w=max(0.02, max(right1, right2) - min(left1, left2)),
        h=max(0.02, max(bottom1, bottom2) - min(top1, top2)),
        kind=block.kind,
    )


def _merge_integral_differential_blocks(blocks: list[HandwritingBlock]) -> list[HandwritingBlock]:
    if len(blocks) <= 1:
        return blocks
    merged = []
    skip_next = False
    for i in range(len(blocks)):
        if skip_next:
            skip_next = False
            continue
        curr = blocks[i]
        if i + 1 < len(blocks):
            nxt = blocks[i + 1]
            if _text_has_integral(curr.text) and _is_differential_text(nxt.text):
                merged.append(_append_integral_differential(curr, nxt))
                skip_next = True
                continue
        merged.append(curr)
    return merged


def _compact_ocr_coverage_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _blocks_miss_main_text(main_text: str, blocks: list[HandwritingBlock]) -> bool:
    main_compact = _compact_ocr_coverage_text(main_text)
    if not main_compact:
        return False
    blocks_compact = "".join(_compact_ocr_coverage_text(b.text) for b in blocks)
    return len(blocks_compact) < len(main_compact) * 0.65


def _parse_handwriting_content(raw_text: str) -> HandwritingContent:
    cleaned = _strip_response_fence(raw_text)
    try:
        data = json.loads(cleaned)
    except Exception:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
            except Exception:
                return HandwritingContent(main_text=cleaned)
        else:
            return HandwritingContent(main_text=cleaned)

    main_text = str(data.get("main_text") or "").strip()
    raw_blocks = data.get("blocks") or []
    blocks = []
    for item in raw_blocks:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            if text:
                blocks.append(
                    HandwritingBlock(
                        text=text,
                        x=float(item.get("x", 0.5)),
                        y=float(item.get("y", 0.5)),
                        w=float(item.get("w", 0.8)),
                        h=float(item.get("h", 0.1)),
                        kind=str(item.get("kind", "text")),
                    )
                )

    raw_labels = data.get("labels") or []
    labels = []
    for item in raw_labels:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            if text:
                labels.append(
                    HandwritingLabel(
                        text=text,
                        x=float(item.get("x", 0.5)),
                        y=float(item.get("y", 0.5)),
                    )
                )

    blocks = _normalize_block_coords(blocks)
    blocks = _merge_inline_blocks(blocks)
    blocks = _merge_system_blocks(blocks)
    blocks = _merge_integral_differential_blocks(blocks)

    if not blocks and main_text:
        blocks = [HandwritingBlock(text=main_text, x=0.5, y=0.5, w=0.9, h=0.8)]
    elif _blocks_miss_main_text(main_text, blocks):
        blocks = [HandwritingBlock(text=main_text, x=0.5, y=0.5, w=0.9, h=0.8)]

    return HandwritingContent(main_text=main_text, blocks=blocks, labels=labels)


def _is_math_text(text: str) -> bool:
    return bool(_MATH_OPERATOR_RE.search(text)) or any(c in _MATH_FALLBACK_CHARS for c in text)


def _normalize_handwriting_font_key(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _handwriting_font_candidates(root: Path, font_key: str | None = None) -> list[Path]:
    fonts_dir = root / "resources" / "fonts"
    candidates = []
    normalized_key = _normalize_handwriting_font_key(font_key)
    if normalized_key:
        for f in fonts_dir.glob("*.ttf"):
            if normalized_key in _normalize_handwriting_font_key(f.stem):
                candidates.append(f)
    candidates.extend(sorted(fonts_dir.glob("*.ttf")))
    return candidates


def _load_font(size: int, math: bool = False, handwriting_font: str | None = None) -> ImageFont.FreeTypeFont:
    root = _resource_root()
    candidates = _handwriting_font_candidates(root, handwriting_font)
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                continue
    try:
        return ImageFont.truetype("Arial", size=size)
    except Exception:
        return ImageFont.load_default()


def _load_math_symbol_font(size: int) -> ImageFont.FreeTypeFont:
    for name in ["DejaVuSans.ttf", "Arial.ttf"]:
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _advance_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return max(0, bbox[2])


def _draw_text_with_math_fallback(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    fill: Any = (0, 0, 0),
    font: ImageFont.FreeTypeFont | None = None,
) -> None:
    draw.text(xy, text, fill=fill, font=font)


def _font_face_css(handwriting_font: str | None = None) -> tuple[str, str]:
    family = "EDrawHandwriting"
    for font_path in _handwriting_font_candidates(_resource_root(), handwriting_font):
        if font_path.exists():
            uri = font_path.resolve().as_uri()
            css = (
                f"@font-face {{font-family:'{family}';"
                f"src:url('{uri}') format('truetype');"
                f"font-weight:400;font-style:normal;}}"
            )
            return (family, css)
    return ("Comic Sans MS", "")


def _mathjax_script_source() -> str:
    """Return the MathJax script tag for inline rendering."""
    return (
        '<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js">'
        "</script>"
    )


def _clean_math_token(token: str) -> str:
    return token.strip()


def _line_has_system_brace(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("{") or stripped.startswith("\\{")


def _strip_system_brace(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("\\{"):
        return stripped[2:].strip()
    if stripped.startswith("{"):
        return stripped[1:].strip()
    return stripped


def _is_system_equation_line(line: str) -> bool:
    core = _strip_system_brace(line)
    if not core:
        return False
    return bool(_MATH_OPERATOR_RE.search(core) or _should_render_math_group(core))


def _text_has_integral(text: str) -> bool:
    return "∫" in text or "\\int" in text


def _is_differential_text(text: str) -> bool:
    stripped = text.strip()
    return bool(re.fullmatch(r"d[a-zA-Z]", stripped))


def _looks_like_math_token(token: str) -> bool:
    stripped = token.strip()
    if not stripped:
        return False
    if _MATH_OPERATOR_RE.search(stripped):
        return True
    if any(c in _MATH_FALLBACK_CHARS for c in stripped):
        return True
    return False


def _continues_math_group(token: str) -> bool:
    stripped = token.strip()
    if not stripped:
        return False
    if _looks_like_math_token(stripped):
        return True
    if re.fullmatch(r"[A-Za-z0-9⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]+[)\\]}.,;]+", stripped):
        return True
    return False


def _should_render_math_group(group: str) -> bool:
    text = _repair_math_unicode(group.strip())
    if not text:
        return False
    if _text_has_integral(text):
        return True
    if _MATH_OPERATOR_RE.search(text):
        return True
    if any(c in _MATH_FALLBACK_CHARS for c in text):
        return True
    return False


def _find_matching_math_paren(source: str, open_index: int) -> int | None:
    pairs = {")": ")", "]": "]", "}": "}"}
    pairs = {"(": ")", "[": "]", "{": "}"}
    open_ch = source[open_index]
    close_ch = pairs.get(open_ch)
    if close_ch is None:
        return None
    depth = 0
    for index in range(open_index, len(source)):
        char = source[index]
        if char == open_ch:
            depth += 1
        elif char == close_ch:
            depth -= 1
            if depth == 0:
                return index
    return None


def _consume_sqrt_radicand(text: str, start: int) -> tuple[str, int] | None:
    j = start
    while j < len(text) and text[j].isspace():
        j += 1
    if j >= len(text):
        return None
    if text[j] in "([{":
        close = _find_matching_math_paren(text, j)
        if close is not None and close > j:
            return text[j + 1 : close], close + 1
    atom_chars = "A-Za-z0-9⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎"
    match = re.match(f"[{atom_chars}]+(?:[-+][{atom_chars}]+)*", text[j:])
    if match:
        raw = match.group(0)
        return raw, j + len(raw)
    return None


def _find_matching_left(source: str, close_index: int, open_ch: str, close_ch: str) -> int | None:
    depth = 0
    for index in range(close_index, -1, -1):
        char = source[index]
        if char == close_ch:
            depth += 1
        elif char == open_ch:
            depth -= 1
            if depth == 0:
                return index
    return None


def _find_matching_right(source: str, open_index: int, open_ch: str, close_ch: str) -> int | None:
    depth = 0
    for index in range(open_index, len(source)):
        char = source[index]
        if char == open_ch:
            depth += 1
        elif char == close_ch:
            depth -= 1
            if depth == 0:
                return index
    return None


def _scan_tex_command_left(source: str, end: int) -> int:
    i = end
    while i > 0 and source[i - 1].isalpha():
        i -= 1
    if i > 0 and source[i - 1] == "\\":
        return i - 1
    return end


def _scan_tex_group_left(source: str, end: int) -> int | None:
    if end <= 0:
        return None
    close_ch = source[end - 1]
    pair = {"}": "{", ")": "(", "]": "["}.get(close_ch)
    if pair is None:
        return None
    start = _find_matching_left(source, end - 1, pair, close_ch)
    if start is None:
        return None
    if pair == "{" and start > 0 and source[start - 1] in "^_":
        base_start = _scan_tex_atom_left(source, start - 1)
        if base_start is not None:
            return base_start
        return start - 1
    if pair == "{":
        command_start = _scan_tex_command_left(source, start)
        if command_start < start:
            return command_start
    return start


def _scan_tex_atom_left(source: str, slash_index: int) -> int | None:
    end = slash_index
    while end > 0 and source[end - 1].isspace():
        end -= 1
    if end <= 0:
        return None
    group_start = _scan_tex_group_left(source, end)
    if group_start is not None:
        return group_start
    start = end
    while start > 0 and re.match(r"[A-Za-z0-9]", source[start - 1]):
        start -= 1
    if start < end:
        return start
    if source[end - 1] == "|":
        start = end - 1
        while start > 0 and source[start - 1] != "|":
            start -= 1
        if start >= 0:
            return start
    return None


def _scan_tex_group_right(source: str, start: int) -> int | None:
    if start >= len(source):
        return None
    open_ch = source[start]
    pair = {"{": "}", "(": ")", "[": "]"}.get(open_ch)
    if pair is None:
        return None
    end = _find_matching_right(source, start, open_ch, pair)
    if end is None:
        return None
    return end + 1


def _scan_tex_suffix_right(source: str, end: int) -> int:
    while end < len(source) and source[end] in "^_":
        group_start = end + 1
        if group_start < len(source) and source[group_start] == "{":
            group_end = _scan_tex_group_right(source, group_start)
            if group_end is None:
                return end
            end = group_end
        else:
            end += 1
            while end < len(source) and re.match(r"[A-Za-z0-9]", source[end]):
                end += 1
    return end


def _scan_tex_atom_right(source: str, slash_index: int) -> int | None:
    start = slash_index + 1
    while start < len(source) and source[start].isspace():
        start += 1
    if start >= len(source):
        return None
    if source[start] in "({[":
        group_end = _scan_tex_group_right(source, start)
        if group_end is not None:
            return _scan_tex_suffix_right(source, group_end)
        return None
    if source[start] == "\\":
        end = start + 1
        while end < len(source) and source[end].isalpha():
            end += 1
        if end < len(source) and source[end] == "{":
            group_end = _scan_tex_group_right(source, end)
            if group_end is not None:
                return _scan_tex_suffix_right(source, group_end)
        return _scan_tex_suffix_right(source, end)
    end = start
    while end < len(source) and re.match(r"[A-Za-z0-9]", source[end]):
        end += 1
    if end > start:
        return _scan_tex_suffix_right(source, end)
    if source[start] == "|":
        end = source.find("|", start + 1)
        if end >= 0:
            return end + 1
    return None


def _strip_wrapping_math_parens(expr: str) -> str:
    stripped = expr.strip()
    if len(stripped) >= 2 and stripped[0] == "(" and stripped[-1] == ")":
        close = _find_matching_right(stripped, 0, "(", ")")
        if close == len(stripped) - 1:
            return stripped[1:-1].strip()
    return stripped


def _tex_fraction_postprocess(tex: str) -> str:
    current = tex
    while True:
        changed = False
        depth_brace = 0
        depth_paren = 0
        depth_bracket = 0
        i = 0
        while i < len(current):
            char = current[i]
            if char == "{":
                depth_brace += 1
            elif char == "}":
                depth_brace = max(0, depth_brace - 1)
            elif char == "(":
                depth_paren += 1
            elif char == ")":
                depth_paren = max(0, depth_paren - 1)
            elif char == "[":
                depth_bracket += 1
            elif char == "]":
                depth_bracket = max(0, depth_bracket - 1)
            elif char == "/" and depth_brace == 0 and depth_paren == 0 and depth_bracket == 0:
                left_start = _scan_tex_atom_left(current, i)
                right_end = _scan_tex_atom_right(current, i)
                if left_start is not None and right_end is not None:
                    left = _strip_wrapping_math_parens(current[left_start:i])
                    right = _strip_wrapping_math_parens(current[i + 1 : right_end])
                    replacement = f"\\frac{{{left}}}{{{right}}}"
                    current = current[:left_start] + replacement + current[right_end:]
                    changed = True
                    break
            i += 1
        if not changed:
            return current


def _tex_differential_postprocess(tex: str) -> str:
    return re.sub(r"(?<![A-Za-z\\])d([A-Za-z])\b", r"\,d\1", tex)


def _strip_inline_math_delimiters(text: str) -> str:
    if not text:
        return text
    current = text
    for pattern in (r"\\\((.*?)\\\)", r"\\\[(.*?\\])", r"\$(.*?)\$"):
        current = re.sub(pattern, lambda m: m.group(1), current, flags=re.S)
    return current


def _strip_wrapping_tex_braces(text: str) -> str:
    if not text:
        return text
    leading_len = len(text) - len(text.lstrip())
    trailing_len = len(text) - len(text.rstrip())
    leading = text[:leading_len]
    trailing = text[len(text) - trailing_len:] if trailing_len else ""
    core = text.strip()
    if len(core) >= 2 and core[0] == "{" and core[-1] == "}":
        close = _find_matching_right(core, 0, "{", "}")
        if close == len(core) - 1:
            return leading + core[1:-1].strip() + trailing
    return text


def _plain_fraction_text(numerator: str, denominator: str) -> str:
    num = numerator.strip()
    den = denominator.strip()
    if re.search(r"\s|[+\-=]", num):
        num = f"({num})"
    if re.search(r"\s|[+\-=]", den):
        den = f"({den})"
    return f"{num}/{den}"


def _replace_simple_latex_groups(text: str) -> str:
    current = text
    for _ in range(12):
        updated = re.sub(
            r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}",
            lambda m: _plain_fraction_text(m.group(1), m.group(2)),
            current,
        )
        updated = re.sub(
            r"\\sqrt\s*\{([^{}]+)\}",
            lambda m: "√(" + m.group(1).strip() + ")",
            updated,
        )
        if updated == current:
            return current
        current = updated
    return current


def _normalize_ocr_latex_markup(text: str) -> str:
    if not text:
        return text
    normalized = _strip_inline_math_delimiters(text)
    normalized = normalized.replace(r"\left", "").replace(r"\right", "")
    normalized = normalized.replace(r"\{", "{").replace(r"\}", "}")
    normalized = _replace_simple_latex_groups(normalized)
    normalized = re.sub(r"\^\{([0-9+\-=()]+)\}", lambda m: _to_superscript(m.group(1)), normalized)
    normalized = re.sub(r"_\{([0-9+\-=()]+)\}", lambda m: _to_subscript(m.group(1)), normalized)
    replacements = {
        r"\leq": "≤",
        r"\le": "≤",
        r"\geq": "≥",
        r"\ge": "≥",
        r"\neq": "≠",
        r"\ne": "≠",
        r"\pm": "±",
        r"\times": "×",
        r"\div": "÷",
        r"\cdot": "·",
        r"\infty": "∞",
        r"\int": "∫",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"\\[;,! ]", " ", normalized)
    normalized = _strip_wrapping_tex_braces(normalized)
    return normalized


def _unicode_math_to_tex(text: str) -> str:
    text = _repair_math_unicode(_normalize_ocr_latex_markup(text))
    out = []
    i = 0
    while i < len(text):
        char = text[i]
        if char in _SUPERSCRIPT_TO_TEX:
            value = []
            while i < len(text) and text[i] in _SUPERSCRIPT_TO_TEX:
                value.append(_SUPERSCRIPT_TO_TEX[text[i]])
                i += 1
            out.append("^{" + "".join(value) + "}")
            continue
        if char in _SUBSCRIPT_TO_TEX:
            value = []
            while i < len(text) and text[i] in _SUBSCRIPT_TO_TEX:
                value.append(_SUBSCRIPT_TO_TEX[text[i]])
                i += 1
            out.append("_{" + "".join(value) + "}")
            continue
        if char == "√":
            radicand = _consume_sqrt_radicand(text, i + 1)
            if radicand is not None:
                raw, end = radicand
                out.append("\\sqrt{" + _unicode_math_to_tex(raw) + "}")
                i = end
                continue
            out.append("\\sqrt{}")
            i += 1
            continue
        replacements = {
            "≤": "\\le ",
            "≥": "\\ge ",
            "≠": "\\ne ",
            "±": "\\pm ",
            "∞": "\\infty ",
            "∫": "\\int ",
            "∑": "\\sum ",
            "∏": "\\prod ",
            "×": "\\times ",
            "÷": "\\div ",
            "·": "\\cdot ",
            "{": "\\{",
            "}": "\\}",
        }
        if char in replacements:
            out.append(replacements[char])
            i += 1
            continue
        out.append(char)
        i += 1
    tex = "".join(out)
    tex = _tex_differential_postprocess(tex)
    tex = _tex_fraction_postprocess(tex)
    return tex


def _system_range_end(lines: list[str], start: int) -> int:
    if start >= len(lines) or not _line_has_system_brace(lines[start]):
        return start
    equations = []
    end = start
    while end < len(lines):
        line = lines[end]
        if not line:
            end += 1
            continue
        core = _strip_system_brace(line)
        if not core:
            end += 1
            continue
        if not _is_system_equation_line(line):
            break
        equations.append(core)
        end += 1
    if len(equations) >= 2:
        return end
    return start


def _system_lines_to_mathjax_html(lines: list[str]) -> tuple[str, bool]:
    equations = [_strip_system_brace(line) for line in lines if _is_system_equation_line(line)]
    if len(equations) < 2:
        return ("", False)
    tex_lines = [html.escape(_unicode_math_to_tex(eq), quote=False) for eq in equations]
    body = "\\(\\left\\{\\begin{array}{l}" + " \\\\ ".join(tex_lines) + "\\end{array}\\right.\\)"
    return (body, True)


def _line_to_mathjax_html(line: str) -> tuple[str, bool]:
    line = normalize_handwriting_text(line)
    tokens = re.findall(r"\s+|\S+", line)
    pieces = []
    group = []
    has_math = False

    def flush_group() -> None:
        nonlocal has_math
        if not group:
            return
        raw = "".join(group)
        if _should_render_math_group(raw):
            leading_len = len(raw) - len(raw.lstrip())
            trailing_len = len(raw) - len(raw.rstrip())
            leading = raw[:leading_len]
            trailing = raw[len(raw) - trailing_len:] if trailing_len else ""
            core = raw.strip()
            if leading:
                pieces.append(html.escape(leading))
            tex = _unicode_math_to_tex(core)
            pieces.append("\\(" + html.escape(tex, quote=False) + "\\)")
            if trailing:
                pieces.append(html.escape(trailing))
            has_math = True
        else:
            pieces.append(html.escape(raw))
        group.clear()

    for token in tokens:
        if token.isspace():
            if group:
                group.append(token)
            else:
                pieces.append(html.escape(token))
        elif _looks_like_math_token(token) or (group and _continues_math_group(token)):
            group.append(token)
        else:
            flush_group()
            pieces.append(html.escape(token))
    flush_group()
    return ("".join(pieces), has_math)


def _text_has_mathjax(text: str) -> bool:
    for line in normalize_handwriting_text(text).split("\n"):
        if _line_to_mathjax_html(line)[1]:
            return True
    return False


def _lines_have_mathjax(lines: list[str]) -> bool:
    return any((line and _line_to_mathjax_html(line)[1]) for line in lines)


def _mathjax_line_height_ratio(line: str) -> float:
    if not line or not _line_to_mathjax_html(line)[1]:
        return 1.08
    repaired = _repair_math_unicode(line)
    ratio = 1.46
    if "/" in repaired or "√" in repaired or "\\frac" in repaired:
        ratio = max(ratio, 1.82)
    if any(char in repaired for char in "∫∑∏") or re.search(r"[⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉^_]", repaired):
        ratio = max(ratio, 1.58)
    return ratio


def _lines_math_height_ratio(lines: list[str], default: float = 1.16) -> float:
    ratios = [_mathjax_line_height_ratio(line) for line in lines if line]
    return max(ratios, default=default)


def build_handwriting_mathjax_html(
    content: HandwritingContent,
    width: int,
    height: int,
    handwriting_font: str | None = None,
    source_png_bytes: bytes | None = None,
    transparent_background: bool = True,
    preserve_source_overlay: bool = True,
) -> tuple[str, int, int, bool] | None:
    """Build one transparent HTML page from OCR blocks; MathJax renders math runs."""
    mathjax_source = _mathjax_script_source()
    logical_width = max(160, int(width or 0))
    logical_height = max(90, int(height or 0))
    scale = _LOCAL_RENDER_SCALE
    width = logical_width * scale
    height = logical_height * scale
    blocks = _merge_integral_differential_blocks(_merge_system_blocks(list(content.blocks or [])))
    if not blocks and content.main_text:
        blocks = [HandwritingBlock(content.main_text, 0.5, 0.5, 0.96, 0.86, "text")]
    if not blocks:
        return None
    has_math_hint = any(_text_has_mathjax(block.text) for block in blocks)
    padding_x = max(8, int(width * 0.018))
    padding_top = max(8, int(height * (0.095 if has_math_hint else 0.035)))
    padding_bottom = max(10, int(height * (0.135 if has_math_hint else 0.04)))
    overlay_html = ""
    if preserve_source_overlay:
        source_clear_rects = _block_clear_rects(blocks, width, height)
        overlay = _extract_source_drawing_overlay(
            source_png_bytes,
            width,
            height,
            0,
            label_clear_rects=source_clear_rects,
            preserve_original_drawing=True,
        )
    else:
        overlay = None
    if overlay is not None:
        data = io.BytesIO()
        overlay.save(data, format="PNG")
        encoded = base64.b64encode(data.getvalue()).decode("ascii")
        overlay_html = f'<img class="source-overlay" src="data:image/png;base64,{encoded}" alt="">'
    family, font_face = _font_face_css(handwriting_font)
    dummy = Image.new("RGB", (max(1, width), max(1, height)), (255, 255, 255))
    draw = ImageDraw.Draw(dummy)
    draw_blocks = _fit_blocks_to_canvas(blocks, width, height, padding_x, padding_top, padding_bottom)
    rng = random.Random((len(content.main_text) * 131 + width * 17 + height * 29) & 0xFFFFFFFF)
    ink_colors = ["rgb(2,30,92)", "rgb(0,36,108)", "rgb(8,42,116)"]
    line_html = []
    has_math = False
    for index, block in enumerate(draw_blocks):
        block_text = normalize_handwriting_text(block.text)
        if not block_text:
            continue
        left, top, right, bottom = _block_rect(block, width, height)
        rect_w = max(18, right - left)
        rect_h = max(14, bottom - top)
        font, lines, line_height, paragraph_gap = _choose_block_font_and_lines(
            draw, block_text, rect_w, rect_h, handwriting_font=handwriting_font
        )
        total_text_height = sum((line_height if line else paragraph_gap) for line in lines)
        cursor_y = top + max(0, (rect_h - total_text_height) // 2)
        block_rng = random.Random((index * 7919 + len(block_text) * 313 + width * 7 + height * 19) & 0xFFFFFFFF)
        line_index = 0
        while line_index < len(lines):
            line = lines[line_index]
            if line == "":
                cursor_y += paragraph_gap
                line_index += 1
                continue
            jitter_x = block_rng.randint(-2, 3) * scale
            jitter_y = block_rng.randint(-1, 2) * scale
            system_end = _system_range_end(lines, line_index)
            if system_end > line_index:
                system_lines = lines[line_index:system_end]
                line_body, line_has_math = _system_lines_to_mathjax_html(system_lines)
                visible_count = max(1, sum(1 for item in system_lines if _is_system_equation_line(item)))
                line_span_height = max(line_height, line_height * visible_count)
                line_index = system_end
            else:
                line_body, line_has_math = _line_to_mathjax_html(line)
                line_span_height = line_height
                line_index += 1
            has_math = has_math or line_has_math
            color = rng.choice(ink_colors)
            line_html.append(
                f'<div class="hw-line" style="left:{left + jitter_x}px;top:{cursor_y + jitter_y}px;max-width:{rect_w}px;font-size:{int(getattr(font, "size", 18))}px;line-height:{line_height}px;min-height:{line_span_height}px;color:{color};">{line_body}</div>'
            )
            cursor_y += line_span_height + block_rng.randint(-1, 2) * scale

    if has_math and not mathjax_source:
        return None
    mathjax_config = ""
    mathjax_script = ""
    if has_math and mathjax_source:
        mathjax_config = """
<script>
window.__EDRAW_HANDWRITING_READY = false;
window.__EDRAW_HANDWRITING_FAILED = false;
window.MathJax = {
  tex: {
    inlineMath: [['\\\\(','\\\\)']],
    displayMath: [['\\\\[','\\\\]']],
    processEscapes: true
  },
  svg: { fontCache: 'none' },
  startup: {
    typeset: false,
    ready: function () {
      MathJax.startup.defaultReady();
      MathJax.typesetPromise([document.getElementById('page')])
        .then(function(){ window.__EDRAW_HANDWRITING_READY = true; })
        .catch(function(){ window.__EDRAW_HANDWRITING_FAILED = true; });
    }
  }
};
</script>
"""
        mathjax_script = f"<script>{mathjax_source}</script>"
    else:
        mathjax_config = "<script>window.__EDRAW_HANDWRITING_READY=true;window.__EDRAW_HANDWRITING_FAILED=false;</script>"
    background = "transparent" if transparent_background else "#f9faf7"
    doc = "".join([
        "<!doctype html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n",
        f"{mathjax_config}\n",
        f"{mathjax_script}\n<style>\n",
        f"{font_face}\nhtml, body {{\n  margin: 0;\n  padding: 0;\n  width: {width}px;\n  height: {height}px;\n  overflow: hidden;\n  background: {background};\n}}\n#page {{\n  position: relative;\n  width: {width}px;\n  height: {height}px;\n  overflow: hidden;\n  background: {background};\n}}\n.source-overlay {{\n  position: absolute;\n  left: 0;\n  top: 0;\n  width: {width}px;\n  height: {height}px;\n}}\n#edraw-md {{\n  margin: 0 !important;\n  padding: 0 !important;\n  width: {width}px !important;\n  height: {height}px !important;\n  overflow: hidden !important;\n}}\n.hw-line {{\n  position: absolute;\n  font-family: '{family}', 'Comic Sans MS', 'Segoe Print', cursive;\n  font-weight: 400;\n  white-space: nowrap;\n  overflow: visible;\n  text-shadow: 1px 0 currentColor;\n}}\n.hw-line mjx-container {{\n  margin: 0 !important;\n  color: inherit !important;\n  vertical-align: -0.12em;\n  overflow: visible !important;\n}}\n.hw-line mjx-container[jax=\"SVG\"] svg {{\n  overflow: visible;\n}}\n</style>\n</head>\n<body>\n<div id=\"page\">\n",
        f"{overlay_html}\n",
        "".join(line_html),
        "\n</div>\n</body>\n</html>",
    ])
    return (doc, width, height, (has_math and bool(mathjax_source)))


def build_handwriting_mathjax_body(
    content: HandwritingContent,
    width: int,
    height: int,
    handwriting_font: str | None = None,
    source_png_bytes: bytes | None = None,
    transparent_background: bool = True,
    preserve_source_overlay: bool = True,
) -> tuple[str, int, int, bool] | None:
    built = build_handwriting_mathjax_html(
        content,
        width,
        height,
        handwriting_font=handwriting_font,
        source_png_bytes=source_png_bytes,
        transparent_background=transparent_background,
        preserve_source_overlay=preserve_source_overlay,
    )
    if built is None:
        return None
    doc, render_w, render_h, has_math = built
    style_match = re.search(r"<style>\s*(.*?)\s*</style>", doc, flags=re.S | re.I)
    body_match = re.search(r'(<div id="page">.*</div>)\s*</body>', doc, flags=re.S | re.I)
    if not style_match or not body_match:
        return None
    body = f"<style>{style_match.group(1)}</style>{body_match.group(1)}"
    return (body, render_w, render_h, has_math)


def _split_long_word(draw: ImageDraw.ImageDraw, word: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    if _text_width(draw, word, font) <= max_width:
        return [word]
    chunks = []
    current = ""
    for char in word:
        candidate = current + char
        if current and _text_width(draw, candidate, font) > max_width:
            chunks.append(current)
            current = char
            continue
        current = candidate
    if current:
        chunks.append(current)
    if not chunks:
        return [word]
    return chunks


def _wrap_line(draw: ImageDraw.ImageDraw, line: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    if _text_has_integral(line):
        return [line]
    words = line.split()
    if not words:
        return [""]
    wrapped = []
    current = ""
    for word in words:
        pieces = _split_long_word(draw, word, font, max_width)
        for piece in pieces:
            candidate = piece if not current else f"{current} {piece}"
            if not current or _text_width(draw, candidate, font) <= max_width:
                current = candidate
                continue
            wrapped.append(current)
            current = piece
    if current:
        wrapped.append(current)
    return wrapped


def _layout_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines = []
    paragraphs = normalize_handwriting_text(text).split("\n")
    for paragraph_index, paragraph in enumerate(paragraphs):
        lines.extend(_wrap_line(draw, paragraph, font, max_width))
        if paragraph_index < len(paragraphs) - 1:
            lines.append("")
    return _merge_integral_differential_lines(lines)


def _merge_integral_differential_lines(lines: list[str]) -> list[str]:
    if len(lines) <= 1:
        return lines
    merged = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _text_has_integral(line):
            probe = index + 1
            skipped_blank = False
            while probe < len(lines) and lines[probe] == "":
                probe += 1
                skipped_blank = True
            if probe < len(lines) and _is_differential_text(lines[probe]):
                merged.append(f"{line.strip()} {lines[probe].strip()}")
                index = probe + 1
                continue
            if skipped_blank:
                merged.append(line)
                index += 1
                continue
        merged.append(line)
        index += 1
    return merged


def _choose_layout(
    text: str,
    width: int,
    height: int,
    padding_x: int,
    padding_top: int,
    padding_bottom: int,
    handwriting_font: str | None = None,
) -> tuple[ImageFont.FreeTypeFont, list[str], int, int]:
    dummy = Image.new("RGB", (max(1, width), max(1, height)), (255, 255, 255))
    draw = ImageDraw.Draw(dummy)
    max_width = max(20, width - padding_x * 2)
    usable_height = max(20, height - padding_top - padding_bottom)
    render_scale = max(1, _LOCAL_RENDER_SCALE)
    max_size = max(18 * render_scale, min(86 * render_scale, int(width / 10), int(usable_height * 0.92)))
    min_size = 10 * render_scale
    fallback = None
    paragraphs = [line for line in normalize_handwriting_text(text).split("\n") if line]
    use_math_font = False
    for size in range(max_size, min_size - 1, -2):
        font = _load_font(size, math=use_math_font, handwriting_font=handwriting_font)
        paragraph_gap = max(2, int(size * 0.14))
        lines = _layout_lines(draw, text, font, max_width)
        line_height = max(12, int(size * _lines_math_height_ratio(lines)))
        total_height = 0
        for line in lines:
            total_height += paragraph_gap if line == "" else line_height
        fallback = (font, lines, line_height, paragraph_gap)
        if total_height <= usable_height and len([line for line in lines if line]) <= max(1, len(paragraphs)):
            return fallback

    for size in range(max_size, min_size - 1, -2):
        font = _load_font(size, math=use_math_font, handwriting_font=handwriting_font)
        paragraph_gap = max(2, int(size * 0.14))
        lines = _layout_lines(draw, text, font, max_width)
        line_height = max(12, int(size * _lines_math_height_ratio(lines)))
        total_height = 0
        for line in lines:
            total_height += paragraph_gap if line == "" else line_height
        fallback = (font, lines, line_height, paragraph_gap)
        if total_height <= usable_height:
            return fallback

    if fallback is not None:
        return fallback
    return (_load_font(18, math=use_math_font, handwriting_font=handwriting_font), [], 20, 3)


def _make_paper_texture(width: int, height: int) -> Image.Image:
    paper = Image.new("RGB", (width, height), (249, 250, 247))
    noise = Image.effect_noise((width, height), 7).convert("L")
    noise = ImageEnhance.Contrast(noise).enhance(0.42)
    tint = Image.new("RGB", (width, height), (239, 243, 242))
    textured = Image.blend(paper, tint, 0.16)
    textured.putalpha(noise.point(lambda v: 16 if v > 128 else 7))
    base = Image.new("RGB", (width, height), (249, 250, 247))
    base.paste(textured, mask=textured.getchannel("A"))
    return base


def _label_clear_rects(
    draw: ImageDraw.ImageDraw,
    labels: list[HandwritingLabel],
    font: ImageFont.FreeTypeFont,
    width: int,
    height: int,
) -> list[tuple[int, int, int, int]]:
    rects = []
    if not labels:
        return rects
    for label in labels:
        text = normalize_handwriting_text(label.text).replace("\n", " ")
        if not text:
            continue
        box = draw.textbbox((0, 0), text, font=font)
        text_w = max(8, box[2] - box[0])
        text_h = max(8, box[3] - box[1])
        cx = int(label.x * width)
        cy = int(label.y * height)
        pad_x = max(8, int(text_h * 0.65))
        pad_y = max(6, int(text_h * 0.55))
        rects.append(
            (
                max(0, cx - text_w // 2 - pad_x),
                max(0, cy - text_h // 2 - pad_y),
                min(width, cx + text_w // 2 + pad_x),
                min(height, cy + text_h // 2 + pad_y),
            )
        )
    return rects


def _block_rect(block: HandwritingBlock, width: int, height: int) -> tuple[int, int, int, int]:
    text_len = len(block.text)
    est_chars_per_line = max(1, text_len)
    fallback_w = max(80, min(width, int(est_chars_per_line * 11)))
    n_lines = max(1, block.text.count("\n") + 1)
    fallback_h = max(28, min(height, int(n_lines * 24)))
    block_w = max(int(block.w * width), fallback_w) if block.w > 0.01 else fallback_w
    block_h = max(int(block.h * height), fallback_h) if block.h > 0.01 else fallback_h
    block_w = max(32, min(width, block_w))
    block_h = max(20, min(height, block_h))
    cx = int(block.x * width)
    cy = int(block.y * height)
    left = max(0, cx - block_w // 2)
    top = max(0, cy - block_h // 2)
    right = min(width, left + block_w)
    bottom = min(height, top + block_h)
    if right - left < block_w:
        left = max(0, right - block_w)
    if bottom - top < block_h:
        top = max(0, bottom - block_h)
    return (left, top, right, bottom)


def _block_clear_rects(blocks: list[HandwritingBlock], width: int, height: int) -> list[tuple[int, int, int, int]]:
    rects = []
    if not blocks:
        return rects
    for block in blocks:
        left, top, right, bottom = _block_rect(block, width, height)
        pad_x = max(8, int((bottom - top) * 0.45))
        pad_y = max(5, int((bottom - top) * 0.28))
        rects.append(
            (
                max(0, left - pad_x),
                max(0, top - pad_y),
                min(width, right + pad_x),
                min(height, bottom + pad_y),
            )
        )
    return rects


def _choose_block_font_and_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    rect_width: int,
    rect_height: int,
    handwriting_font: str | None = None,
) -> tuple[ImageFont.FreeTypeFont, list[str], int, int]:
    render_scale = max(1, _LOCAL_RENDER_SCALE)
    max_line_width = max(20, rect_width)
    use_math_font = _is_math_text(text)
    max_size = max(14 * render_scale, min(72 * render_scale, int(rect_height * 0.78), int(max_line_width / 4)))
    min_size = max(10 * render_scale, int(rect_height * 0.18))
    if min_size > max_size:
        min_size = max(8 * render_scale, max_size - 4 * render_scale)
    fallback = None
    for size in range(max_size, min_size - 1, -1):
        font = _load_font(size, math=use_math_font, handwriting_font=handwriting_font)
        paragraph_gap = max(2, int(size * 0.14))
        lines = _layout_lines(draw, text, font, max_line_width)
        line_height = max(12, int(size * _lines_math_height_ratio(lines)))
        line_boxes = [draw.textbbox((0, 0), line, font=font) for line in lines if line]
        total_height = sum((paragraph_gap if line == "" else line_height) for line in lines)
        widest = max((box[2] - box[0] for box in line_boxes), default=0)
        glyph_height = sum(box[3] - box[1] for box in line_boxes) + paragraph_gap * lines.count("")
        fallback = (font, lines, line_height, paragraph_gap)
        if total_height <= rect_height and glyph_height <= rect_height and widest <= max_line_width:
            return fallback
    if fallback is not None:
        return fallback
    return (_load_font(12 * render_scale, math=use_math_font, handwriting_font=handwriting_font), [text], 14 * render_scale, 2 * render_scale)


def _draw_handwriting_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    line_height: int,
    paragraph_gap: int,
    rng: random.Random,
    ink_colors: list[str],
) -> int:
    cursor_y = y
    text_bottom = cursor_y
    for line in lines:
        if line == "":
            cursor_y += paragraph_gap
            continue
        jitter_x = rng.randint(-2, 3)
        jitter_y = rng.randint(-1, 2)
        color = rng.choice(ink_colors)
        line_box = draw.textbbox((0, 0), line, font=font)
        draw_y = cursor_y - min(0, line_box[1]) + jitter_y
        _draw_text_with_math_fallback(draw, (x + jitter_x, draw_y), line, fill=color, font=font)
        _draw_text_with_math_fallback(draw, (x + jitter_x + 1, draw_y), line, fill=color, font=font)
        text_bottom = max(text_bottom, cursor_y + line_height)
        cursor_y += line_height + rng.randint(-1, 2)
    return text_bottom


def _inside_any_rect(x: int, y: int, rects: list[tuple[int, int, int, int]]) -> bool:
    for left, top, right, bottom in rects:
        if left <= x < right and top <= y < bottom:
            return True
    return False


def _extract_source_drawing_overlay(
    source_png_bytes: bytes | None,
    width: int,
    height: int,
    min_y: int,
    label_clear_rects: list[tuple[int, int, int, int]] | None = None,
    preserve_original_drawing: bool = False,
) -> Image.Image | None:
    if not source_png_bytes:
        return None
    try:
        source = Image.open(io.BytesIO(source_png_bytes)).convert("RGBA")
    except Exception:
        return None
    if source.size != (width, height):
        source = source.resize((width, height), Image.Resampling.LANCZOS)
    total = width * height
    pixels = list(source.getdata())
    mask_values = bytearray(total)
    dark_candidates = bytearray(total)
    kept = 0
    color_kept = 0
    for index, (r, g, b, a) in enumerate(pixels):
        y = index // width
        if y < min_y or a <= 18:
            continue
        x = index % width
        if label_clear_rects and _inside_any_rect(x, y, label_clear_rects):
            continue
        brightness = (int(r) + int(g) + int(b)) / 3.0
        saturation = max(r, g, b) - min(r, g, b)
        colorful = saturation >= 24 and max(r, g, b) >= 60 and brightness <= 235
        if colorful:
            mask_values[index] = min(235, max(0, a))
            kept += 1
            color_kept += 1
        elif brightness <= 140:
            dark_candidates[index] = 1

    def keep_dark_component(count: int, min_x: int, max_x: int, min_comp_y: int, max_comp_y: int) -> bool:
        if count < 8:
            return False
        bbox_w = max_x - min_x + 1
        bbox_h = max_comp_y - min_comp_y + 1
        density = count / max(1, bbox_w * bbox_h)
        horizontal_axis = (
            bbox_w >= max(70, int(width * 0.1))
            and bbox_h <= max(18, int(height * 0.09))
            and density >= 0.05
        )
        vertical_axis = (
            bbox_h >= max(55, int(height * 0.16))
            and bbox_w <= max(18, int(width * 0.045))
            and density >= 0.05
        )
        large_shape = (
            bbox_w >= max(70, int(width * 0.12))
            and bbox_h >= max(34, int(height * 0.12))
            and density <= 0.28
        )
        return horizontal_axis or vertical_axis or large_shape

    visited = bytearray(total)
    start_row = max(0, min_y)
    dark_component_kept = 0
    for start in range(start_row * width, total):
        if not dark_candidates[start] or visited[start]:
            continue
        stack = [start]
        visited[start] = 1
        component = []
        min_x = width
        max_x = 0
        min_comp_y = height
        max_comp_y = 0
        while stack:
            point = stack.pop()
            component.append(point)
            px = point % width
            py = point // width
            if px < min_x:
                min_x = px
            if px > max_x:
                max_x = px
            if py < min_comp_y:
                min_comp_y = py
            if py > max_comp_y:
                max_comp_y = py
            for ny in (py - 1, py, py + 1):
                if 0 <= ny < height:
                    row = ny * width
                    for nx in (px - 1, px, px + 1):
                        if 0 <= nx < width:
                            neighbor = row + nx
                            if dark_candidates[neighbor] and not visited[neighbor]:
                                visited[neighbor] = 1
                                stack.append(neighbor)
        if not keep_dark_component(len(component), min_x, max_x, min_comp_y, max_comp_y):
            continue
        for point in component:
            mask_values[point] = min(235, max(0, pixels[point][3]))
        kept += len(component)
        dark_component_kept += len(component)

    if preserve_original_drawing and (color_kept >= 24 or dark_component_kept >= 24 or not label_clear_rects):
        kept = 0
        mask_values = bytearray(total)
        for index, (r, g, b, a) in enumerate(pixels):
            y = index // width
            if y < min_y or a <= 18:
                continue
            x = index % width
            if label_clear_rects and _inside_any_rect(x, y, label_clear_rects):
                continue
            brightness = (int(r) + int(g) + int(b)) / 3.0
            saturation = max(r, g, b) - min(r, g, b)
            visible_stroke = brightness < 205 or (saturation > 22 and max(r, g, b) > 60)
            if not visible_stroke:
                continue
            mask_values[index] = min(235, max(0, a))
            kept += 1

    if kept < 12:
        return None

    mask = Image.new("L", (width, height), 0)
    mask.putdata(mask_values)
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(0.25))
    overlay = source.copy()
    overlay.putalpha(mask)
    return overlay


def render_handwriting_image(
    text: str,
    width: int,
    height: int,
    labels: list[HandwritingLabel] | None = None,
    blocks: list[HandwritingBlock] | None = None,
    handwriting_font: str | None = None,
    source_png_bytes: bytes | None = None,
    transparent_background: bool = False,
    preserve_source_overlay: bool = True,
) -> QImage:
    logical_width = max(160, int(width or 0))
    logical_height = max(90, int(height or 0))
    scale = _LOCAL_RENDER_SCALE
    width = logical_width * scale
    height = logical_height * scale
    padding_x = max(8, int(width * 0.018))
    padding_top = max(8, int(height * 0.035))
    padding_bottom = max(10, int(height * 0.04))

    if transparent_background:
        page = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    else:
        page = _make_paper_texture(width, height).convert("RGBA")
    draw = ImageDraw.Draw(page)

    rng = random.Random((len(text) * 131 + width * 17 + height * 29) & 0xFFFFFFFF)
    ink_colors = [(2, 30, 92), (0, 36, 108), (8, 42, 116)]

    if preserve_source_overlay:
        source_clear_rects = _block_clear_rects(blocks or [], width, height)
        draw_blocks = _fit_blocks_to_canvas(blocks or [], width, height, padding_x, padding_top, padding_bottom)
        overlay = _extract_source_drawing_overlay(
            source_png_bytes,
            width,
            height,
            0,
            label_clear_rects=source_clear_rects,
            preserve_original_drawing=True,
        )
        if overlay is not None:
            page.alpha_composite(overlay)
    else:
        draw_blocks = _fit_blocks_to_canvas(blocks or [], width, height, padding_x, padding_top, padding_bottom)

    if draw_blocks:
        for index, block in enumerate(draw_blocks):
            block_text = normalize_handwriting_text(block.text)
            if not block_text:
                continue
            left, top, right, bottom = _block_rect(block, width, height)
            rect_w = max(18, right - left)
            rect_h = max(14, bottom - top)
            font, block_lines, line_height, paragraph_gap = _choose_block_font_and_lines(
                draw, block_text, rect_w, rect_h, handwriting_font=handwriting_font
            )
            total_text_height = sum((line_height if line else paragraph_gap) for line in block_lines)
            text_y = top + max(0, (rect_h - total_text_height) // 2)
            block_rng = random.Random((index * 7919 + len(block_text) * 313 + width * 7 + height * 19) & 0xFFFFFFFF)
            _draw_handwriting_lines(
                draw,
                block_lines,
                font,
                left,
                text_y,
                line_height,
                paragraph_gap,
                block_rng,
                ink_colors,
            )
        page = page.filter(ImageFilter.UnsharpMask(radius=0.7, percent=112, threshold=3))
        data = io.BytesIO()
        page.save(data, format="PNG")
        image = QImage()
        image.loadFromData(data.getvalue())
        return image

    font, lines, line_height, paragraph_gap = _choose_layout(
        text, width, height, padding_x, padding_top, padding_bottom, handwriting_font=handwriting_font
    )
    cursor_y = padding_top
    text_bottom = cursor_y
    main_text_clear_rects = []
    for line in lines:
        if line == "":
            cursor_y += paragraph_gap
            continue
        jitter_x = rng.randint(-2, 3)
        jitter_y = rng.randint(-1, 2)
        text_x = padding_x + jitter_x
        text_box = draw.textbbox((0, 0), line, font=font)
        pad_line_x = max(8, int((text_box[2] - text_box[0]) * 0.04))
        pad_line_y = max(6, int(line_height * 0.28))
        main_text_clear_rects.append(
            (
                max(0, text_x - pad_line_x),
                max(0, cursor_y - pad_line_y),
                min(width, text_x + (text_box[2] - text_box[0]) + pad_line_x),
                min(height, cursor_y + line_height + pad_line_y),
            )
        )
        color = rng.choice(ink_colors)
        _draw_text_with_math_fallback(draw, (text_x, cursor_y + jitter_y), line, fill=color, font=font)
        _draw_text_with_math_fallback(draw, (text_x + 1, cursor_y + jitter_y), line, fill=color, font=font)
        text_bottom = max(text_bottom, cursor_y + line_height)
        cursor_y += line_height + rng.randint(-1, 2)

    if preserve_source_overlay:
        overlay = _extract_source_drawing_overlay(
            source_png_bytes,
            width,
            height,
            max(0, text_bottom - int(line_height * 0.72)),
            label_clear_rects=main_text_clear_rects,
            preserve_original_drawing=False,
        )
        if overlay is not None:
            page.alpha_composite(overlay)

    if labels:
        label_size = max(12, int(getattr(font, "size", 24) * 0.55), min(34, int(width * 0.12)))
        label_font = _load_font(
            label_size,
            math=any(_is_math_text(label.text) for label in labels),
            handwriting_font=handwriting_font,
        )
        label_clear_rects = _label_clear_rects(draw, labels, label_font, width, height)
        label_rng = random.Random((len(labels) * 977 + width * 11 + height * 23) & 0xFFFFFFFF)
        for label in labels:
            label_text = normalize_handwriting_text(label.text).replace("\n", " ")
            if not label_text:
                continue
            box = draw.textbbox((0, 0), label_text, font=label_font)
            label_w = box[2] - box[0]
            label_h = box[3] - box[1]
            x = int(label.x * width) - label_w // 2 + label_rng.randint(-2, 3)
            y = int(label.y * height) - label_h // 2 + label_rng.randint(-1, 2)
            color = label_rng.choice(ink_colors)
            _draw_text_with_math_fallback(draw, (x, y), label_text, fill=color, font=label_font)
            _draw_text_with_math_fallback(draw, (x + 1, y), label_text, fill=color, font=label_font)

    page = page.filter(ImageFilter.UnsharpMask(radius=0.7, percent=112, threshold=3))
    data = io.BytesIO()
    page.save(data, format="PNG")
    image = QImage()
    image.loadFromData(data.getvalue())
    return image


def extract_text_with_gemini(
    api_key: str,
    model: str = "gemini-2.5-pro",
    png_bytes: Any = None,
    log: Any = None,
    *,
    timeout_ms: int = 45000,
    retry_max: int = 2,
    retry_wait: float = 1.5,
) -> HandwritingContent:
    if log is None:
        log = lambda msg: None
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Thiếu thư viện google-genai. Hãy chạy: pip install google-genai") from exc
    from core.gemini_models import get_candidate_models, ensure_png_bytes, is_fallback_error

    raw_bytes = ensure_png_bytes(png_bytes)
    if not raw_bytes:
        raise RuntimeError(t("Vui lòng vẽ hoặc chọn nội dung trên bảng trước khi dùng AI."))

    image_part = types.Part.from_bytes(data=raw_bytes, mime_type="image/png")
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))
    candidates = get_candidate_models(model)
    last_err = None

    for m_idx, current_model in enumerate(candidates):
        is_last = (m_idx == len(candidates) - 1)
        attempts = 1 if not is_last else retry_max
        for attempt in range(1, attempts + 1):
            try:
                log(t("Gọi Gemini đọc nội dung ({model})...", model=current_model))
                resp = client.models.generate_content(
                    model=current_model,
                    contents=[_OCR_PROMPT, image_part],
                    config=types.GenerateContentConfig(temperature=0.02),
                )
                text = (resp.text or "").strip()
                content = _parse_handwriting_content(text)
                label_count = len(content.labels)
                block_count = len(content.blocks)
                log(t("Gemini trả về {block_count} khối chữ, {char_count} ký tự fallback và {label_count} nhãn hình vẽ.",
                      block_count=block_count, char_count=len(content.main_text), label_count=label_count))
                if content.blocks or content.main_text or content.labels:
                    return content
                if text:
                    # Non-empty raw text that didn't match schema
                    return HandwritingContent(
                        main_text=text,
                        blocks=[HandwritingBlock(text=text, x=0.5, y=0.5, w=0.9, h=0.8)]
                    )
            except Exception as exc:
                last_err = exc
                err_msg = str(exc)
                log(t("Gemini lỗi: {error}", error=err_msg[:120]))
                if is_fallback_error(exc) and not is_last:
                    next_model = candidates[m_idx + 1]
                    log(t("→ Tự động chuyển sang mô hình: {model} …", model=next_model))
                    break
                if attempt < attempts:
                    time.sleep(retry_wait * attempt)

    if last_err:
        raise last_err
    raise RuntimeError("Gemini không đọc được nội dung trong vùng chọn.")


