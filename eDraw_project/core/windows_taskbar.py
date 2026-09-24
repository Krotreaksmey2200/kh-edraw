"""Windows taskbar identity helpers.

When eDraw is run from source, the real executable is ``pythonw.exe``.  Windows
can still show the window icon correctly, but the taskbar pin command needs
explicit relaunch metadata or it pins *Python* instead of *eDraw*.
"""

from __future__ import annotations

import ctypes
import sys
import uuid
from ctypes import wintypes
from pathlib import Path

APP_USER_MODEL_ID = "HMaths.eDraw"

# ---------------------------------------------------------------------------
# COM / PropertyStore constants
# ---------------------------------------------------------------------------

_PKEY_APP_USER_MODEL_ID_PID = 5
_PKEY_APP_USER_MODEL_RELAUNCH_COMMAND_PID = 2
_PKEY_APP_USER_MODEL_RELAUNCH_ICON_RESOURCE_PID = 3
_PKEY_APP_USER_MODEL_RELAUNCH_DISPLAY_NAME_RESOURCE_PID = 4

_APP_USER_MODEL_FMTID = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
_IID_IPROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"

_VT_LPWSTR = 31

# Window style / positioning constants
_GWL_STYLE = -16
_WS_MAXIMIZE = 0x01000000
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020


# ---------------------------------------------------------------------------
# ctypes structures
# ---------------------------------------------------------------------------


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [
        ("fmtid", _GUID),
        ("pid", wintypes.DWORD),
    ]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("pwszVal", ctypes.c_void_p),
        ("reserved", ctypes.c_void_p),
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _guid(value: str) -> _GUID:
    """Parse a GUID string into a ``_GUID`` structure."""
    parsed = uuid.UUID(value)
    data4 = (ctypes.c_ubyte * 8).from_buffer_copy(parsed.bytes[8:])
    return _GUID(parsed.time_low, parsed.time_mid, parsed.time_hi_version, data4)


def _pkey(pid: int) -> _PROPERTYKEY:
    return _PROPERTYKEY(_guid(_APP_USER_MODEL_FMTID), pid)


def _relaunch_command() -> str:
    """Build the relaunch command string for the current process."""
    executable = Path(sys.executable).resolve()
    if not getattr(sys, "frozen", False):
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
        script = (
            Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0]
            else Path(__file__).resolve().parent.parent / "main.py"
        )
        return f'"{executable}" "{script}"'
    return f'"{executable}"'


def _icon_resource(icon_path: str | None) -> str:
    """Build the icon resource string for relaunch metadata."""
    if icon_path:
        return f"{Path(icon_path).resolve()},0"
    return f"{Path(sys.executable).resolve()},0"


def _source_main() -> Path:
    return Path(__file__).resolve().parent.parent / "main.py"


def _get_window_property_store(hwnd: int) -> ctypes.c_void_p:
    """Obtain the IPropertyStore for a window handle."""
    shell32 = ctypes.OleDLL("shell32")
    shell32.SHGetPropertyStoreForWindow.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    )
    shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long
    store = ctypes.c_void_p()
    hr = shell32.SHGetPropertyStoreForWindow(
        wintypes.HWND(hwnd),
        ctypes.byref(_guid(_IID_IPROPERTY_STORE)),
        ctypes.byref(store),
    )
    if hr < 0 or not store:
        raise OSError(hr)
    return store


def _method(store: ctypes.c_void_p, index: int, restype: type, *argtypes: type):
    """Look up a COM vtable method by index."""
    vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method_ptr = vtbl[index]
    func_type = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return func_type(ctypes.cast(method_ptr, ctypes.c_void_p))


def _set_property(store: ctypes.c_void_p, key: _PROPERTYKEY, value: str) -> None:
    """Set a string property on the window's PropertyStore."""
    pv = _PROPVARIANT()
    pv.vt = _VT_LPWSTR
    buffer = ctypes.create_unicode_buffer(value)
    pv.pwszVal = ctypes.cast(buffer, ctypes.c_void_p)
    set_value = _method(
        store, 6, ctypes.c_long,
        ctypes.POINTER(_PROPERTYKEY),
        ctypes.POINTER(_PROPVARIANT),
    )
    hr = set_value(store, ctypes.byref(key), ctypes.byref(pv))
    if hr < 0:
        raise OSError(hr)


def _commit(store: ctypes.c_void_p) -> None:
    """Commit pending property changes."""
    commit = _method(store, 7, ctypes.c_long)
    hr = commit(store)
    if hr < 0:
        raise OSError(hr)


def _release(store: ctypes.c_void_p) -> None:
    """Release the PropertyStore COM object."""
    release_fn = _method(store, 2, wintypes.ULONG)
    release_fn(store)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def set_process_app_user_model_id(app_id: str) -> None:
    """Set the AppUserModelID for the current process (Windows only)."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(str(app_id))
    except Exception:
        pass


def ensure_window_maximized_style(hwnd: int) -> None:
    """Ensure *hwnd* has ``WS_MAXIMIZE`` before the first ``ShowWindow``."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            get_window_long = user32.GetWindowLongPtrW
            set_window_long = user32.SetWindowLongPtrW
        else:
            get_window_long = user32.GetWindowLongW
            set_window_long = user32.SetWindowLongW

        get_window_long.argtypes = (wintypes.HWND, ctypes.c_int)
        get_window_long.restype = ctypes.c_ssize_t
        set_window_long.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        set_window_long.restype = ctypes.c_ssize_t

        hwnd_val = wintypes.HWND(hwnd)
        style = int(get_window_long(hwnd_val, _GWL_STYLE))
        if style & _WS_MAXIMIZE:
            return

        set_window_long(hwnd_val, _GWL_STYLE, style | _WS_MAXIMIZE)

        user32.SetWindowPos.argtypes = (
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_uint,
        )
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.SetWindowPos(
            hwnd_val,
            wintypes.HWND(0),
            0, 0, 0, 0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
        )
    except Exception:
        pass


def configure_window_taskbar(
    hwnd: int,
    *,
    display_name: str = 'eDraw',
    icon_path: str | Path | None = None,
) -> None:
    """Configure taskbar properties (AppUserModelID, relaunch command, icon)."""
    if sys.platform != "win32" or not hwnd:
        return
    store = _get_window_property_store(hwnd)
    try:
        _set_property(store, _pkey(_PKEY_APP_USER_MODEL_ID_PID), APP_USER_MODEL_ID)
        _set_property(
            store,
            _pkey(_PKEY_APP_USER_MODEL_RELAUNCH_COMMAND_PID),
            _relaunch_command(),
        )
        _set_property(
            store,
            _pkey(_PKEY_APP_USER_MODEL_RELAUNCH_DISPLAY_NAME_RESOURCE_PID),
            display_name,
        )
        _set_property(
            store,
            _pkey(_PKEY_APP_USER_MODEL_RELAUNCH_ICON_RESOURCE_PID),
            _icon_resource(icon_path),
        )
        _commit(store)
    finally:
        _release(store)
