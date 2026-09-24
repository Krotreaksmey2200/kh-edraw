'''Shared application icon helpers.'''
from __future__ import annotations
from pathlib import Path
import sys
from PyQt6.QtGui import QIcon


def _resource_root():
    '''Trả về thư mục gốc chứa tài nguyên ứng dụng.'''
    if getattr(sys, 'frozen', False):
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def app_icon_path():
    '''Tìm file icon phù hợp với nền tảng hiện tại.'''
    root = _resource_root()
    if sys.platform == 'win32':
        candidates = (
            root / 'assets' / 'khedraw.ico',
            root / 'assets' / 'khedraw_logo.png',
            root / 'assets' / 'iconEDraw.ico',
            root / 'assets' / 'iconEDraw.png',
        )
    elif sys.platform == 'darwin':
        candidates = (
            root / 'assets' / 'khedraw.icns',
            root / 'assets' / 'khedraw_logo.png',
            root / 'assets' / 'iconEDraw.icns',
            root / 'assets' / 'iconEDraw.png',
        )
    else:
        candidates = (
            root / 'assets' / 'khedraw_logo.png',
            root / 'assets' / 'iconEDraw.png',
            root / 'assets' / 'khedraw.ico',
        )
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_app_icon():
    '''Tải QIcon từ file icon ứng dụng.'''
    path = app_icon_path()
    if path and path.is_file():
        return QIcon(str(path))
    return QIcon()
