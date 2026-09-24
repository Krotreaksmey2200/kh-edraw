"""Gemini-powered code assist for the figure-code dialog.

Provides prompts, response cleanup, and a background worker that calls
Gemini to generate TikZ or eDraw Python code from user requests.
"""

from __future__ import annotations

import re
import time
import traceback
from typing import Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.i18n import t

# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------


class FigureCodeMode:
    """How the AI response should be applied to the editor."""

    SNIPPET = "snippet"
    FULL = "full"


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_PROMPT_EDRAW_HEADER = (
    '\n**Role:** You are a Python graphics expert assisting eDraw users to create sandbox drawing code.\n\n'
    '**MANDATORY FILE STRUCTURE:**\n'
    '```python\n'
    'PARAMS = {\n'
    '    # "param_name": {"min": <float>, "max": <float>, "step": <float>, "value": <float>, "label": "<label_in_khmer>"},\n'
    '}\n\n'
    'def eDraw(ed, p):\n'
    '    ed.axes(-5, 5, -5, 5)\n'
    '    # ... drawing commands ...\n'
    '```\n\n'
    '**LANGUAGE REQUIREMENT:** All text labels and descriptions MUST be in KHMER (ភាសាខ្មែរ). NO VIETNAMESE.\n\n'
    '**Available `ed` API (DO NOT import):**\n'
    '- View: ed.axes, ed.view, ed.axis, ed.xlim, ed.ylim\n'
    '- Plot: ed.plot, ed.parametric, ed.curve\n'
    '- Fill: ed.fill_between, ed.area, ed.fill_under, ed.fill\n'
    '- Point & line: ed.point, ed.scatter, ed.line, ed.segment, ed.hline, ed.vline\n'
    '- Shape: ed.circle, ed.ellipse, ed.rect, ed.polygon, ed.polyline\n'
    '- Vector: ed.vector, ed.arrow\n'
    '- Text: ed.text, ed.title\n'
    '- Color: ed.hex_to_rgb\n'
    '- Math: ed.linspace, ed.meshgrid\n'
)

_PROMPT_TIKZ_HEADER = (
    '\n**Role:** You are an expert LaTeX/TikZ developer assisting eDraw users.\n\n'
    '**LANGUAGE REQUIREMENT (MANDATORY):**\n'
    '- ALL text, labels, annotations, and comments MUST BE IN KHMER (ភាសាខ្មែរ).\n'
    '- ABSOLUTELY NO VIETNAMESE WORDS OR CHARACTERS ALLOWED.\n\n'
    '**MANDATORY PREAMBLE (XeLaTeX with Khmer font):**\n'
    '```latex\n'
    '\\documentclass[tikz,border=1mm]{standalone}\n'
    '\\usepackage{amsmath,amssymb}\n'
    '\\usepackage{tikz}\n'
    '\\usetikzlibrary{arrows.meta,calc,intersections,patterns,patterns.meta,positioning,shapes.geometric,angles,quotes}\n'
    '\\usepackage{fontspec}\n'
    '\\setmainfont{Khmer OS}\n'
    '```\n'
    '- Use math mode for math symbols ($...$).\n'
    '- Avoid manual \\foreach hatching loops; use the patterns library.\n'
)

_RULES_SNIPPET = (
    '\n**MODE: SNIPPET (INSERT AT CURSOR)**\n'
    '- Return ONLY the new commands to insert at cursor position.\n'
    '- Do NOT rewrite PARAMS, def eDraw, \\documentclass, \\begin{document}.\n'
    '- Must match indentation before cursor.\n'
    '- Do NOT wrap in ``` markdown fences, NO explanations.\n'
    '- Output pure code.\n'
)

_RULES_FULL = (
    '\n**MODE: FULL (COMPLETE FILE)**\n'
    '- The editor is empty. Return the FULL file code.\n'
    '- Must follow the structure above.\n'
    '- Do NOT wrap in ``` markdown fences, NO explanations.\n'
    '- Output pure code.\n'
)

_CODE_FENCE_RE = re.compile(
    r"```(?:python|py|latex|tex|tikz)?\s*\n?(.*?)\n?```",
    flags=re.DOTALL | re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Response cleanup
# ---------------------------------------------------------------------------


def _strip_code_fence(text: str | None) -> str:
    """Strip surrounding ``` fences and return only the code."""
    if not text:
        return ""
    match = _CODE_FENCE_RE.search(text)
    if match:
        return match.group(1).rstrip()
    return text.strip()


def _strip_leading_comment_intro(text: str, backend: str) -> str:
    """Drop a single leading 'Sure, here is…' chatter line."""
    if not text:
        return text
    lines = text.split("\n", 1)
    first = lines[0].strip()
    if not first:
        return text
    # Common chatter patterns
    chatter_prefixes = [
        "sure", "here is", "here's", "certainly", "of course",
        "dưới đây", "đây là", "vâng", "chắc chắn",
    ]
    lower_first = first.lower()
    is_chatter = any(lower_first.startswith(p) for p in chatter_prefixes)
    is_comment = first.startswith("#") or first.startswith("%")
    if is_chatter or (is_comment and len(first) < 120 and len(lines) > 1):
        return lines[1] if len(lines) > 1 else ""
    return text


def clean_figure_code_response(raw: str | None, *, backend: str) -> str:
    """Run the full cleanup pipeline on Gemini's response."""
    if not raw:
        return ""
    text = _strip_code_fence(raw)
    text = _strip_leading_comment_intro(text, backend)
    if text and text.endswith("\n"):
        return text.rstrip() + "\n"
    return "\n" + text.rstrip() if text else ""


# ---------------------------------------------------------------------------
# Indent / cursor helpers
# ---------------------------------------------------------------------------


def _detect_indent(existing_code: str, cursor_offset: int) -> str:
    """Return the leading whitespace of the line at *cursor_offset*."""
    if not existing_code:
        return ""
    cursor_offset = max(0, min(len(existing_code), int(cursor_offset)))
    line_start = existing_code.rfind("\n", 0, cursor_offset) + 1
    line_end = existing_code.find("\n", cursor_offset)
    if line_end < 0:
        line_end = len(existing_code)
    line = existing_code[line_start:line_end]
    indent_chars: list[str] = []
    for ch in line:
        if ch in (" ", "\t"):
            indent_chars.append(ch)
        else:
            break
    return "".join(indent_chars)


def _split_around_cursor(text: str, cursor_offset: int) -> tuple[str, str]:
    if not text:
        return ("", "")
    cursor_offset = max(0, min(len(text), int(cursor_offset)))
    return (text[:cursor_offset], text[cursor_offset:])


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_prompt(
    *,
    backend: str,
    user_request: str,
    existing_code: str,
    cursor_offset: int,
    selection_text: str,
) -> tuple[str, str]:
    """Return ``(prompt_text, mode)`` for the Gemini call."""
    backend = (backend or "edraw").lower()
    header = _PROMPT_TIKZ_HEADER if backend == "tikz" else _PROMPT_EDRAW_HEADER
    has_code = bool((existing_code or "").strip())

    if has_code:
        mode = FigureCodeMode.SNIPPET
        before, after = _split_around_cursor(existing_code, cursor_offset)
        indent = _detect_indent(existing_code, cursor_offset)
        rules = _RULES_SNIPPET
        context_block = (
            "\n**CODE HIỆN TẠI CỦA NGƯỜI DÙNG (KHÔNG ĐƯỢC CHỈNH SỬA):**\n"
            f"```\n{existing_code.rstrip()}\n```\n\n"
            f"**Vị trí con trỏ:** offset = {cursor_offset} (0-indexed).\n\n"
            f"**INDENT_HINT:** mỗi dòng trong snippet phải bắt đầu bằng "
            f"{repr(indent)} ({len(indent)} ký tự khoảng trắng).\n\n"
            f"**Đoạn trước con trỏ (200 ký tự cuối):**\n"
            f"```\n{before[-200:]}\n```\n\n"
            f"**Đoạn sau con trỏ (200 ký tự đầu):**\n"
            f"```\n{after[:200]}\n```\n"
        )
        if (selection_text or "").strip():
            context_block += (
                "\n**Phần đang được bôi đen (người dùng muốn THAY THẾ):**\n"
                f"```\n{selection_text}\n```\n"
            )
    else:
        mode = FigureCodeMode.FULL
        rules = _RULES_FULL
        context_block = "\n**Editor đang trống.** Hãy soạn toàn bộ file.\n"

    request = (user_request or "").strip() or "(không có mô tả)"
    request_block = f"\n**YÊU CẦU CỦA NGƯỜI DÙNG:**\n{request}\n"

    prompt = header + context_block + request_block + rules
    return (prompt, mode)


# ---------------------------------------------------------------------------
# Gemini API call
# ---------------------------------------------------------------------------


def _call_gemini(
    api_key: str,
    model: str,
    prompt: str,
    log: Callable[[str], None] = print,
    *,
    timeout_ms: int = 120000,
    retry_max: int = 3,
    retry_wait: float = 10,
    temperature: float = 0.4,
) -> str:
    """Call Gemini and return the raw text response."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError(
            "Thiếu thư viện google-genai. Hãy chạy: pip install google-genai"
        )

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout_ms),
    )
    from core.gemini_models import get_candidate_models, is_fallback_error
    candidates = get_candidate_models(model)
    last_err: Exception | None = None

    for m_idx, current_model in enumerate(candidates):
        is_last = (m_idx == len(candidates) - 1)
        attempts = 1 if not is_last else retry_max
        for attempt in range(1, attempts + 1):
            log(
                t(
                    "Gọi Gemini soạn mã ({model})...",
                    model=current_model,
                )
            )
            try:
                resp = client.models.generate_content(
                    model=current_model,
                    contents=[prompt],
                    config=types.GenerateContentConfig(temperature=temperature),
                )
                text = (resp.text or "").strip()
                if text:
                    log(t("Gemini trả về {count} ký tự.", count=len(text)))
                    return text
                log("Gemini trả về rỗng, thử lại...")
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
    return ""


# ---------------------------------------------------------------------------
# Qt Worker
# ---------------------------------------------------------------------------


class FigureCodeAIWorker(QObject):
    """Background worker that calls Gemini for code generation."""

    finished = pyqtSignal(str, str)  # (code, mode)
    failed = pyqtSignal(str)

    def __init__(
        self,
        api_key: str,
        model: str,
        backend: str,
        user_request: str,
        existing_code: str,
        cursor_offset: int,
        selection_text: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api_key = api_key
        self._model = model
        self._backend = backend
        self._user_request = user_request
        self._existing_code = existing_code
        self._cursor_offset = cursor_offset
        self._selection_text = selection_text

    def run(self) -> None:
        try:
            prompt, mode = build_prompt(
                backend=self._backend,
                user_request=self._user_request,
                existing_code=self._existing_code,
                cursor_offset=self._cursor_offset,
                selection_text=self._selection_text,
            )
            raw = _call_gemini(self._api_key, self._model, prompt)
            code = clean_figure_code_response(raw, backend=self._backend)
            self.finished.emit(code, mode)
        except Exception as exc:
            self.failed.emit(str(exc))


def start_figure_code_ai_worker(
    parent: QObject | None,
    worker: FigureCodeAIWorker,
) -> QThread:
    """Launch *worker* in a new QThread."""
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
