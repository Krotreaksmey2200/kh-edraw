"""core/rich_text_preprocessor.py

Split rich-text source (Markdown + LaTeX math + TikZ) into HTML suitable for
the QWebEngineView shell that renders via MathJax + TikZJax.

Source convention (same as MarkdownTypeEditor):

* Plain text: Markdown syntax.
* Math: ``$...$``, ``$$...$$``, ``\\(...\\)``, ``\\[...\\]`` — kept verbatim after
  Markdown processing, since MathJax in the WebEngine shell typesets them. Because
  Markdown treats ``\\[``, ``\\]``, ``\\(``, ``\\)`` as escape sequences for
  ``[``, ``]``, ``(``, ``)`` (and ``_``, ``*`` inside ``$x_1$`` / ``$a*b$`` become
  italic/bold), the preprocessor must PROTECT math tokens before feeding text to
  Markdown, then RESTORE them into the HTML output.
* TikZ: supports fenced blocks `````tikz ... ``` ``, raw blocks
  ``\\begin{tikzpicture}...\\end{tikzpicture}``, and short commands
  ``\\tikz ...;`` / ``\\tikz{...}``.  These are extracted BEFORE Markdown
  processing and converted to ``<script type="text/tikz">…</script>`` for TikZJax.

This module has no Qt / PyQt6 dependency and can be tested independently.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Callable

# ---------------------------------------------------------------------------
# TikZ patterns
# ---------------------------------------------------------------------------

_TIKZ_FENCE_RE = re.compile(
    r"```[ \t]*tikz\b[^\n`]*\n(.*?)\n[ \t]*```", re.DOTALL | re.IGNORECASE
)
_TIKZ_BEGIN_RE = re.compile(
    r"\\begin\s*\{\s*tikzpicture\s*\}", re.IGNORECASE
)
_TIKZ_END_RE = re.compile(
    r"\\end\s*\{\s*tikzpicture\s*\}", re.IGNORECASE
)
_TIKZ_COMMAND_RE = re.compile(r"\\tikz\b", re.IGNORECASE)

_DEFAULT_TIKZ_LIBRARIES: tuple[str, ...] = (
    "shapes.geometric", "arrows", "snakes", "shadows", "backgrounds",
    "decorations.text", "shapes", "calc", "intersections", "angles",
    "patterns", "patterns.meta", "positioning", "decorations.pathmorphing",
    "fadings", "shadings",
)

_TIKZ_LIBRARY_RE = re.compile(
    r"\\usetikzlibrary\s*(?:\[[^\]]*\]\s*)?\{([^}]*)\}",
    re.IGNORECASE | re.DOTALL,
)
_TIKZ_BEGIN_DOCUMENT_RE = re.compile(
    r"\\begin\s*\{\s*document\s*\}", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Math token patterns (order matters — longest first)
# ---------------------------------------------------------------------------

_MATH_TOKEN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\$\$(.+?)\$\$", re.DOTALL), "display_dollar"),
    (re.compile(r"\\\[(.+?)\\\]", re.DOTALL), "display_bracket"),
    (re.compile(r"\\\((.+?)\\\)", re.DOTALL), "inline_paren"),
    (re.compile(r"(?<!\\)\$([^\n$]+?)(?<!\\)\$"), "inline_dollar"),
]

_MATH_PLACEHOLDER_FMT = "\ue000MJX{idx:04d}\ue000"
_MATH_PLACEHOLDER_RE = re.compile(r"\ue000MJX(\d{4})\ue000")


@dataclass(slots=True)
class RichTextBlock:
    """A single text or tikz block."""

    kind: str  # "text" or "tikz"
    content: str


# ---------------------------------------------------------------------------
# TikZ detection helpers
# ---------------------------------------------------------------------------

def contains_tikz(source: str) -> bool:
    """Return True if *source* contains fenced / raw TikZ renderable by TikZJax."""
    if not source:
        return False
    return _find_next_tikz_block(source, 0) is not None


def split_rich_text_blocks(source: str) -> list[RichTextBlock]:
    """Split *source* into alternating text / tikz blocks, preserving order."""
    if not source:
        return []

    blocks: list[RichTextBlock] = []
    pos = 0
    n = len(source)

    while pos < n:
        tikz = _find_next_tikz_block(source, pos)
        if tikz is None:
            blocks.append(RichTextBlock(kind="text", content=source[pos:]))
            break
        start, end = tikz
        if start > pos:
            blocks.append(RichTextBlock(kind="text", content=source[pos:start]))
        blocks.append(RichTextBlock(kind="tikz", content=source[start:end]))
        pos = end

    return blocks


def _is_escaped(source: str, idx: int) -> bool:
    """Return True if the character at *idx* is escaped by an odd number of backslashes."""
    slash_count = 0
    j = idx - 1
    while j >= 0 and source[j] == "\\":
        slash_count += 1
        j -= 1
    return bool(slash_count % 2)


def _is_in_tex_comment(source: str, idx: int) -> bool:
    """Return True if position *idx* falls after an unescaped ``%`` on the same line."""
    line_start = source.rfind("\n", 0, idx) + 1
    pos = line_start
    while True:
        comment = source.find("%", pos, idx)
        if comment < 0:
            return False
        if not _is_escaped(source, comment):
            return True
        pos = comment + 1


def _search_uncommented(pattern: re.Pattern, source: str, start_pos: int) -> re.Match | None:
    """Search *source* for *pattern* starting at *start_pos*, skipping comments."""
    pos = start_pos
    match = pattern.search(source, pos)
    while match is not None:
        if not _is_in_tex_comment(source, match.start()):
            return match
        pos = match.start() + 1
        match = pattern.search(source, pos)
    return None


def _skip_line_comment(source: str, idx: int) -> int:
    newline = source.find("\n", idx)
    if newline < 0:
        return len(source)
    return newline + 1


def _skip_space_and_comments(source: str, idx: int) -> int:
    i = idx
    n = len(source)
    while i < n:
        ch = source[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "%" and not _is_escaped(source, i):
            i = _skip_line_comment(source, i)
            continue
        break
    return i


def _find_matching_delimiter(
    source: str, open_idx: int, open_ch: str, close_ch: str
) -> int | None:
    """Find the matching closing delimiter, respecting nesting and comments."""
    depth = 0
    i = open_idx
    n = len(source)
    while i < n:
        ch = source[i]
        if ch == "%" and not _is_escaped(source, i):
            i = _skip_line_comment(source, i)
            continue
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _include_trailing_tex_comment(source: str, end: int) -> int:
    """If a ``%`` comment immediately follows a TikZ command, consume it too."""
    i = end
    n = len(source)
    while i < n and source[i] in " \t":
        i += 1
    if i < n and source[i] == "%" and not _is_escaped(source, i):
        return _skip_line_comment(source, i)
    return i


def _find_tikzpicture_span(source: str, start_pos: int) -> tuple[int, int] | None:
    """Find the span of a ``\\begin{tikzpicture}...\\end{tikzpicture}`` block."""
    begin = _search_uncommented(_TIKZ_BEGIN_RE, source, start_pos)
    if begin is None:
        return None
    # Find matching \end{tikzpicture} at same nesting level
    pos = begin.end()
    end_match = _search_uncommented(_TIKZ_END_RE, source, pos)
    if end_match is None:
        return None
    return begin.start(), _include_trailing_tex_comment(source, end_match.end())


def _consume_tikz_options(source: str, idx: int) -> int:
    """Skip optional ``[...]`` arguments after ``\\tikz``."""
    i = _skip_space_and_comments(source, idx)
    n = len(source)
    if i < n and source[i] == "[":
        closing = _find_matching_delimiter(source, i, "[", "]")
        if closing is not None:
            i = _skip_space_and_comments(source, closing + 1)
    return i


def _find_tikz_statement_end(source: str, idx: int) -> int | None:
    """Find the end of a ``\\tikz ...;`` or ``\\tikz{...}`` statement."""
    brace_depth = 0
    bracket_depth = 0
    i = idx
    n = len(source)
    while i < n:
        ch = source[i]
        if ch == "%" and not _is_escaped(source, i):
            i = _skip_line_comment(source, i)
            continue
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if not _is_escaped(source, i):
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth = max(0, brace_depth - 1)
            elif ch == "[":
                bracket_depth += 1
            elif ch == "]":
                bracket_depth = max(0, bracket_depth - 1)
            elif ch == ";" and brace_depth == 0 and bracket_depth == 0:
                return _include_trailing_tex_comment(source, i + 1)
        i += 1
    return None


def _find_tikz_command_span(source: str, start_pos: int) -> tuple[int, int] | None:
    """Find the span of a ``\\tikz ...;`` or ``\\tikz{...}`` command."""
    command = _TIKZ_COMMAND_RE.search(source, start_pos)
    if command is None:
        return None
    pos = _consume_tikz_options(source, command.end())
    end = _find_tikz_statement_end(source, pos)
    if end is None:
        return None
    return command.start(), end


def _find_next_tikz_block(source: str, start_pos: int) -> tuple[int, int] | None:
    """Find the earliest TikZ block (fence / tikzpicture / command) starting at *start_pos*."""
    candidates: list[tuple[int, int]] = []

    fence = _TIKZ_FENCE_RE.search(source, start_pos)
    if fence is not None:
        candidates.append((fence.start(), fence.end()))

    tikzpic = _find_tikzpicture_span(source, start_pos)
    if tikzpic is not None:
        candidates.append(tikzpic)

    cmd = _find_tikz_command_span(source, start_pos)
    if cmd is not None:
        candidates.append(cmd)

    if not candidates:
        return None
    return min(candidates, key=lambda c: c[0])


# ---------------------------------------------------------------------------
# TikZ processing
# ---------------------------------------------------------------------------

def _escape_script_end(source: str) -> str:
    """Prevent literal ``</script>`` in TikZ from closing the wrapper."""
    return source.replace("</script", "<\\/script")


def _existing_tikz_libraries(tikz_source: str) -> set[str]:
    """Return the set of TikZ library names already declared by the user."""
    libraries: set[str] = set()
    if not tikz_source:
        return libraries
    for match in _TIKZ_LIBRARY_RE.finditer(tikz_source):
        if match.group(1):
            for name in match.group(1).split(","):
                clean = name.strip()
                if clean:
                    libraries.add(clean.lower())
    return libraries


def _with_default_tikz_libraries(tikz_source: str) -> str:
    """Inject commonly-used TikZ libraries that the user hasn't declared.

    For a full ``\\begin{document}`` block, the ``\\usetikzlibrary{...}`` line is
    placed before ``\\begin{document}``; for plain tikzpicture blocks, it goes at
    the top so TikZJax processes it first.
    """
    if not tikz_source:
        return tikz_source
    source = tikz_source
    existing = _existing_tikz_libraries(source)
    missing = [lib for lib in _DEFAULT_TIKZ_LIBRARIES if lib.lower() not in existing]
    if not missing:
        return source
    library_line = "\\usetikzlibrary{" + ",".join(missing) + "}\n"
    doc_match = _TIKZ_BEGIN_DOCUMENT_RE.search(source)
    if doc_match is not None:
        insert_pos = doc_match.start()
        return source[:insert_pos] + library_line + source[insert_pos:]
    return library_line + source


def _tikz_block_to_html(tikz_source: str) -> str:
    """Wrap TikZ source in ``<script type="text/tikz">`` for TikZJax processing."""
    safe = _escape_script_end(_with_default_tikz_libraries(tikz_source))
    return f'<div class="edraw-tikz"><script type="text/tikz">\n{safe}\n</script></div>'


# ---------------------------------------------------------------------------
# Math token protection / restoration
# ---------------------------------------------------------------------------

def _protect_math_tokens(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Replace every math token with a Private-Use placeholder.

    Returns ``(protected_text, tokens)`` where *tokens* is a list of
    ``(kind, original_full_match)`` — restoration will re-join the exact
    original delimiters.
    """
    tokens: list[tuple[str, str]] = []
    out = text
    for pattern, kind in _MATH_TOKEN_PATTERNS:
        def repl(match: re.Match, k: str = kind) -> str:
            placeholder = _MATH_PLACEHOLDER_FMT.format(idx=len(tokens))
            tokens.append((k, match.group(0)))
            return placeholder

        out = pattern.sub(repl, out)
    return out, tokens


def _restore_math_tokens(html_body: str, tokens: list[tuple[str, str]]) -> str:
    """Restore original math token delimiters into HTML that went through Markdown."""
    def repl(match: re.Match) -> str:
        try:
            idx = int(match.group(1))
            return tokens[idx][1]
        except (ValueError, IndexError):
            return match.group(0)

    return _MATH_PLACEHOLDER_RE.sub(repl, html_body)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preprocess_to_html(source: str, text_to_html: Callable[[str], str]) -> str:
    """Convert rich-text *source* to an HTML body for injection into the shell.

    ``text_to_html`` is a Markdown→HTML function (e.g. ``markdown.markdown`` or
    an internal fallback).  Math tokens are protected / restored around
    ``text_to_html`` so Markdown doesn't consume ``\\[``, ``\\]``, ``\\(``,
    ``\\)`` (see module docstring).

    Returns the HTML body string; does not include the outer container.
    """
    parts: list[str] = []
    for block in split_rich_text_blocks(source):
        if block.kind == "tikz":
            parts.append(_tikz_block_to_html(block.content))
            continue

        text = block.content
        if not text.strip():
            parts.append("")
            continue

        protected, tokens = _protect_math_tokens(text)
        try:
            rendered = text_to_html(protected)
        except Exception:
            rendered = "<pre>" + html.escape(protected) + "</pre>"

        if tokens:
            rendered = _restore_math_tokens(rendered, tokens)

        parts.append(rendered)

    return "\n".join(parts)
