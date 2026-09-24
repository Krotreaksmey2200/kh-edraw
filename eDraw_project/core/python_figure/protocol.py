"""Backend protocol for Python Figure rendering.

A Backend takes user source code, compiles it into a ``BackendProgram``, and
then turns (program, params, size) tuples into rendered ``RenderResult``\ s.
eDraw ships only the controlled in-house ``edraw`` backend for Python Figure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from PyQt6.QtGui import QImage


@dataclass
class BackendProgram:
    """Compiled representation of user figure code."""
    source: str
    compiled_code: Any = None
    warnings: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RenderResult:
    """Result of rendering a ``BackendProgram``."""
    image: QImage | None = None
    warnings: list[str] = field(default_factory=list)


class Backend(Protocol):
    """Pluggable rendering backend."""

    allow_modules: frozenset[str]

    def compile(self, code: str) -> BackendProgram:
        """Compile user source.  Must validate via ast_guard.

        Raises:
            SandboxError: when the source contains forbidden patterns.
            ValueError:   for any other compile-time problem (syntax, missing
                          ``draw``, malformed PARAMS, ...).
        """
        ...

    def render(
        self,
        program: BackendProgram,
        params: dict[str, float],
        size_px: tuple[int, int],
    ) -> RenderResult:
        """Render program at the given pixel size with the supplied parameters."""
        ...
