"""Sandbox checks for user-authored Python figure code.

Two layers, applied in order:

1. **Regex pass** (defence-in-depth) -- catches obvious forbidden tokens
   (`open`, `exec`, `subprocess`, `__class__`, ...) before the source even
   reaches `ast.parse`.  Mirrors `core.custom_curve_tool._FORBIDDEN_RE`.

2. **AST walk** -- parses the source and rejects:
     * `Import` / `ImportFrom` whose top-level name is not in `allow_modules`
     * Any `Attribute` access whose name starts with `_` (blocks dunder probing)
     * `range(N)` where `N > MAX_LOOP_COUNT` (prevents huge user loops)

Neither layer is a hardened security boundary -- combined with restricted
`__builtins__` in the backend's sandbox globals, however, they block the
common patterns that would let user code reach the filesystem, network, or
process control.
"""
from __future__ import annotations

import ast
import re

__all__ = ["SandboxError", "validate_source"]

_MAX_LOOP_COUNT = 100_000


class SandboxError(ValueError):
    """Raised when user code contains forbidden patterns."""


_FORBIDDEN_BASE = (
    "exec",
    "eval",
    "compile",
    "open",
    "input",
    "breakpoint",
    "exit",
    "quit",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "subprocess",
    "sys",
    "os",
    "socket",
    "urllib",
    "requests",
    "pathlib",
    "threading",
    "ctypes",
    "shutil",
    "tempfile",
    "multiprocessing",
    "asyncio",
    "signal",
)

_ALWAYS_ALLOWED_MODULES = frozenset({"math"})

_DUNDER_RE = re.compile(r"\b__\w+__\b")


def _build_import_regex(allow_modules=None):
    """Build a regex that matches ``import X`` / ``from X import ...`` for any
    module NOT in *allow_modules*."""
    if not allow_modules:
        return re.compile(
            r"\b(?:import\s+\w+|from\s+\w+\s+import)\b"
        )
    allowed = "|".join(sorted(allow_modules))
    return re.compile(
        rf"\b(?:import\s+(?!(?:{allowed})\b)\w+"
        rf"|from\s+(?!(?:{allowed})\b)\w+\s+import)\b"
    )


def _build_forbidden_regex(extra_allowed=None):
    """Build a regex matching forbidden tokens (excluding any in *extra_allowed*)."""
    forbidden = [t for t in _FORBIDDEN_BASE if t not in (extra_allowed or set())]
    if not forbidden:
        return re.compile(r"$.")  # matches nothing
    pattern = r"\b(?:" + "|".join(re.escape(t) for t in forbidden) + r")\b"
    return re.compile(pattern)


def validate_source(code, *, allow_modules):
    """Reject *code* if it contains forbidden patterns.

    *allow_modules* is the set of module names this backend permits in
    ``import`` / ``from ... import ...`` statements.  ``math`` is always
    allowed.  Token-level blocks (open, exec, subprocess...) cannot be
    re-allowed by this argument.

    Raises :class:`SandboxError` with a short token/diagnostic on rejection.
    """
    if not isinstance(code, str):
        raise SandboxError("Source code must be a string.")

    effective_allowed = frozenset(allow_modules) | _ALWAYS_ALLOWED_MODULES

    # 1. Import regex check
    import_re = _build_import_regex(effective_allowed)
    m = import_re.search(code)
    if m:
        raise SandboxError(m.group(0))

    # 2. Forbidden token check
    forbidden_re = _build_forbidden_regex()
    m = forbidden_re.search(code)
    if m:
        raise SandboxError(m.group(0))

    # 3. Dunder attribute check
    m = _DUNDER_RE.search(code)
    if m:
        raise SandboxError(m.group(0))

    # 4. AST walk
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top not in effective_allowed:
                    raise SandboxError(f"import {alias.name}")

        elif isinstance(node, ast.ImportFrom):
            if not node.module:
                continue
            top = node.module.split(".", 1)[0]
            if top not in effective_allowed:
                raise SandboxError(f"from {node.module} import")

        elif isinstance(node, ast.Attribute):
            if isinstance(node.attr, str) and node.attr.startswith("_"):
                raise SandboxError(f".{node.attr}")

        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "range":
                if (
                    node.args
                    and isinstance(node.args[-1], ast.Constant)
                    and isinstance(node.args[-1].value, int)
                    and node.args[-1].value > _MAX_LOOP_COUNT
                ):
                    raise SandboxError(f"range({node.args[-1].value})")

    return None
