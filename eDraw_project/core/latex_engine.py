"""LaTeX compilation engine for eDraw.

Compiles LaTeX blocks (``\\begin{ex}...\\end{ex}`` from the ``ex_test.sty``
package) into QPixmap images for slide insertion.

Pipeline (batch one-shot compile):
  1. All blocks are concatenated into a single ``.tex`` file using the
     ``templates/extest/slide_wrapper.tex`` template (standalone class +
     tcolorbox frame).
  2. A single ``pdflatex`` run produces a multi-page PDF.
  3. PyMuPDF (``fitz``) opens the PDF → ``list[QImage]`` (one image per page).

Requirements:
  - ``pdflatex`` (TeX Live, MiKTeX, …) in PATH.
  - ``pymupdf``: ``pip install pymupdf``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QImage

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_TEMPLATE_DIR = _THIS_DIR.parent / "config" / "templates" / "extest"
_TEMPLATE_TEX = _TEMPLATE_DIR / "slide_wrapper.tex"
_TEMPLATE_STY = _TEMPLATE_DIR / "ex_test.sty"
_BODY_PLACEHOLDER = "% __SLIDE_BODY__"
_ORG = "eDraw"
_APP = "eDraw"


# ---------------------------------------------------------------------------
# pdflatex command management
# ---------------------------------------------------------------------------


def load_pdflatex_command() -> str:
    """Load the user-configured pdflatex command from QSettings."""
    s = QSettings(_ORG, _APP)
    return str(s.value("latex/pdflatex_path", "") or "").strip()


def default_pdflatex_command() -> str:
    # Prefer xelatex for native Unicode & Khmer font support
    xe, _ = _resolve_pdflatex_executable("xelatex")
    if xe:
        return f"{xe} -interaction=nonstopmode %.tex"
    exe = "pdflatex.exe" if os.name == "nt" else "pdflatex"
    return f"{exe} -synctex=1 -interaction=nonstopmode %.tex"


def display_pdflatex_command() -> str:
    configured = load_pdflatex_command()
    if configured:
        return configured
    return default_pdflatex_command()


def save_pdflatex_command(command: str) -> None:
    """Persist the user-configured pdflatex command to QSettings."""
    s = QSettings(_ORG, _APP)
    s.setValue("latex/pdflatex_path", command.strip() if command else "")


# ---------------------------------------------------------------------------
# pdflatex resolution
# ---------------------------------------------------------------------------


def _extract_pdflatex_executable(command: str) -> str:
    """Extract the executable name from a pdflatex command string."""
    if not command:
        return "pdflatex"
    parts = command.strip().split()
    if parts:
        return parts[0]
    return "pdflatex"


def _has_path_separator(value: str) -> bool:
    return os.sep in value or (os.altsep and os.altsep in value)


def _macos_tex_search_dirs() -> list[Path]:
    """Common TeX locations on macOS that may be missing from PATH."""
    if sys.platform != "darwin":
        return []
    dirs: list[Path] = [Path("/Library/TeX/texbin")]
    texlive_root = Path("/usr/local/texlive")
    try:
        year_dirs = sorted(
            texlive_root.iterdir(),
            key=lambda p: int(p.name) if p.name.isdigit() else 0,
            reverse=True,
        )
        for year_dir in year_dirs:
            bin_root = year_dir / "bin"
            if bin_root.is_dir():
                for arch_dir in bin_root.iterdir():
                    if arch_dir.is_dir():
                        dirs.append(arch_dir)
    except OSError:
        pass
    dirs.extend([
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        Path("/opt/local/bin"),
    ])
    return dirs


def _pdflatex_search_path(extra_dirs: list[Path] | None = None) -> str:
    """Build a PATH string that includes common TeX locations."""
    parts: list[str] = []
    if extra_dirs:
        parts.extend(str(d) for d in extra_dirs if d.is_dir())
    if sys.platform == "darwin":
        parts.extend(str(d) for d in _macos_tex_search_dirs() if d.is_dir())
    parts.append(os.environ.get("PATH", ""))
    return os.pathsep.join(parts)


def _pdflatex_env(extra_dirs: list[Path] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = _pdflatex_search_path(extra_dirs)
    return env


def _resolve_pdflatex_executable(cmd: str) -> tuple[str | None, list[str]]:
    """Resolve the pdflatex executable to an absolute path.

    Returns ``(resolved_path_or_None, tried_paths)``.
    """
    tried: list[str] = []
    if not cmd:
        cmd = "pdflatex"
    exe = _extract_pdflatex_executable(cmd)
    if _has_path_separator(exe):
        if Path(exe).is_file():
            return exe, tried
        tried.append(exe)
        return None, tried

    extra_dirs: list[Path] = []
    if sys.platform == "darwin":
        extra_dirs = _macos_tex_search_dirs()

    env = _pdflatex_env(extra_dirs)
    search_path = env.get("PATH", "")
    for directory in search_path.split(os.pathsep):
        if not directory:
            continue
        candidate = os.path.join(directory, exe)
        tried.append(candidate)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate, tried
    return None, tried


def get_pdflatex_command() -> str:
    """Return the configured pdflatex command string."""
    return _extract_pdflatex_executable(display_pdflatex_command())


def check_pdflatex() -> tuple[bool, str]:
    """Check if pdflatex is available. Returns ``(found, path_or_empty)``."""
    cmd = get_pdflatex_command()
    resolved, _tried = _resolve_pdflatex_executable(cmd)
    return (resolved is not None, resolved or "")


def _hidden_kwargs() -> dict:
    """Return subprocess kwargs to suppress the console window on Windows."""
    if os.name != "nt":
        return {}
    info = subprocess.STARTUPINFO()
    return {"startupinfo": info, "creationflags": subprocess.CREATE_NO_WINDOW}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class LatexEngineError(RuntimeError):
    """Raised when LaTeX compilation fails."""


@dataclass
class CompileResult:
    """Result of a LaTeX compilation."""

    pdf_path: Path
    images: list[QImage]


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


def _read_template() -> str:
    if not _TEMPLATE_TEX.exists():
        raise LatexEngineError(f"រកមិនឃើញគំរូឯកសារ: {_TEMPLATE_TEX}")
    if not _TEMPLATE_STY.exists():
        raise LatexEngineError(f"រកមិនឃើញកញ្ចប់ ex_test.sty នៅ: {_TEMPLATE_STY}")
    return _TEMPLATE_TEX.read_text(encoding="utf-8")


def _build_standalone_tex(block: str) -> str:
    """Build a standalone ``.tex`` string for a single block."""
    template = _read_template()
    if _BODY_PLACEHOLDER not in template:
        raise LatexEngineError(
            f"រកមិនឃើញ placeholder '{_BODY_PLACEHOLDER}' "
            "ក្នុង slide_wrapper.tex ទេ"
        )
    return template.replace(_BODY_PLACEHOLDER, block.strip())


def _build_batch_tex(blocks: list[str]) -> str:
    """Merge all blocks into a single ``.tex`` file.

    The ``standalone`` class automatically splits each ``tikzpicture`` node
    onto its own PDF page — no manual ``\\newpage`` needed.
    """
    template = _read_template()
    if _BODY_PLACEHOLDER not in template:
        raise LatexEngineError(
            f"រកមិនឃើញ placeholder '{_BODY_PLACEHOLDER}' "
            "ក្នុង slide_wrapper.tex ទេ"
        )
    body = "\n\n".join(b.strip() for b in blocks if b.strip())
    return template.replace(_BODY_PLACEHOLDER, body)


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


def _run_pdflatex(
    tex_name: str,
    work_dir: Path,
    *,
    log_fn: callable = print,
    timeout: int = 120,
    debug_save_dir: Path | None = None,
) -> Path:
    """Run ``pdflatex`` for *tex_name* inside *work_dir*.  Returns the PDF path."""
    configured_pdflatex = get_pdflatex_command()
    pdflatex, tried = _resolve_pdflatex_executable(configured_pdflatex)
    if not pdflatex:
        pdflatex = configured_pdflatex

    candidates = [pdflatex]
    if "xelatex" not in pdflatex.lower():
        xe_alt, _ = _resolve_pdflatex_executable("xelatex")
        if xe_alt and xe_alt not in candidates:
            candidates.append(xe_alt)
    elif "pdflatex" not in pdflatex.lower():
        pdf_alt, _ = _resolve_pdflatex_executable("pdflatex")
        if pdf_alt and pdf_alt not in candidates:
            candidates.append(pdf_alt)

    last_err = ""
    for current_exe in candidates:
        cmd = [current_exe, "-interaction=nonstopmode", "-halt-on-error", tex_name]
        extra_path_dirs: list[Path] = []
        if _has_path_separator(current_exe):
            extra_path_dirs = [Path(current_exe).parent]
        env = _pdflatex_env(extra_path_dirs)
        kwargs = _hidden_kwargs()
        log_fn(f"Running: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                **kwargs,
            )
            if result.returncode == 0:
                break
            last_err = result.stdout[-500:] if result.stdout else (result.stderr[-500:] if result.stderr else "")
            log_fn(f"⚠ {Path(current_exe).name} failed (code {result.returncode}), trying fallback if available...")
        except subprocess.TimeoutExpired as exc:
            raise LatexEngineError(f"{Path(current_exe).name} timed out after {timeout}s") from exc
        except FileNotFoundError:
            continue
    else:
        raise LatexEngineError(f"LaTeX compilation failed: {last_err[-200:]}")

    pdf_path = work_dir / tex_name.replace(".tex", ".pdf")
    if not pdf_path.exists():
        raise LatexEngineError(f"មិនមានឯកសារ PDF ទេ: {pdf_path}")

    if debug_save_dir is not None:
        debug_save_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf_path, debug_save_dir / pdf_path.name)

    return pdf_path


def pdf_pages_to_qimages(
    pdf_path: Path,
    *,
    dpi: int = 150,
    transparent: bool = True,
) -> list[QImage]:
    """Open a PDF and return a list of ``QImage`` (one per page).

    Thread-safe: does not use ``QPixmap``.
    """
    try:
        import fitz  # type: ignore[import-untyped]
    except ImportError as exc:
        raise LatexEngineError(
            "ខ្វះបណ្ណាល័យ PyMuPDF។ សូមដំឡើង: pip install pymupdf"
        ) from exc

    images: list[QImage] = []
    doc = fitz.open(str(pdf_path))
    try:
        for page in doc:
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            mp = page.get_pixmap(matrix=mat, alpha=transparent)
            fmt = (
                QImage.Format.Format_RGB888 if mp.n == 3
                else QImage.Format.Format_RGBA8888
            )
            img = QImage(mp.samples, mp.width, mp.height, mp.stride, fmt).copy()
            images.append(img)
    finally:
        doc.close()
    return images


# ---------------------------------------------------------------------------
# Batch compilation
# ---------------------------------------------------------------------------


def render_blocks_to_qimages(
    blocks: list[str],
    *,
    dpi: int = 150,
    log_fn: callable = print,
) -> list[QImage]:
    """Compile all blocks in a **single** pdflatex run.

    Falls back to per-block compilation if the batch fails.
    """
    if not blocks:
        return []
    total = len(blocks)
    work_dir = Path(tempfile.mkdtemp(prefix="edraw_latex_"))

    try:
        shutil.copy2(_TEMPLATE_STY, work_dir / "ex_test.sty")

        # --- Batch attempt ---
        log_fn(f"កំពុងបញ្ចូល {total} សំណួរទៅក្នុងឯកសារ .tex តែមួយដើម្បីចងក្រង...")
        tex_name = "slides_batch.tex"
        (work_dir / tex_name).write_text(_build_batch_tex(blocks), encoding="utf-8")

        try:
            log_fn("កំពុងចងក្រង LaTeX (១ លើកសម្រាប់សំណួរទាំងអស់)...")
            pdf_path = _run_pdflatex(tex_name, work_dir, log_fn=log_fn)
            log_fn("កំពុងបម្លែងទំព័រ PDF នីមួយៗជារូបភាព...")
            images = pdf_pages_to_qimages(pdf_path, dpi=dpi)
            log_fn(f"បានបញ្ចប់: {len(images)} រូបភាព ពី {total} សំណួរ (ចងក្រង ១ លើក)។")
            return images
        except LatexEngineError as batch_err:
            log_fn(f"⚠ ការចងក្រងជាក្រុមបរាជ័យ: {str(batch_err)[:200]}")
            log_fn("→ កំពុងប្តូរទៅចងក្រងម្តងមួយសំណួរ (សំណួរដែលមានកំហុសនឹងត្រូវរំលង)...")

        # --- Fallback: per-block ---
        images: list[QImage] = []
        debug_dir = _THIS_DIR.parent / "debug_latex"
        fallback_dir = Path(tempfile.mkdtemp(prefix="edraw_fb_"))
        try:
            shutil.copy2(_TEMPLATE_STY, fallback_dir / "ex_test.sty")
            for i, block in enumerate(blocks, 1):
                tex_name_i = f"q{i:03d}.tex"
                (fallback_dir / tex_name_i).write_text(
                    _build_standalone_tex(block), encoding="utf-8"
                )
                try:
                    pdf_i = _run_pdflatex(
                        tex_name_i, fallback_dir,
                        log_fn=log_fn, debug_save_dir=debug_dir,
                    )
                    imgs_i = pdf_pages_to_qimages(pdf_i, dpi=dpi)
                    images.extend(imgs_i)
                    log_fn(f"   ✓ សំណួរ {i}/{total}: ជោគជ័យ ({len(imgs_i)} ទំព័រ)")
                except LatexEngineError as e:
                    log_fn(f"   ✗ សំណួរ {i}/{total}: កំហុស (រំលង) — {str(e)[:120]}")
                    continue
        finally:
            shutil.rmtree(fallback_dir, ignore_errors=True)

        if images:
            log_fn(f"បានបញ្ចប់: {len(images)} រូបភាពជោគជ័យ / {total} សំណួរ។")
        else:
            raise LatexEngineError(
                f"ការចងក្រងសំណួរទាំង {total} មិនជោគជ័យទេ។ "
                "សូមពិនិត្យមើលខ្លឹមសារកូដ LaTeX ពី Gemini ម្តងទៀត។"
            )
        return images
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
