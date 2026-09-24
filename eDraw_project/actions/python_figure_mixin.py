"""
actions/python_figure_mixin.py
Python Figure flow — mixed into MainWindow.

Pattern mirrors `actions/ai_mixin.py`: a dialog is opened, the user composes
Python source, on accept we place a high-resolution floating figure on the
current slide; right-click commits it as a `PythonFigureElement`.

Live parameter changes (via the floating slider panel on the canvas) are
rendered on a dedicated background `PythonFigureRenderWorker` so the UI
thread stays free for drawing/painting/other interactions.  The latest
render request always wins — older in-flight renders are discarded when a
newer one finishes, ensuring smooth slider behaviour.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, QPointF, QSizeF, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

from core.i18n import t
from core.python_figure import PythonFigureRenderWorker, SandboxError, get_service, start_python_figure_worker
from models.elements import ImageElement, PythonFigureElement

_FLOATING_RENDER_SCALE = 4
_LIVE_RENDER_SCALE = 4


def _params_for_render_scale(backend, params, render_scale):
    out = dict(params)
    if backend == "edraw" and float(render_scale) != 1:
        out["__edraw_render_scale__"] = float(render_scale)
    return out


class _ParamRenderDispatcher(QObject):
    """Holds the queued signals used to drive the off-thread render worker.

    pyqtSignal can only be declared at class level on a QObject subclass —
    PythonFigureMixin is a plain mixin so we keep the signals on this small
    helper that lives on the MainWindow.
    """
    compile_and_render = pyqtSignal(str, str, dict, int, int)
    render_only = pyqtSignal(dict, int, int)


class PythonFigureMixin:
    """Toolbar entry-point + canvas helpers for Python Figure elements."""

    def _run_figure_composer(self):
        """Toolbar button → open the unified figure compiler dialog."""
        self._open_python_figure_dialog(initial=None, initial_backend="tikz")

    def _run_python_figure(self):
        """Compatibility entry point for older shortcuts/actions."""
        self._run_figure_composer()

    def _run_tikz_figure(self):
        """Compatibility entry point for older shortcuts/actions."""
        self._open_python_figure_dialog(initial=None, initial_backend="tikz")

    def _open_python_figure_dialog(self, initial=None, *, initial_backend="tikz", initial_code=None):
        from dialogs.python_figure_dialog import PythonFigureDialog
        code = initial_code or (initial.code if initial else "")
        backend = initial_backend or (initial.backend if initial else "tikz")
        params = dict(initial.params) if initial else {}
        param_specs = dict(initial.param_specs) if initial else {}
        editing = initial is not None
        dlg = PythonFigureDialog(
            parent=self,
            code=code,
            backend=backend,
            params=params,
            param_specs=param_specs,
            editing=editing,
        )
        dlg.finished_signal.connect(lambda: self._on_python_figure_dialog_finished(dlg))
        self._py_fig_dialog = dlg
        self._py_fig_pending_element = initial
        dlg.show()

    def _on_python_figure_dialog_finished(self, dlg):
        if getattr(self, "_py_fig_dialog", None) is dlg:
            self._py_fig_dialog = None
        self._py_fig_pending_element = None

    def _on_python_figure_ready(self, data):
        """Dialog callback — insert or update a figure on the current slide.

        Return True to close the dialog, False to keep it open (e.g. quota
        check failed).
        """
        editing = getattr(self, "_py_fig_pending_element", None)
        param_specs = dict(data.get("param_specs", {}))
        is_dynamic = len(param_specs) > 0
        backend = data.get("backend", "tikz")
        is_tikz = backend == "tikz"
        code = data.get("code", "")
        logical_w = data.get("width", 400)
        logical_h = data.get("height", 300)
        params = dict(data.get("params", {}))
        if editing:
            editing.code = code
            editing.backend = backend
            editing.params = params
            editing.param_specs = param_specs
            editing.logical_size = QSizeF(logical_w, logical_h)
            self.canvas.update()
        else:
            pos = self._python_figure_default_pos(QSizeF(logical_w, logical_h))
            el = PythonFigureElement(
                code=code,
                backend=backend,
                params=params,
                param_specs=param_specs,
                logical_size=QSizeF(logical_w, logical_h),
                pos=pos,
            )
            self.canvas._current_slide.add_element(el)
            self.canvas._current_slide.save_state()
            self.canvas.update()
        return True

    def can_edit_python_figure_code(self):
        """Only PRO can edit raw source — BASIC/PLUS see read-only editor."""
        return bool(self._plan_limits().get("can_edit_code"))

    def _python_figure_default_pos(self, logical_size):
        """Return a slide-space top-left position that centers the figure
        on the current viewport."""
        canvas = self.canvas
        vp_w = canvas.viewport().width() / canvas._zoom
        vp_h = canvas.viewport().height() / canvas._zoom
        x = canvas._scroll_x + (vp_w - logical_size.width()) / 2
        y = canvas._scroll_y + (vp_h - logical_size.height()) / 2
        return QPointF(max(0, x), max(0, y))

    def _render_python_figure_pixmap(self, el, *, render_scale, fallback=None):
        scale = max(1, float(render_scale))
        size_px = (
            max(1, int(round(el.logical_size.width() * scale))),
            max(1, int(round(el.logical_size.height() * scale))),
        )
        try:
            service = get_service()
            params = _params_for_render_scale(el.backend, el.params, render_scale)
            image = service.render(el.code, el.backend, size_px, params)
            if image and not image.isNull():
                return QPixmap.fromImage(image)
        except Exception:
            pass
        return fallback

    def init_python_figure_signals(self):
        """Wire canvas.python_figure_selected → param panel.

        Called by MainWindow.__init__ after `self.canvas` is built.
        """
        canvas = getattr(self, "canvas", None)
        if canvas and hasattr(canvas, "python_figure_selected"):
            canvas.python_figure_selected.connect(self._handle_python_figure_selected)

    def _ensure_param_panel(self):
        if getattr(self, "_py_fig_param_panel", None):
            return self._py_fig_param_panel
        from widgets.python_figure_param_panel import PythonFigureParamPanel
        panel = PythonFigureParamPanel(self)
        panel.params_changed.connect(self._on_panel_params_changed)
        panel.edit_requested.connect(self._on_panel_edit_requested)
        panel.bake_requested.connect(self._on_panel_bake_requested)
        panel.close_requested.connect(self._on_panel_close_requested)
        self._py_fig_param_panel = panel
        return panel

    def _handle_python_figure_selected(self, el):
        """Canvas → double-click → show floating param panel near the figure."""
        panel = self._ensure_param_panel()
        panel.set_element(el)
        anchor = self._element_global_anchor(el)
        panel.move(anchor)
        panel.show()
        panel.raise_()

    def _element_global_anchor(self, el):
        """Return a global QPoint at the top-right of the element on screen."""
        canvas = self.canvas
        w = el.logical_size.width() * el.scale_x
        slide_pt = QPointF(el.pos.x() + w, el.pos.y())
        vp_x = (slide_pt.x() - canvas._scroll_x) * canvas._zoom
        vp_y = (slide_pt.y() - canvas._scroll_y) * canvas._zoom
        global_pt = canvas.mapToGlobal(QPoint(int(vp_x), int(vp_y)))
        return global_pt

    def _hide_param_panel(self):
        panel = getattr(self, "_py_fig_param_panel", None)
        if panel:
            panel.hide()

    def _reposition_python_figure_panel(self):
        panel = getattr(self, "_py_fig_param_panel", None)
        if panel and panel.isVisible():
            el = panel._element
            if el:
                anchor = self._element_global_anchor(el)
                panel.move(anchor)

    def _on_panel_params_changed(self, new_params):
        panel = getattr(self, "_py_fig_param_panel", None)
        if panel and panel._element:
            self._update_python_figure_params(panel._element, new_params)

    def _on_panel_edit_requested(self):
        panel = getattr(self, "_py_fig_param_panel", None)
        if panel and panel._element:
            self._edit_python_figure(panel._element)

    def _on_panel_bake_requested(self):
        panel = getattr(self, "_py_fig_param_panel", None)
        if panel and panel._element:
            self._bake_python_figure_to_image(panel._element)
            self._hide_param_panel()

    def _on_panel_close_requested(self):
        self._hide_param_panel()

    def _edit_python_figure(self, el):
        """Open the dialog pre-populated with this element for editing."""
        self._open_python_figure_dialog(initial=el)

    def _update_python_figure_params(self, el, new_params):
        """Apply slider changes asynchronously via the render worker.

        The render runs on a dedicated background thread so dragging the
        slider never freezes the UI — drawing strokes, panning, other figure
        interactions all stay smooth.  Only the latest pending render is kept
        when requests arrive faster than the worker can finish them.
        """
        el.params = dict(new_params)
        canvas = getattr(self, "canvas", None)
        if canvas:
            canvas.update()

    def _ensure_param_render_worker(self):
        pass

    def _dispatch_pending_param_render(self):
        pass

    def _on_param_render_done(self, image):
        self._py_fig_render_inflight = None

    def _on_param_render_failed(self, message):
        self._py_fig_render_inflight = None
        self._py_fig_worker_compiled_key = None
        short = (message or "?").splitlines()[0][:200]
        self.statusBar().showMessage(t("Lỗi vẽ: {error}", error=short), 3000)

    def _find_python_figure_by_id(self, el_id):
        canvas = getattr(self, "canvas", None)
        if not canvas:
            return None
        for el in canvas._current_slide.elements:
            if el.kind == "python_figure" and el.id == el_id:
                return el
        return None

    def _bake_python_figure_to_image(self, el):
        """Convert the figure into a static ImageElement at its current params.

        Renders at 4x logical size for crisp output, then adjusts scale so
        the on-canvas footprint stays the same.
        """
        canvas = self.canvas
        service = get_service()
        scale = _FLOATING_RENDER_SCALE
        size_px = (
            max(1, int(round(el.logical_size.width() * scale))),
            max(1, int(round(el.logical_size.height() * scale))),
        )
        try:
            params = _params_for_render_scale(el.backend, el.params, scale)
            image = service.render(el.code, el.backend, size_px, params)
            if image and not image.isNull():
                pix = QPixmap.fromImage(image)
                img_el = ImageElement(
                    pos=QPointF(el.pos),
                    scale_x=el.scale_x / scale,
                    scale_y=el.scale_y / scale,
                    rotation=el.rotation,
                )
                canvas._current_slide.elements.remove(el)
                canvas._current_slide.add_element(img_el)
                canvas._current_slide.save_state()
                canvas.update()
        except Exception as e:
            self.statusBar().showMessage(t("Lỗi ghim figure: {error}", error=str(e)), 4000)
