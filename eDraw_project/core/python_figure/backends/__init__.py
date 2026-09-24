"""Backend registry for Python Figure.

The in-house `edraw` backend covers safe Python drawing primitives.  The `tikz`
backend is not a Python execution backend; it compiles user-authored standalone
TikZ documents through the configured local pdflatex.
"""

from __future__ import annotations

from core.python_figure.backends.edraw_backend import EDrawBackend
from core.python_figure.backends.tikz_backend import TikzBackend
from core.python_figure.protocol import Backend

BACKENDS: dict[str, Backend] = {
    "tikz": TikzBackend(),
    "edraw": EDrawBackend(),
}


def available_backends() -> list[str]:
    return ["tikz", "edraw"]


__all__ = ["BACKENDS", "Backend", "available_backends"]
