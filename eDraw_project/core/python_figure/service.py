"""PythonFigureRenderService -- compile + render entry point used by UI/worker.

The service caches:
  * compiled programs by (hash(code), backend_name) -- survives across renders
  * rendered images by (compile_key, params_tuple, size) -- size-limited LRU
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Any

from PyQt6.QtGui import QImage

from core.python_figure.protocol import BackendProgram, RenderResult

_RENDER_CACHE_MAX = 32


def _code_hash(code: str) -> str:
    return hashlib.md5(code.encode("utf-8", errors="replace")).hexdigest()


def _params_key(params: dict[str, float]) -> list:
    return sorted(params.items())


class PythonFigureRenderService:
    """Lazy backend registry + LRU caches for compile/render."""

    def __init__(self):
        self._compile_cache: dict[tuple[str, str], BackendProgram] = {}
        self._render_cache: OrderedDict[tuple, QImage] = OrderedDict()

    def _get_backend(self, backend_name: str):
        import core.python_figure.backends
        BACKENDS = core.python_figure.backends.BACKENDS
        try:
            return BACKENDS[backend_name]
        except KeyError:
            raise ValueError(f"Backend '{backend_name}' không tồn tại.")

    def compile(self, code: str, backend_name: str) -> BackendProgram:
        key = (_code_hash(code), backend_name)
        cached = self._compile_cache.get(key)
        if cached is not None:
            return cached
        backend = self._get_backend(backend_name)
        program = backend.compile(code)
        self._compile_cache[key] = program
        return program

    def render(
        self,
        program: BackendProgram,
        backend_name: str,
        params: dict[str, float],
        size_px: tuple[int, int],
    ) -> RenderResult:
        backend = self._get_backend(backend_name)
        w = max(1, int(size_px[0]))
        h = max(1, int(size_px[1]))
        return backend.render(program, params, (w, h))

    def render_cached(
        self,
        code: str,
        backend_name: str,
        params: dict[str, float],
        size_px: tuple[int, int],
    ) -> RenderResult:
        """Convenience: compile (cached) + render with an LRU image cache."""
        program = self.compile(code, backend_name)
        w = max(1, int(size_px[0]))
        h = max(1, int(size_px[1]))
        key = (_code_hash(code), backend_name, _params_key(params), w, h)
        cached_img = self._render_cache.get(key)
        if cached_img is not None:
            return RenderResult(image=cached_img, warnings=list(program.warnings))
        result = self.render(program, backend_name, params, (w, h))
        if result.image is not None:
            self._render_cache[key] = result.image
            if len(self._render_cache) > _RENDER_CACHE_MAX:
                self._render_cache.popitem(last=False)
        return result

    def clear_caches(self):
        self._compile_cache.clear()
        self._render_cache.clear()


_service: PythonFigureRenderService | None = None


def get_service() -> PythonFigureRenderService:
    global _service
    if _service is None:
        _service = PythonFigureRenderService()
    return _service
