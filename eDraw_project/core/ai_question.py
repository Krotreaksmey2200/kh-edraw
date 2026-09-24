"""core/ai_question.py

AI question generation module — Mode [C]: generate questions by topic.

Pipeline:
  1. Send scanned image region + counts of 4 question types to Gemini.
  2. Gemini returns LaTeX body with ``\\begin{ex}...\\end{ex}`` blocks
     (ex_test.sty package).
  3. Split body into individual blocks by type.
  4. Compile via the internal LaTeX engine → one QPixmap per block → insert slides.

Dependencies: google-genai, PyMuPDF, pdflatex (TeX Live/MiKTeX) — see
core/latex_engine.py.
"""
from __future__ import annotations

import re
import time
from typing import Callable

from PyQt6.QtCore import QBuffer, QIODevice, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap

from core.i18n import t


def pixmap_to_png_bytes(pix: QPixmap) -> bytes:
    """Encode a QPixmap to PNG bytes for sending to Gemini.

    IMPORTANT: must be called from the main thread (QPixmap is not thread-safe).
    The returned bytes can be used safely in any thread.
    """
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.ReadWrite)
    pix.save(buf, "PNG")
    data = bytes(buf.data())
    buf.close()
    return data


def image_to_png_bytes(img) -> bytes:
    """Encode a QImage to PNG bytes (thread-safe)."""
    from PyQt6.QtGui import QImage

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.ReadWrite)
    img.save(buf, "PNG")
    data = bytes(buf.data())
    buf.close()
    return data


# ---------------------------------------------------------------------------
# Rules & prompts
# ---------------------------------------------------------------------------

_RULES = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ទម្រង់កូដត្រឹមត្រូវ — កញ្ចប់ ex_test.sty
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[A] លទ្ធផលបញ្ចេញ
- បញ្ចេញតែ code fence ```latex ... ``` ប៉ុណ្ណោះ។ មិនត្រូវពន្យល់បន្ថែមទេ។
- ហាមដាច់ខាតបញ្ចេញ៖ \\documentclass \\usepackage \\begin{document} \\end{document} \\newpage \\clearpage \\section \\setcounter{ex}{...}
- បញ្ចេញតែប្លុក \\begin{ex}...\\end{ex} បន្តបន្ទាប់គ្នាតែប៉ុណ្ណោះ។
- ចាំបាច់ត្រូវប្រើភាសាខ្មែរ៖ គ្រប់ប្រធានលំហាត់ ជម្រើស សំណួរ ដំណោះស្រាយ ត្រូវតែសរសេរជាភាសាខ្មែរ (Khmer ភាសាខ្មែរ) ទាំងស្រុង។ ហាមដាច់ខាតប្រើភាសាវៀតណាម។

[B] រូបមន្តគណិតវិទ្យា
- គ្រប់អថេរ រូបមន្ត ស្វ័យគុណ សន្ទស្សន៍ ត្រូវតែដាក់ក្នុង $...$ ឬ \\[...\\].

[C] ប្រភេទទី ១ — \\choice (៤ ជម្រើស)
ទម្រង់៖ \\choice{<A>}{<B>}{<C>}{<D>}
ចម្លើយត្រឹមត្រូវត្រូវចាប់ផ្តើមដោយ \\True។ មិនត្រូវដាក់សញ្ញាចុច (.) នៅចុងជម្រើសទេ។
ឧទាហរណ៍៖
\\begin{ex}
រកឫសនៃសមីការ $x^2 - 5x + 6 = 0$ គឺ៖
\\choice
{$\\{1;6\\}$}
{\\True $\\{2;3\\}$}
{$\\{-2;-3\\}$}
{$\\{-1;-6\\}$}
\\loigiai{យើងមាន $(x-2)(x-3)=0 \\Rightarrow x=2$ ឬ $x=3$។}
\\end{ex}

[D] ប្រភេទទី ២ — \\choiceTF (ត្រូវ/ខុស)
ទម្រង់៖ \\choiceTF{<a>}{<b>}{<c>}{<d>}
ជម្រើសត្រូវចាប់ផ្តើមដោយ \\True។ ជម្រើសខុសគ្មាន \\True។
ដំណោះស្រាយប្រើ \\begin{itemchoice}...\\end{itemchoice} ជាមួយ \\itemch។
ឧទាហរណ៍៖
\\begin{ex}
គេឱ្យសមីការ $x^2 - 4 = 0$។ ចូរពិនិត្យមើលការអះអាងខាងក្រោម៖
\\choiceTF
{សមីការមានឫស $x=2$}
{\\True សមីការមានឫសពីរ $x=\\pm 2$}
{សមីការគ្មានឫស}
{\\True សំណុំឫសគឺ $\\{-2;2\\}$}
\\loigiai{
\\begin{itemchoice}
\\itemch មិនពិត៖ ខ្វះឫស $x=-2$។
\\itemch ពិត៖ $(x-2)(x+2)=0$។
\\itemch មិនពិត៖ សមីការមានឫសពីរ។
\\itemch ពិត៖ សំណុំឫស $\\{-2;2\\}$។
\\end{itemchoice}
}
\\end{ex}

[E] ប្រភេទទី ៣ — \\shortans (ចម្លើយខ្លី)
ទម្រង់៖ \\shortans{$<ចម្លើយ>$}
ដាក់នៅពីមុខ \\loigiai ភ្លាមៗ។
ឧទាហរណ៍៖
\\begin{ex}
គណនាតម្លៃ $P = 3^2 + 4^2$។
\\shortans{$25$}
\\loigiai{យើងមាន $P = 9 + 16 = 25$។}
\\end{ex}

[F] ប្រភេទទី ៤ — ស្វ័យដោះស្រាយ
មានតែ \\loigiai{...}។ មិនមាន \\choice, \\choiceTF, \\shortans ឡើយ។
ឧទាហរណ៍៖
\\begin{ex}
ដោះស្រាយវិសមីការ $2x - 6 > 0$។
\\loigiai{យើងមាន $2x > 6 \\Rightarrow x > 3$។ ដូច្នេះសំណុំចម្លើយគឺ $S = (3; +\\infty)$។}
\\end{ex}
"""

PROMPT_TOPIC = (
    "អ្នកគឺជាគ្រូបង្រៀនគណិតវិទ្យាជំនាញ និងជាអ្នករៀបចំ LaTeX គណិតវិទ្យាជាភាសាខ្មែរ (Khmer Math Teacher)។\n"
    "ភារកិច្ច៖ វិភាគរូបភាពគំរូ និងប្រធានបទ រួចតែងលំហាត់ថ្មីជាភាសាខ្មែរ (Khmer Language) ទាំងស្រុង។\n"
    "តម្រូវការចាំបាច់បំផុត៖\n"
    "1. គ្រប់អត្ថបទលំហាត់ ជម្រើស សំណួរ និងដំណោះស្រាយ ត្រូវតែសរសេរជាភាសាខ្មែរ (Khmer) ទាំងស្រុង។ ហាមដាច់ខាតសរសេរជាភាសាវៀតណាម។\n"
    "2. រូបមន្តគណិតវិទ្យា និមិត្តសញ្ញា និងអថេរ ត្រូវដាក់ក្នុង $...$ ឬ \\[...\\].\n"
    "3. គោរពតាមទម្រង់កញ្ចប់ ex_test.sty ឱ្យបានត្រឹមត្រូវបំផុត៖ \\begin{ex}...\\end{ex}។\n"
    + _RULES
)


# ---------------------------------------------------------------------------
# LaTeX helpers
# ---------------------------------------------------------------------------

def clean_latex(raw: str) -> str:
    """Strip code-fence ```latex ... ``` and preamble if present."""
    if not raw:
        return ""
    text = raw.strip()
    # Handle ```latex ... ```
    if "```latex" in text:
        text = text.split("```latex", 1)[1]
        if "```" in text:
            text = text.split("```", 1)[0]
    elif text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
    text = text.strip()
    # Remove \begin{document} / \end{document}
    if "\\begin{document}" in text:
        text = text.split("\\begin{document}", 1)[1]
    if "\\end{document}" in text:
        text = text.split("\\end{document}", 1)[0]
    # Remove leading/trailing blank lines
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def split_blocks(body: str) -> list[str]:
    """Split body into individual ``\\begin{ex}...\\end{ex}`` blocks."""
    return re.findall(r"\\begin\{ex\}.*?\\end\{ex\}", body, flags=re.DOTALL)


_RE_ESCAPED = re.compile(r"\\.")


def _count_dollars(text: str) -> int:
    """Count unescaped ``$`` characters in *text*."""
    count = 0
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == "$":
            count += 1
            i += 1
        else:
            i += 1
    return count


def sanitize_block(block: str) -> str:
    """Pre-process a ``\\begin{ex}...\\end{ex}`` block from Gemini to match
    the ex_test.sty interface before LaTeX compilation."""
    # Remove \setcounter{ex}{…}
    block = re.sub(r"\\setcounter\{ex\}\{[^}]*\}[\s]*", "", block)
    # Remove optional argument from \loigiai[…]
    block = re.sub(r"(\\loigiai)\s*\[[^\]]*\]", r"\1", block)
    # Remove document-level commands that should not appear inside \begin{ex}
    block = re.sub(r"\\documentclass\b[^\n]*", "", block)
    block = re.sub(r"\\usepackage\b[^\n]*", "", block)
    block = re.sub(r"\\begin\{document\}", "", block)
    block = re.sub(r"\\end\{document\}", "", block)
    # Strip trailing period in choices
    block = _strip_trailing_period_in_choices(block)
    # Balance unclosed \begin{listEX}
    n_open = len(re.findall(r"\\begin\{listEX\}", block))
    n_close = len(re.findall(r"\\end\{listEX\}", block))
    if n_open > n_close:
        block = re.sub(
            r"(?=\\loigiai|\\end\{ex\})",
            "\\end{listEX}\n",
            block,
            count=n_open - n_close,
        )
    # Fix odd number of unescaped $
    inner = block
    if _count_dollars(inner) % 2 == 1:
        block = re.sub(r"(\\end\{ex\})", r"$\1", block)
    # Balance unclosed \begin{itemchoice}
    n_ic_open = len(re.findall(r"\\begin\{itemchoice\}", block))
    n_ic_close = len(re.findall(r"\\end\{itemchoice\}", block))
    if n_ic_open > n_ic_close:
        block = re.sub(
            r"(?=\\end\{ex\})",
            "\\end{itemchoice}\n",
            block,
            count=n_ic_open - n_ic_close,
        )
    return block.strip()


def _strip_trailing_period_in_choices(block: str) -> str:
    """Remove trailing ``.`` from each ``{}`` option of ``\\choice`` / ``\\choiceTF``."""
    result: list[str] = []
    i = 0
    n = len(block)
    after_choice = False
    while i < n:
        m = re.match(r"\\(choiceTF|choice)\b", block[i:])
        if m:
            result.append(block[i : i + m.end()])
            i += m.end()
            after_choice = True
            continue
        if after_choice and block[i] == "{":
            depth = 0
            j = i
            while j < n:
                if block[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if block[j] == "{":
                    depth += 1
                elif block[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            inner = block[i + 1 : j]
            inner = inner.rstrip()
            if inner.endswith("."):
                inner = inner[:-1].rstrip()
            result.append("{" + inner + "}")
            i = j + 1
            continue
        if after_choice and block[i] not in (" ", "\t", "\n", "\r"):
            after_choice = False
        result.append(block[i])
        i += 1
    return "".join(result)


def sanitize_blocks(blocks: list[str]) -> list[str]:
    """Sanitize all blocks."""
    return [sanitize_block(b) for b in blocks]


# ---------------------------------------------------------------------------
# Gemini API
# ---------------------------------------------------------------------------

def _call_gemini(
    api_key: str,
    model: str,
    prompt: str,
    image_part: Any,
    log: Callable[[str], None],
    *,
    temperature: float = 0.4,
    retry_max: int = 2,
    retry_wait: int = 2,
    timeout_ms: int = 120_000,
) -> str:
    """Call Gemini API with text + image, with automatic model fallback."""
    from google import genai
    from google.genai import types
    from core.gemini_models import get_candidate_models, ensure_png_bytes, is_fallback_error

    img_bytes = ensure_png_bytes(image_part)
    parts = []
    if img_bytes:
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/png"))
    parts.append(types.Part.from_text(text=prompt))

    candidates = get_candidate_models(model)
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))
    last_exc: Exception | None = None

    for m_idx, current_model in enumerate(candidates):
        is_last = (m_idx == len(candidates) - 1)
        attempts = 1 if not is_last else retry_max
        for attempt in range(1, attempts + 1):
            try:
                log(f"កំពុងទាក់ទង Gemini ({current_model}) …")
                response = client.models.generate_content(
                    model=current_model,
                    contents=types.Content(role="user", parts=parts),
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                    ),
                )
                text = response.text or ""
                if text.strip():
                    return text
            except Exception as exc:
                last_exc = exc
                err_msg = str(exc)
                log(f"Gemini {current_model} (លើកទី {attempt}): {err_msg[:120]}")
                if is_fallback_error(exc) and not is_last:
                    next_model = candidates[m_idx + 1]
                    log(f"→ ប្តូរដោយស្វ័យប្រវត្តិទៅកាន់ម៉ូដែល៖ {next_model} …")
                    break
                if attempt < attempts:
                    time.sleep(retry_wait)

    if last_exc:
        raise RuntimeError(f"Gemini failed: {last_exc}")
    raise RuntimeError("Gemini មិនបានបញ្ជូនទិន្នន័យមកវិញទេ។")



# ---------------------------------------------------------------------------
# Prompt building & classification
# ---------------------------------------------------------------------------

_KIND_LABEL = {
    "choice": r"សំណួរពហុជ្រើសរើស (\choice)",
    "tf": r"សំណួរ ត្រូវ/ខុស (\choiceTF)",
    "short": r"សំណួរចម្លើយខ្លី (\shortans)",
    "long": "សំណួរស្វ័យដោះស្រាយ",
}
_BATCH_SIZE = 6


def _mk_prompt(counts: dict, topic_hint: str, batch_index: int, batch_total: int) -> str:
    items: list[str] = []
    if counts.get("choice"):
        items.append(f"{counts['choice']} លំហាត់ \\choice (4 ជម្រើស)")
    if counts.get("tf"):
        items.append(f"{counts['tf']} លំហាត់ \\choiceTF (ត្រូវ/ខុស)")
    if counts.get("short"):
        items.append(f"{counts['short']} លំហាត់ \\shortans (ចម្លើយខ្លី)")
    if counts.get("long"):
        items.append(f"{counts['long']} លំហាត់ស្វ័យដោះស្រាយ")
    if not topic_hint:
        topic_hint = ""
    topic_note = f" ប្រធានបទបន្ថែម៖ {topic_hint.strip()}។" if topic_hint.strip() else ""
    batch_note = f" ក្រុម {batch_index}/{batch_total}។" if batch_total > 1 else ""
    return (
        f"ពីប្រធានបទក្នុងរូបភាពគំរូ ចូរតែង {' និង '.join(items)} ជាភាសាខ្មែរ (Khmer Language)។"
        f"{topic_note}{batch_note}"
        " ប្រសិនបើសំណួរត្រូវការរូបភាព/ដ្យាក្រាម/តារាងអថេរភាព ត្រូវតែគូរដោយ TikZ/tkz-euclide/tkz-tab។ "
        "បញ្ចេញតែប្លុក \\begin{ex}...\\end{ex} ប៉ុណ្ណោះ មិនត្រូវបញ្ចេញ preamble, \\section, \\documentclass ឡើយ។ "
        "សំខាន់បំផុត៖ ត្រូវតែសរសេរជាភាសាខ្មែរ (Khmer Unicode) ទាំងស្រុង។ ហាមដាច់ខាតសរសេរជាភាសាវៀតណាម។ "
        "លេខទិន្នន័យត្រូវខុសពីគំរូ។"
    )


def _classify_block(block: str) -> str:
    if "\\choiceTF" in block:
        return "tf"
    if "\\choice" in block:
        return "choice"
    if "\\shortans" in block:
        return "short"
    return "long"


def generate_blocks(
    api_key: str,
    model: str,
    png_bytes: bytes,
    counts: dict[str, int],
    topic_hint: str,
    log: Callable[[str], None],
) -> list[str]:
    """Call Gemini to generate LaTeX blocks. Auto-batches when total > BATCH_SIZE.

    Receives ``png_bytes`` (not QPixmap) for safe background-thread usage.
    Returns a sorted list of ``\\begin{ex}...\\end{ex}`` blocks that have been
    cleaned, ordered: choice → tf → short → long.
    """
    total = sum(v for v in counts.values() if v)
    if total <= 0:
        return []

    batches: list[dict[str, int]] = []
    remaining = dict(counts)
    while sum(remaining.values()) > 0:
        batch: dict[str, int] = {}
        for kind in ("choice", "tf", "short", "long"):
            take = min(remaining.get(kind, 0), _BATCH_SIZE - sum(batch.values()))
            if take > 0:
                batch[kind] = take
                remaining[kind] -= take
            if sum(batch.values()) >= _BATCH_SIZE:
                break
        if batch:
            batches.append(batch)

    all_blocks: list[str] = []
    batch_total = len(batches)
    for idx, batch_counts in enumerate(batches, 1):
        prompt = _mk_prompt(batch_counts, topic_hint, idx, batch_total)
        full_prompt = PROMPT_TOPIC + "\n" + prompt
        log(f"Gemini batch {idx}/{batch_total} …")
        raw = _call_gemini(api_key, model, full_prompt, png_bytes, log)
        cleaned = clean_latex(raw)
        blocks = split_blocks(cleaned)
        all_blocks.extend(sanitize_blocks(blocks))

    def _sort_key(block: str) -> int:
        kind = _classify_block(block)
        order = {"choice": 0, "tf": 1, "short": 2, "long": 3}
        return order.get(kind, 99)

    all_blocks.sort(key=_sort_key)
    return all_blocks


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class AIQuestionWorker(QObject):
    """Worker that generates AI questions in a background thread."""

    finished = pyqtSignal(list)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        api_key: str,
        model: str,
        png_bytes: Any,
        counts: dict[str, int],
        topic_hint: str = "",
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        from core.gemini_models import ensure_png_bytes
        self._api_key = api_key
        self._model = model
        self._png_bytes = ensure_png_bytes(png_bytes)
        self._counts = counts
        self._topic_hint = topic_hint

    def run(self):
        """Entry point — called when the QThread starts."""
        try:
            self.progress.emit("កំពុងទាក់ទង Gemini …")
            blocks = generate_blocks(
                self._api_key,
                self._model,
                self._png_bytes,
                self._counts,
                self._topic_hint,
                lambda msg: self.progress.emit(msg),
            )
            if not blocks:
                self.finished.emit([])
                return
            self.progress.emit("កំពុងចងក្រង LaTeX …")
            from core.latex_engine import render_blocks_to_qimages
            images = render_blocks_to_qimages(blocks, log_fn=lambda msg: self.progress.emit(msg))
            self.finished.emit(images)
        except Exception as exc:
            self.failed.emit(str(exc))


def start_worker(parent: QObject, worker: AIQuestionWorker) -> QThread:
    """Launch *worker* in a new QThread, auto-clean when done."""
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
