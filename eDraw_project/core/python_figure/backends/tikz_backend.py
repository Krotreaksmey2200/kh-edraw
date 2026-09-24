"""TikZ / pdflatex backend for editable code figures.

Users author a complete standalone LaTeX document.  If the document contains a
top-level ``\\foreach \\k in {...}{ ... \\begin{tikzpicture} ... }`` loop, the
backend treats each generated PDF page as one value of the detected parameter
and exposes that value as a slider.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter

from core.i18n import t
from core.latex_engine import LatexEngineError, _run_pdflatex
from core.python_figure.protocol import BackendProgram, RenderResult

TIKZ_FIXED_PREAMBLE = (
    "\\documentclass[tikz,border=1mm]{standalone}\n"
    "\\usepackage[utf8]{vietnam}\n"
    "\\usepackage{amsmath,amssymb}\n"
    "\\usepackage{tikz}\n"
    "\\usetikzlibrary{arrows.meta,calc,intersections,patterns,patterns.meta,"
    "positioning,shapes.geometric,angles,quotes}\n"
)


class TikzBackend:
    """Compile standalone TikZ documents with pdflatex and render PDF pages."""

    name = "tikz"
    allow_modules = frozenset()

    def compile(self, code: str) -> BackendProgram:
        tex = _normalise_tikz_document(code)
        param_sets = _detect_top_level_foreach_params(tex)
        work_dir = Path(tempfile.mkdtemp(prefix="edraw_tikz_fig_"))
        tex_name = "tikz_figure.tex"
        tex_path = work_dir / tex_name
        tex_path.write_text(tex, encoding="utf-8")
        pdf_path = work_dir / "tikz_figure.pdf"
        _run_pdflatex(tex_path, pdf_path, timeout=180)
        if not pdf_path.exists():
            raise LatexEngineError("PDF đã tạo nhưng không đọc được trang ảnh nào.")
        pdf_bytes = pdf_path.read_bytes()
        page_count = _pdf_page_count(pdf_bytes)
        warnings: list[str] = []
        param_specs: dict[str, Any] = {}
        if param_sets:
            for i, ps in enumerate(param_sets):
                expected = len(ps["values"])
                if expected != page_count:
                    warnings.append(
                        f"Phát hiện {expected} giá trị tham số nhưng PDF có {page_count} trang."
                    )
            param_specs = _param_specs_from_foreach(param_sets)
        else:
            warnings.append(t("Không phát hiện \\foreach ngoài tikzpicture; dùng thanh Trang."))
        return BackendProgram(
            source=code,
            warnings=warnings,
            payload={
                "pdf_bytes": pdf_bytes,
                "page_count": page_count,
                "param_sets": param_sets,
            },
        )

    def render(
        self,
        program: BackendProgram,
        params: dict[str, float],
        size_px: tuple[int, int],
    ) -> RenderResult:
        if not program.payload:
            raise ValueError("Backend TikZ chưa có PDF vector đã biên dịch.")
        payload = program.payload
        pdf_bytes = payload.get("pdf_bytes", b"")
        page_count = int(payload.get("page_count", 0))
        if not pdf_bytes or page_count <= 0:
            raise ValueError("Backend TikZ chưa có PDF vector đã biên dịch.")
        param_sets = payload.get("param_sets", [])
        idx = _page_index_for_params(param_sets, params, page_count)
        return RenderResult(
            image=_render_pdf_page_to_qimage(pdf_bytes, idx, size_px),
            warnings=list(program.warnings),
        )


def _ensure_vietnam_package(text: str) -> str:
    """Insert ``\\usepackage[utf8]{vietnam}`` if a full TeX doc is missing it.

    Gemini sometimes ignores the preamble instruction and ships
    ``\\usepackage[utf8]{inputenc}`` instead, which then chokes on Vietnamese
    characters like ``ố`` (U+1ED1).  We treat the vietnam package as a
    non-negotiable safety net and patch it in right after ``\\documentclass``
    when absent.
    """
    if "\\usepackage[utf8]{vietnam}" in text or "\\usepackage{vietnam}" in text:
        return text
    match = re.search(r"\\documentclass[^\n]*\n", text)
    if not match:
        return text
    insert_at = match.end()
    return text[:insert_at] + "\\usepackage[utf8]{vietnam}\n" + text[insert_at:]


def _normalise_tikz_document(code: str) -> str:
    text = (code or "").strip()
    if not text:
        raise ValueError("Mã TikZ đang rỗng.")
    fence = re.search(r"```(?:latex|tex|tikz)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    if "\\documentclass" in text and "\\begin{document}" in text:
        return _ensure_vietnam_package(text)
    if "\\begin{tikzpicture}" in text:
        return TIKZ_FIXED_PREAMBLE + "\\begin{document}\n" + f"{text}\n" + "\\end{document}\n"
    raise ValueError("Mã TikZ cần là document standalone hoặc chứa \\begin{tikzpicture}.")


def _strip_tex_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        cut = len(line)
        i = 0
        in_quote = False
        while i < len(line):
            ch = line[i]
            if ch == '"':
                in_quote = not in_quote
            elif ch == '%' and not in_quote:
                cut = i
                break
            elif ch == '\\':
                i += 1
            i += 1
        out.append(line[:cut])
    return '\n'.join(out)


def _outside_tikzpicture_text(text: str) -> str:
    clean = _strip_tex_comments(text)
    out = []
    pos = 0
    begin_re = re.compile(r'\\begin\s*\{tikzpicture\}')
    end_re = re.compile(r'\\end\s*\{tikzpicture\}')
    m = begin_re.search(clean, pos)
    if not m:
        out.append(clean[pos:])
    else:
        out.append(clean[pos:m.start()])
        e = end_re.search(clean, m.end())
        if e:
            pos = e.end()
    return '\n'.join(out)


def _detect_top_level_foreach_params(tex: str) -> list[dict[str, Any]]:
    outside = _outside_tikzpicture_text(tex)
    pattern = re.compile(
        r'\\foreach\s+\\([A-Za-z@]+)(?:\s*\[[^\]]*\])?\s+in\s*\{([^{}]+)\}',
        flags=re.DOTALL,
    )
    params = []
    for match in pattern.finditer(outside):
        values = _parse_numeric_foreach_values(match.group(2))
        if not values:
            continue
        params.append({
            "name": match.group(1),
            "values": tuple(values),
        })
    return params[:1]


def _parse_numeric_foreach_values(raw: str) -> list[float]:
    part = raw.strip().split('\n')
    tokens = []
    for segment in part:
        tokens.extend(segment.split(','))
    tokens = [t.strip() for t in tokens if t.strip()]
    dots = [t for t in tokens if t == '...']
    if len(dots) == 1:
        idx = tokens.index('...')
        if idx > 0 and idx < len(tokens) - 1:
            start = float(tokens[idx - 1])
            end = float(tokens[idx + 1])
            step = 1.0
            if idx + 2 < len(tokens) and tokens[idx + 2] == 'by':
                if idx + 3 < len(tokens):
                    step = float(tokens[idx + 3])
            else:
                second_idx = idx + 1
                if second_idx + 1 < len(tokens) and tokens[second_idx + 1] not in ('...', 'by'):
                    step = float(tokens[second_idx + 1]) - float(tokens[second_idx])
            if abs(step) < 1e-12:
                step = 1.0 if end >= start else -1.0
            values = []
            max_count = 1000
            eps = 1e-9
            v = start
            while (step > 0 and v <= end + eps) or (step < 0 and v >= end - eps):
                values.append(round(float(v), 10))
                v += step
                if len(values) >= max_count:
                    break
            return values
    values = []
    for token in tokens:
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def _round_tex_number(value: float) -> float:
    rounded = round(float(value), 10)
    if abs(rounded - round(rounded)) < 1e-10:
        return float(round(rounded))
    return rounded


def _param_specs_from_foreach(param_sets: list[dict[str, Any]]) -> dict[str, Any]:
    if not param_sets:
        return {}
    first = param_sets[0]
    v = first["values"]
    values = list(v)
    step = _step_for_values(values)
    return {
        "name": first["name"].lstrip("\\"),
        "values": values,
        "min": values[0],
        "max": values[-1],
        "step": step,
        "value": values[0],
    }


def _step_for_values(values: list[float]) -> float:
    if len(values) < 2:
        return 1
    diffs = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    avg = sum(diffs) / len(diffs) if diffs else 1.0
    if abs(avg) < 1e-12:
        return 1.0
    return round(avg, 12)


def _page_index_for_params(
    param_sets: list[dict[str, Any]],
    params: dict[str, float],
    page_count: int,
) -> int:
    if not param_sets:
        return max(0, min(int(params.get("__page__", 0)), page_count - 1))
    first = param_sets[0]
    name = first["name"].lstrip("\\")
    v = params.get(name)
    values = list(first["values"])
    if v is not None:
        idx = min(range(len(values)), key=lambda i: abs(values[i] - v))
    else:
        idx = 0
    return max(0, min(idx, page_count - 1))


def _fitz_module():
    try:
        import fitz
        return fitz
    except ImportError:
        raise LatexEngineError("Thiếu thư viện PyMuPDF. Hãy chạy: pip install pymupdf")


def _open_fitz_pdf(pdf_bytes: bytes):
    return _fitz_module().open(stream=pdf_bytes, filetype="pdf")


def _pdf_page_count(pdf_bytes: bytes) -> int:
    doc = _open_fitz_pdf(pdf_bytes)
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def _render_pdf_page_to_qimage(
    pdf_bytes: bytes,
    page_index: int,
    size_px: tuple[int, int],
) -> QImage:
    w = max(1, int(size_px[0]))
    h = max(1, int(size_px[1]))
    fitz = _fitz_module()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        index = max(0, min(int(doc.page_count) - 1, int(page_index)))
        page = doc.load_page(index)
        rect = page.rect
        if rect.width <= 0 or rect.height <= 0:
            empty = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            empty.fill(Qt.GlobalColor.transparent)
            return empty
        scale = min(w / float(rect.width), h / float(rect.height))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True)
        fmt = QImage.Format.Format_RGB888 if pix.n == 3 else QImage.Format.Format_RGBA8888
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
        return _fit_image_to_size(img, (w, h))
    finally:
        doc.close()


def _fit_image_to_size(source: QImage, size_px: tuple[int, int]) -> QImage:
    w = max(1, int(size_px[0]))
    h = max(1, int(size_px[1]))
    if source.isNull():
        empty = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        empty.fill(Qt.GlobalColor.transparent)
        return empty
    canvas = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    scaled = source.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(canvas)
    painter.drawImage((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
    painter.end()
    return canvas
