"""TikZ code AI generation.

Uses Google Gemini to generate TikZ code from user-provided images,
then compiles it to a preview QImage.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QImage

from core.i18n import t
from core.latex_engine import LatexEngineError, _run_pdflatex, pdf_pages_to_qimages

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_TIKZ_TEMPLATE = _THIS_DIR.parent / "config" / "templates" / "extest" / "tikz_ai_wrapper.tex"
_BODY_PLACEHOLDER = "% __TIKZ_BODY__"

# ---------------------------------------------------------------------------
# Prompts & Khmer Translation Mapping
# ---------------------------------------------------------------------------

PROMPT_TIKZ_FROM_IMAGE = (
    "You are a world-class LaTeX and TikZ expert.\n"
    "Your mission is to carefully inspect the provided image and generate clean, compile-ready TikZ code "
    "that faithfully redraws the geometric figures, graphs, illustrations, diagrams, and math problems in the image.\n\n"
    "CRITICAL LANGUAGE REQUIREMENTS (STRICT ENFORCEMENT):\n"
    "1. ALL TEXT, LABELS, TITLES, QUESTION STATEMENTS, AND DESCRIPTIONS MUST BE IN 100% KHMER (ភាសាខ្មែរ).\n"
    "2. ABSOLUTELY FORBIDDEN: DO NOT USE ANY VIETNAMESE WORDS OR CHARACTERS (TUYỆT ĐỐI KHÔNG DÙNG TIẾNG VIỆT).\n"
    "   - If the input image contains Vietnamese (or any other language), TRANSLATE EVERYTHING INTO NATURAL KHMER.\n"
    "   - Examples of translation from Vietnamese to Khmer:\n"
    "     * 'Câu 1' or 'Bài 1' -> 'លំហាត់ទី ១' or 'សំនួរទី ១'\n"
    "     * 'Cho hàm số' -> 'គេឱ្យអនុគមន៍'\n"
    "     * 'có đồ thị như hình vẽ bên' or 'như hình vẽ' -> 'មានក្រាហ្វដូចបង្ហាញក្នុងរូប'\n"
    "     * 'Hỏi hàm số...' -> 'តើអនុគមន៍...'\n"
    "     * 'Hỏi...' -> 'តើ...'\n"
    "     * 'Đồ thị' -> 'ក្រាហ្វ'\n"
    "     * 'Điểm cực đại / cực tiểu' -> 'ចំណុចអតិបរមា / អប្បបរមា'\n"
    "     * 'Đồng biến / nghịch biến' -> 'កើន / ចុះ'\n"
    "     * 'Phương trình' -> 'សមីការ'\n"
    "     * 'Hình vẽ bên' -> 'រូបខាងក្រោម' or 'រូបខាងស្តាំ'\n"
    "     * 'Tam giác' -> 'ត្រីកោណ'\n"
    "     * 'Tứ giác' -> 'ចតុកោណ'\n"
    "     * 'Đường tròn' -> 'រង្វង់'\n"
    "     * 'Góc' -> 'មុំ'\n"
    "     * 'Mặt phẳng' -> 'ប្លង់'\n"
    "     * Multiple choice options A, B, C, D: keep A., B., C., D. with math expressions like $A.\\ (0; 2)$.\n"
    "3. TIKZ & LATEX STANDARDS:\n"
    "   - Output standard TikZ code. Do NOT output markdown explanation, only LaTeX/TikZ code.\n"
    "   - Shapes & Curves: Use smooth Bezier curves (.. controls ... ..) for organic shapes/curves, and exact formulas for function plots.\n"
    "   - Coordinate system: Normalized coordinate system. Respect the bounding box provided.\n"
    "   - Colors: Only use standard xcolor names (black, white, red, green, blue, cyan, magenta, yellow, orange, violet, purple, brown, gray, darkgray, lightgray) or define colors using \\definecolor{name}{HTML}{hex} before \\begin{tikzpicture}.\n"
    "   - Use \\clip and patterns/patterns.meta for hatching, NOT manual \\foreach loops with white fills.\n"
    "   - All Khmer text in nodes must be plain UTF-8 Khmer text (e.g. \\node at (0, 2) {លំហាត់ទី ១. ...};).\n"
    "Return ONLY the LaTeX TikZ code."
)


def build_normalized_region_note(
    width_px: int,
    height_px: int,
    user_context: str = "",
) -> str:
    """Build a coordinate-normalization note to attach to the Gemini prompt."""
    width_px = max(1, int(width_px))
    height_px = max(1, int(height_px))

    if width_px >= height_px:
        half_w = 5.0
        half_h = 5.0 * height_px / width_px
    else:
        half_h = 5.0
        half_w = 5.0 * width_px / height_px

    xmin, xmax = -half_w, half_w
    ymin, ymax = -half_h, half_h
    margin = max(0.35, min(half_w, half_h) * 0.1)
    sxmin, sxmax = xmin + margin, xmax - margin
    symin, symax = ymin + margin, ymax - margin

    context = user_context.strip()
    context_block = (
        f"\n**User Context / Note:** {context}\n" if context else ""
    )

    return (
        "\n**COORDINATE CONSTRAINTS (MANDATORY):**\n"
        f"- Target image size: {width_px} x {height_px} px.\n"
        "- Use normalized TikZ coordinates: origin (0,0) at center, x-axis pointing right, y-axis pointing up.\n"
        f"- Bounding box: `({xmin:.3f},{ymin:.3f}) rectangle ({xmax:.3f},{ymax:.3f})`.\n"
        f"- Safe drawing area: `({sxmin:.3f},{symin:.3f}) rectangle ({sxmax:.3f},{symax:.3f})` with {margin:.3f} margin.\n"
        f"- Set `\\path[use as bounding box] ({xmin:.3f},{ymin:.3f}) rectangle ({xmax:.3f},{ymax:.3f});` right after `\\begin{{tikzpicture}}`.\n"
        "- MANDATORY REMINDER: All text, question headers, labels, and notes MUST be in KHMER language. ZERO Vietnamese words.\n"
        f"{context_block}"
    )


_VN_PHRASES_TO_KM: list[tuple[re.Pattern, str]] = [
    # Question numbering
    (re.compile(r'\bCâu\s*(\d+)[:.]?', re.IGNORECASE), r'លំហាត់ទី \1.'),
    (re.compile(r'\bBài\s*(\d+)[:.]?', re.IGNORECASE), r'លំហាត់ទី \1.'),
    (re.compile(r'\bVí dụ\s*(\d+)[:.]?', re.IGNORECASE), r'ឧទាហរណ៍ \1.'),
    (re.compile(r'\bProblem\s*(\d+)[:.]?', re.IGNORECASE), r'លំហាត់ទី \1.'),
    (re.compile(r'\bQuestion\s*(\d+)[:.]?', re.IGNORECASE), r'សំនួរទី \1.'),
    
    # Common mathematical question prompts
    (re.compile(r'\bCho hàm số\b', re.IGNORECASE), 'គេឱ្យអនុគមន៍'),
    (re.compile(r'\bhàm số\b', re.IGNORECASE), 'អនុគមន៍'),
    (re.compile(r'\bcó đồ thị như hình vẽ bên\b', re.IGNORECASE), 'មានក្រាហ្វដូចបង្ហាញក្នុងរូបខាងក្រោម'),
    (re.compile(r'\bcó đồ thị như hình vẽ\b', re.IGNORECASE), 'មានក្រាហ្វដូចបង្ហាញក្នុងរូប'),
    (re.compile(r'\bnhư hình vẽ bên\b', re.IGNORECASE), 'ដូចរូបខាងក្រោម'),
    (re.compile(r'\bnhư hình vẽ\b', re.IGNORECASE), 'ដូចរូបខាងក្រោម'),
    (re.compile(r'\bHình vẽ bên\b', re.IGNORECASE), 'រូបភាពខាងក្រោម'),
    (re.compile(r'\bhình vẽ bên\b', re.IGNORECASE), 'រូបភាពខាងក្រោម'),
    (re.compile(r'\bHỏi hàm số\b', re.IGNORECASE), 'តើអនុគមន៍'),
    (re.compile(r'\bHỏi\b', re.IGNORECASE), 'តើ'),
    (re.compile(r'\bTính đạo hàm\b', re.IGNORECASE), 'គណនាដេរីវេ'),
    (re.compile(r'\bTính tích phân\b', re.IGNORECASE), 'គណនាអាំងតេក្រាល'),
    (re.compile(r'\bTính\b', re.IGNORECASE), 'គណនា'),
    (re.compile(r'\bTìm nghiệm\b', re.IGNORECASE), 'រកឫស'),
    (re.compile(r'\bTìm tập xác định\b', re.IGNORECASE), 'រកដែនកំណត់'),
    (re.compile(r'\bTìm giá trị lớn nhất\b', re.IGNORECASE), 'រកតម្លៃអតិបរមា'),
    (re.compile(r'\bTìm giá trị nhỏ nhất\b', re.IGNORECASE), 'រកតម្លៃអប្បបរមា'),
    (re.compile(r'\bTìm\b', re.IGNORECASE), 'រក'),
    (re.compile(r'\bĐồ thị hàm số\b', re.IGNORECASE), 'ក្រាហ្វនៃអនុគមន៍'),
    (re.compile(r'\bĐồ thị\b', re.IGNORECASE), 'ក្រាហ្វ'),
    (re.compile(r'\bđồ thị\b', re.IGNORECASE), 'ក្រាហ្វ'),
    (re.compile(r'\bBảng biến thiên\b', re.IGNORECASE), 'តារាងអថេរភាព'),
    (re.compile(r'\bbảng biến thiên\b', re.IGNORECASE), 'តារាងអថេរភាព'),
    (re.compile(r'\bTập xác định\b', re.IGNORECASE), 'ដែនកំណត់'),
    (re.compile(r'\btập xác định\b', re.IGNORECASE), 'ដែនកំណត់'),
    (re.compile(r'\bđồng biến trên khoảng\b', re.IGNORECASE), 'កើនលើចន្លោះ'),
    (re.compile(r'\bnghịch biến trên khoảng\b', re.IGNORECASE), 'ចុះលើចន្លោះ'),
    (re.compile(r'\bđồng biến\b', re.IGNORECASE), 'កើន'),
    (re.compile(r'\bnghịch biến\b', re.IGNORECASE), 'ចុះ'),
    (re.compile(r'\bcực đại\b', re.IGNORECASE), 'អតិបរមា'),
    (re.compile(r'\bcực tiểu\b', re.IGNORECASE), 'អប្បបរមា'),
    (re.compile(r'\bĐiểm cực trị\b', re.IGNORECASE), 'ចំណុចបរមា'),
    (re.compile(r'\bGiá trị cực đại\b', re.IGNORECASE), 'តម្លៃអតិបរមា'),
    (re.compile(r'\bGiá trị cực tiểu\b', re.IGNORECASE), 'តម្លៃអប្បបរមា'),
    (re.compile(r'\btiệm cận đứng\b', re.IGNORECASE), 'អាស៊ីមតូតឈរ'),
    (re.compile(r'\btiệm cận ngang\b', re.IGNORECASE), 'អាស៊ីមតូតដេក'),
    (re.compile(r'\btiệm cận\b', re.IGNORECASE), 'អាស៊ីមតូត'),
    (re.compile(r'\bPhương trình\b', re.IGNORECASE), 'សមីការ'),
    (re.compile(r'\bphương trình\b', re.IGNORECASE), 'សមីការ'),
    (re.compile(r'\bBất phương trình\b', re.IGNORECASE), 'វិសមីការ'),
    (re.compile(r'\bbất phương trình\b', re.IGNORECASE), 'វិសមីការ'),
    (re.compile(r'\bHệ phương trình\b', re.IGNORECASE), 'ប្រព័ន្ធសមីការ'),
    (re.compile(r'\bTam giác đều\b', re.IGNORECASE), 'ត្រីកោណសម័ង្ស'),
    (re.compile(r'\bTam giác vuông\b', re.IGNORECASE), 'ត្រីកោណកែង'),
    (re.compile(r'\bTam giác cân\b', re.IGNORECASE), 'ត្រីកោណសមបាត'),
    (re.compile(r'\bTam giác\b', re.IGNORECASE), 'ត្រីកោណ'),
    (re.compile(r'\btam giác\b', re.IGNORECASE), 'ត្រីកោណ'),
    (re.compile(r'\bTứ giác\b', re.IGNORECASE), 'ចតុកោណ'),
    (re.compile(r'\btứ giác\b', re.IGNORECASE), 'ចតុកោណ'),
    (re.compile(r'\bHình vuông\b', re.IGNORECASE), 'ការ៉េ'),
    (re.compile(r'\bHình chữ nhật\b', re.IGNORECASE), 'ចតុកោណកែង'),
    (re.compile(r'\bHình bình hành\b', re.IGNORECASE), 'ប្រលេឡូក្រាម'),
    (re.compile(r'\bHình thoi\b', re.IGNORECASE), 'ចតុកោណស្មើ'),
    (re.compile(r'\bHình thang\b', re.IGNORECASE), 'ចតុកោណព្នាយ'),
    (re.compile(r'\bHình chóp\b', re.IGNORECASE), 'ពីរ៉ាមីត'),
    (re.compile(r'\bHình lăng trụ\b', re.IGNORECASE), 'ព្រីស'),
    (re.compile(r'\bHình nón\b', re.IGNORECASE), 'កោន'),
    (re.compile(r'\bHình trụ\b', re.IGNORECASE), 'ស៊ីឡាំង'),
    (re.compile(r'\bHình cầu\b', re.IGNORECASE), 'ស្វ៊ែរ'),
    (re.compile(r'\bĐường tròn\b', re.IGNORECASE), 'រង្វង់'),
    (re.compile(r'\bđường tròn\b', re.IGNORECASE), 'រង្វង់'),
    (re.compile(r'\bĐường thẳng\b', re.IGNORECASE), 'បន្ទាត់'),
    (re.compile(r'\bđường thẳng\b', re.IGNORECASE), 'បន្ទាត់'),
    (re.compile(r'\bĐoạn thẳng\b', re.IGNORECASE), 'អង្កត់'),
    (re.compile(r'\bđoạn thẳng\b', re.IGNORECASE), 'អង្កត់'),
    (re.compile(r'\bTrung điểm\b', re.IGNORECASE), 'ចំណុចកណ្តាល'),
    (re.compile(r'\btrung điểm\b', re.IGNORECASE), 'ចំណុចកណ្តាល'),
    (re.compile(r'\bTrọng tâm\b', re.IGNORECASE), 'ទីប្រជុំទម្ងន់'),
    (re.compile(r'\btrọng tâm\b', re.IGNORECASE), 'ទីប្រជុំទម្ងន់'),
    (re.compile(r'\bMặt phẳng\b', re.IGNORECASE), 'ប្លង់'),
    (re.compile(r'\bmặt phẳng\b', re.IGNORECASE), 'ប្លង់'),
    (re.compile(r'\bTọa độ\b', re.IGNORECASE), 'កូអរដោណេ'),
    (re.compile(r'\btọa độ\b', re.IGNORECASE), 'កូអរដោណេ'),
    (re.compile(r'\bVectơ\b', re.IGNORECASE), 'វ៉ិចទ័រ'),
    (re.compile(r'\bvectơ\b', re.IGNORECASE), 'វ៉ិចទ័រ'),
    (re.compile(r'\bVector\b', re.IGNORECASE), 'វ៉ិចទ័រ'),
    (re.compile(r'\bvector\b', re.IGNORECASE), 'វ៉ិចទ័រ'),
    (re.compile(r'\bĐiểm\b', re.IGNORECASE), 'ចំណុច'),
    (re.compile(r'\bđiểm\b', re.IGNORECASE), 'ចំណុច'),
    (re.compile(r'\bGóc\b', re.IGNORECASE), 'មុំ'),
    (re.compile(r'\bgóc\b', re.IGNORECASE), 'មុំ'),
    (re.compile(r'\bDiện tích\b', re.IGNORECASE), 'ក្រឡាផ្ទៃ'),
    (re.compile(r'\bdiện tích\b', re.IGNORECASE), 'ក្រឡាផ្ទៃ'),
    (re.compile(r'\bThể tích\b', re.IGNORECASE), 'មាឌ'),
    (re.compile(r'\bthể tích\b', re.IGNORECASE), 'មាឌ'),
    (re.compile(r'\bChu vi\b', re.IGNORECASE), 'បរិមាត្រ'),
    (re.compile(r'\bchu vi\b', re.IGNORECASE), 'បរិមាត្រ'),
    (re.compile(r'\bKhoảng cách\b', re.IGNORECASE), 'ចម្ងាយ'),
    (re.compile(r'\bkhoảng cách\b', re.IGNORECASE), 'ចម្ងាយ'),
    (re.compile(r'\bBán kính\b', re.IGNORECASE), 'កាំ'),
    (re.compile(r'\bbán kính\b', re.IGNORECASE), 'កាំ'),
    (re.compile(r'\bĐường kính\b', re.IGNORECASE), 'អង្កត់ផ្ចិត'),
    (re.compile(r'\bđường kính\b', re.IGNORECASE), 'អង្កត់ផ្ចិត'),
    (re.compile(r'\bvới mọi\b', re.IGNORECASE), 'ចំពោះគ្រប់'),
    (re.compile(r'\btồn tại\b', re.IGNORECASE), 'មាន'),
    (re.compile(r'\bthỏa mãn\b', re.IGNORECASE), 'ផ្ទៀងផ្ទាត់'),
    (re.compile(r'\bĐáp án\b', re.IGNORECASE), 'ចម្លើយ'),
    (re.compile(r'\bđáp án\b', re.IGNORECASE), 'ចម្លើយ'),
    (re.compile(r'\bLời giải\b', re.IGNORECASE), 'ដំណោះស្រាយ'),
    (re.compile(r'\blời giải\b', re.IGNORECASE), 'ដំណោះស្រាយ'),
    (re.compile(r'\bHướng dẫn giải\b', re.IGNORECASE), 'ការណែនាំដោះស្រាយ'),
    (re.compile(r'\bchọn khẳng định đúng\b', re.IGNORECASE), 'ជ្រើសរើសការអះអាងដែលត្រឹមត្រូវ'),
    (re.compile(r'\bkhẳng định đúng\b', re.IGNORECASE), 'ការអះអាងត្រឹមត្រូវ'),
    (re.compile(r'\bkhẳng định sai\b', re.IGNORECASE), 'ការអះអាងមិនត្រឹមត្រូវ'),
    (re.compile(r'\btrong các khẳng định sau\b', re.IGNORECASE), 'ក្នុងចំណោមការអះអាងខាងក្រោម'),
    (re.compile(r'\bvới\b', re.IGNORECASE), 'ជាមួយ'),
    (re.compile(r'\blà\b', re.IGNORECASE), 'ជា'),
    (re.compile(r'\bvà\b', re.IGNORECASE), 'និង'),
    (re.compile(r'\bcủa\b', re.IGNORECASE), 'នៃ'),
    (re.compile(r'\btrên\b', re.IGNORECASE), 'លើ'),
    (re.compile(r'\bdưới\b', re.IGNORECASE), 'ក្រោម'),
    (re.compile(r'\btrong\b', re.IGNORECASE), 'ក្នុង'),
    (re.compile(r'\bngoài\b', re.IGNORECASE), 'ក្រៅ'),
    (re.compile(r'\bthuộc\b', re.IGNORECASE), 'ជារបស់'),
    (re.compile(r'\bkhông thuộc\b', re.IGNORECASE), 'មិនមែនជារបស់'),
]


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


def _read_tikz_template() -> str:
    if not _TIKZ_TEMPLATE.exists():
        raise LatexEngineError(f"Thiếu mẫu TikZ AI: {_TIKZ_TEMPLATE}")
    template = _TIKZ_TEMPLATE.read_text(encoding="utf-8")
    if _BODY_PLACEHOLDER not in template:
        raise LatexEngineError(
            f"Không tìm thấy placeholder '{_BODY_PLACEHOLDER}' "
            f"trong {_TIKZ_TEMPLATE.name}"
        )
    return template


def _strip_code_fence(raw: str | None) -> str:
    """Remove surrounding ```latex fences or leading preamble noise."""
    if not raw:
        return ""
    text = raw.strip()
    fence = re.search(
        r"```(?:latex|tex)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE
    )
    if fence:
        return fence.group(1).strip()
    doc_idx = text.find("\\documentclass")
    if doc_idx >= 0:
        return text[doc_idx:].strip()
    tikz_idx = text.find("\\begin{tikzpicture}")
    if tikz_idx >= 0:
        return text[tikz_idx:].strip()
    return text


# Map of commonly hallucinated color names to valid xcolor equivalents
_COLOR_ALIASES: dict[str, str] = {
    "inkblack": "black",
    "brightgreen": "green",
    "brightred": "red",
    "brightblue": "blue",
    "brightyellow": "yellow",
    "brightcyan": "cyan",
    "brightmagenta": "magenta",
    "darkblue": "blue!60!black",
    "darkred": "red!60!black",
    "darkgreen": "green!60!black",
    "darkyellow": "yellow!60!black",
    "lightblue": "blue!30",
    "lightred": "red!30",
    "lightgreen": "green!30",
    "lightyellow": "yellow!30",
    "deepblue": "blue!80!black",
    "deepred": "red!80!black",
    "deepgreen": "green!80!black",
}


def _extract_preamble_color_defs(code: str) -> str:
    """Extract \\definecolor and \\colorlet commands from the preamble."""
    text = _strip_code_fence(code)
    begin_idx = text.find("\\begin{document}")
    if begin_idx < 0:
        return ""
    preamble = text[:begin_idx]
    color_defs = []
    for pattern in (
        r"\\definecolor\{[^}]+\}\{[^}]+\}\{[^}]+\}",
        r"\\colorlet\{[^}]+\}\{[^}]+\}",
    ):
        for match in re.finditer(pattern, preamble):
            color_defs.append(match.group(0))
    return "\n".join(color_defs)


def _extract_document_body(code: str) -> str:
    """Extract the body content from a standalone LaTeX document."""
    text = _strip_code_fence(code)
    # Find \begin{document} ... \end{document}
    begin_idx = text.find("\\begin{document}")
    if begin_idx >= 0:
        start = begin_idx + len("\\begin{document}")
        end_idx = text.find("\\end{document}", start)
        if end_idx >= 0:
            return text[start:end_idx].strip()
    return text


def _sanitize_color_names(body: str) -> str:
    """Replace hallucinated color names with valid xcolor equivalents."""
    # Sanitize hallucinated styles like markerblack -> black
    body = re.sub(r"\bmarker([a-zA-Z]+)\b", r"\1", body)
    # Replace known invalid color names
    for bad_name, good_name in _COLOR_ALIASES.items():
        # Match color names in typical TikZ contexts: [color=X], {X}, draw=X, fill=X
        body = re.sub(
            rf"\b{re.escape(bad_name)}\b",
            good_name,
            body,
            flags=re.IGNORECASE,
        )
    return body


def clean_tikz_latex(raw: str) -> str:
    """Wrap the AI-generated body in the fixed TikZ preamble template with Khmer support."""
    preamble_colors = _extract_preamble_color_defs(raw)
    body = _extract_document_body(raw)
    body = _sanitize_color_names(body)
    # Automatically translate any leftover Vietnamese math phrases to Khmer
    for pat, rep in _VN_PHRASES_TO_KM:
        body = pat.sub(rep, body)
    # Prepend any definecolor/colorlet from the AI preamble
    if preamble_colors:
        body = preamble_colors + "\n" + body
    return _read_tikz_template().replace(_BODY_PLACEHOLDER, body)


def _run_xelatex(
    tex_name: str,
    work_dir: Path,
    *,
    log_fn: Callable[[str], None] = print,
    timeout: int = 120,
) -> Path:
    """Run xelatex for tex_name inside work_dir. Returns the PDF path."""
    import subprocess
    import os
    xelatex = shutil.which("xelatex") or "/Library/TeX/texbin/xelatex"
    cmd = [xelatex, "-interaction=nonstopmode", "-halt-on-error", tex_name]
    log_fn(f"Running: {' '.join(cmd)}")
    env = os.environ.copy()
    env["PATH"] = "/Library/TeX/texbin:" + env.get("PATH", "")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise LatexEngineError(f"xelatex timed out after {timeout}s")
    if result.returncode != 0:
        log_output = result.stdout[-3000:] if result.stdout else result.stderr[-3000:]
        log_fn(f"xelatex error:\n{log_output}")
        raise LatexEngineError(
            f"xelatex exited with code {result.returncode}\n{log_output[-800:]}"
        )
    pdf_path = work_dir / tex_name.replace(".tex", ".pdf")
    if not pdf_path.exists():
        raise LatexEngineError("xelatex did not produce a PDF file.")
    return pdf_path


def render_tikz_latex_to_qimage(
    code: str,
    *,
    dpi: int = 150,
    log_fn: Callable[[str], None] = print,
) -> QImage:
    """Compile a standalone TikZ document and return the first page as QImage."""
    tex = clean_tikz_latex(code)
    work_dir = Path(tempfile.mkdtemp(prefix="edraw_tikz_"))
    try:
        tex_name = "tikz_ai.tex"
        (work_dir / tex_name).write_text(tex, encoding="utf-8")
        log_fn(t("កំពុងចងក្រង TikZ ដោយប្រើ xelatex..."))
        pdf_path = _run_xelatex(tex_name, work_dir, log_fn=log_fn, timeout=120)
        images = pdf_pages_to_qimages(pdf_path, dpi=dpi, transparent=True)
        if not images:
            raise LatexEngineError("PDF was generated but no page images could be rendered.")
        return images[0]
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Hatching validation
# ---------------------------------------------------------------------------


def _has_forbidden_manual_hatching(code: str) -> bool:
    """Detect forbidden manual hatching patterns that the prompt forbids."""
    if not code:
        return False
    text = code
    if "\\fill[white]" in text or "\\fill [white]" in text:
        return True
    scopes = re.findall(
        r"\\begin\{scope\}(.*?)\\end\{scope\}", text, flags=re.DOTALL
    )
    for scope in scopes:
        if "\\clip" in scope and "\\foreach" in scope and "\\draw" in scope:
            return True
    return False


_MANUAL_HATCH_REPAIR_NOTE = (
    "\n\n**MANDATORY REVISION:**\n"
    "The generated code still used manual hatching or white-fills.\n"
    "Regenerate clean code obeying:\n"
    "- Do NOT use `\\foreach` to draw hatching lines inside a clip.\n"
    "- Do NOT use `\\fill[white]` to clear backgrounds.\n"
    "- All hatching must use `pattern=...` or `patterns.meta`.\n"
    "- All text MUST be 100% Khmer (ភាសាខ្មែរ). ZERO Vietnamese words.\n"
    "- Return ONLY the corrected LaTeX/TikZ code, no explanation.\n"
)


# ---------------------------------------------------------------------------
# Gemini API call
# ---------------------------------------------------------------------------


def _call_gemini_for_tikz(
    api_key: str,
    model: str,
    png_bytes: Any,
    log: Callable[[str], None] = print,
    *,
    retry_max: int = 2,
    retry_wait: float = 2.0,
    timeout_ms: int = 120000,
    prompt_note: str = "",
) -> str:
    """Call Gemini to generate TikZ code from an image, with automatic model failover."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError(
            "Missing google-genai library. Run: pip install google-genai"
        )
    from core.gemini_models import get_candidate_models, ensure_png_bytes, is_fallback_error

    raw_bytes = ensure_png_bytes(png_bytes)
    if not raw_bytes:
        raise ValueError(t("គ្មានរូបភាពសម្រាប់វិភាគ TikZ ទេ"))

    image_part = types.Part.from_bytes(data=raw_bytes, mime_type="image/png")
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout_ms),
    )
    candidates = get_candidate_models(model)
    last_err: Exception | None = None

    for m_idx, current_model in enumerate(candidates):
        is_last = (m_idx == len(candidates) - 1)
        attempts = 1 if not is_last else retry_max
        for attempt in range(1, attempts + 1):
            log(
                t(
                    "Gọi Gemini tạo TikZ ({model})...",
                    model=current_model,
                )
            )
            extra_note = _MANUAL_HATCH_REPAIR_NOTE if attempt > 1 else ""
            full_prompt = PROMPT_TIKZ_FROM_IMAGE
            if prompt_note:
                full_prompt += "\n" + prompt_note
            full_prompt += extra_note

            try:
                resp = client.models.generate_content(
                    model=current_model,
                    contents=[full_prompt, image_part],
                    config=types.GenerateContentConfig(temperature=0.25),
                )
                text = (resp.text or "").strip()
                log(t("Gemini trả về {count} ký tự.", count=len(text)))
                code = clean_tikz_latex(text)
                if _has_forbidden_manual_hatching(code) and attempt < attempts:
                    log(
                        t("រកឃើញការគូសឆ្នូតដោយដៃ ឬលុបផ្ទៃស កំពុងស្នើសុំ Gemini គូរឡើងវិញដោយ pattern...")
                    )
                    time.sleep(1)
                    continue
                return code
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


class TikzAIWorker(QObject):
    """Background worker that calls Gemini and compiles TikZ."""

    finished = pyqtSignal(str, object)  # code (str), image (QImage or None)
    failed = pyqtSignal(str)

    def __init__(
        self,
        api_key: str,
        model: str,
        png_bytes: Any,
        width_px: int = 400,
        height_px: int = 300,
        user_context: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        from core.gemini_models import ensure_png_bytes
        self._api_key = api_key
        self._model = model
        self._png_bytes = ensure_png_bytes(png_bytes)
        self._width_px = width_px
        self._height_px = height_px
        self._user_context = user_context
        self._last_code = ""

    def run(self) -> None:
        try:
            note = build_normalized_region_note(
                self._width_px, self._height_px, self._user_context
            )
            code = _call_gemini_for_tikz(
                self._api_key,
                self._model,
                self._png_bytes,
                prompt_note=note,
            )
            self._last_code = code or ""
            if not code:
                self.failed.emit(t("Gemini មិនបានបញ្ជូនទិន្នន័យមកវិញទេ"))
                return
            img = render_tikz_latex_to_qimage(code)
            self.finished.emit(code, img)
        except Exception as exc:
            self.failed.emit(str(exc))


def start_tikz_ai_worker(
    parent: QObject | None,
    worker: TikzAIWorker,
) -> QThread:
    """Launch *worker* in a new QThread and return it."""
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
