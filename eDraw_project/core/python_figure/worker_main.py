"""QThread worker for compiling and rendering Python figures off the UI thread.

Pattern mirrors ``core.custom_curve_tool.CurveToolWorker``::

    worker = PythonFigureRenderWorker()
    worker.compiled.connect(on_compiled)
    worker.rendered.connect(on_rendered)
    worker.failed.connect(on_failed)
    thread = start_python_figure_worker(parent, worker)
    # then trigger work via queued slots
    QMetaObject.invokeMethod(worker, "run_compile_and_render",
                             Q_ARG(str, code), Q_ARG(str, backend),
                             Q_ARG('QVariant', params), Q_ARG(int, w), Q_ARG(int, h))

A simpler pattern is used in this code base: the caller assigns work to the
worker BEFORE moving to thread (or via a direct queued slot call).  For the
Python Figure UI we drive the worker via dedicated methods that the dialog
invokes through signals.
"""
from __future__ import annotations

import traceback

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage

from core.i18n import t
from core.python_figure.ast_guard import SandboxError
from core.python_figure.service import get_service


class PythonFigureRenderWorker(QObject):
    """QObject worker that compiles + renders Python figure code.

    Signals:
        log       — progress messages for the status bar.
        compiled  — emitted after a successful compile.  Payload is a dict:
                    {"meta", "param_specs", "warnings"}.
        rendered  — emitted after each successful render.  Payload: QImage.
        failed    — emitted on any compile/render error.  Payload: error str.
    """

    log = pyqtSignal(str)
    compiled = pyqtSignal(dict)
    rendered = pyqtSignal(QImage)
    failed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._last_code = None
        self._last_backend = None

    @pyqtSlot(str, str, dict, int, int)
    def run_compile_and_render(self, code: str, backend: str, params: dict, width: int, height: int) -> None:
        service = get_service()
        try:
            self.log.emit(t("Đang biên dịch..."))
            program = service.compile(code, backend)
            self._last_code = code
            self._last_backend = backend
            self.compiled.emit(
                {
                    "meta": dict(program.meta),
                    "param_specs": dict(program.param_specs),
                    "warnings": list(program.warnings),
                }
            )
            self.log.emit(t("Đang vẽ..."))
            merged = {
                name: spec.get("value", 0.0)
                for name, spec in program.param_specs.items()
            }
            merged.update({str(k): float(v) for k, v in (params or {}).items()})
            result = service.render(program, backend, merged, (int(width), int(height)))
            self.rendered.emit(result.image)
            self.log.emit(t("Biên dịch & vẽ thành công"))
        except SandboxError as exc:
            self.failed.emit(t("Mã chứa lệnh bị cấm: {name}", name=str(exc)))
        except Exception as exc:
            tb = traceback.format_exc(limit=3)
            self.failed.emit(f"{exc}\n\n{tb}")

    @pyqtSlot(dict, int, int)
    def run_render(self, params: dict, width: int, height: int) -> None:
        service = get_service()
        if not (self._last_code and self._last_backend):
            self.failed.emit(t("Lỗi vẽ: {error}", error="chưa biên dịch"))
            return
        try:
            program = service.compile(self._last_code, self._last_backend)
            merged = {
                name: spec.get("value", 0.0)
                for name, spec in program.param_specs.items()
            }
            merged.update({str(k): float(v) for k, v in (params or {}).items()})
            result = service.render(program, self._last_backend, merged, (int(width), int(height)))
            self.rendered.emit(result.image)
        except SandboxError as exc:
            self.failed.emit(t("Mã chứa lệnh bị cấm: {name}", name=str(exc)))
        except Exception as exc:
            tb = traceback.format_exc(limit=3)
            self.failed.emit(f"{exc}\n\n{tb}")


def start_python_figure_worker(parent: QObject, worker: PythonFigureRenderWorker) -> QThread:
    """Move *worker* to a fresh QThread parented to *parent* and start it.

    The thread quits/cleans up automatically when the worker emits ``rendered``
    or ``failed``.  Callers retain ownership of the worker reference.
    """
    thread = QThread(parent)
    worker.moveToThread(thread)
    parent.destroyed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
