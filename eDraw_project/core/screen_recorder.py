"""Lightweight threaded app-window screen recorder for eDraw."""
from __future__ import annotations

import queue
import struct
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from PyQt6.QtCore import QObject, QRect, QStandardPaths, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QGuiApplication, QImage
from PyQt6.QtWidgets import QWidget


# ---------------------------------------------------------------------------
# Low-level packing helpers
# ---------------------------------------------------------------------------

def _u16(value: int) -> bytes:
    return struct.pack("<H", value & 0xFFFF)


def _i16(value: int) -> bytes:
    return struct.pack("<h", value)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value & 0xFFFFFFFF)


def _i32(value: int) -> bytes:
    return struct.pack("<i", value)


def _fourcc_int(code: bytes) -> int:
    return struct.unpack("<I", code)[0]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RecordingResult:
    """Outcome of a recording session."""

    path: Path
    frame_count: int
    duration_seconds: float
    error: str | None = None


@dataclass(slots=True)
class _FramePacket:
    """A single captured frame ready for encoding."""

    image: QImage
    rect: QRect
    cursor_x: int = 0
    cursor_y: int = 0
    excluded_rects: tuple = ()
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# AVI / MJPEG writer
# ---------------------------------------------------------------------------

class MjpegAviWriter:
    """Minimal AVI/MJPEG writer with a classic idx1 index."""

    def __init__(
        self,
        path: Path,
        width: int,
        height: int,
        fps: float = 30.0,
        quality: int = 82,
    ):
        if width <= 0 or height <= 0:
            raise ValueError("Invalid frame size")
        if fps <= 0:
            raise ValueError("Invalid FPS")
        self.path = path
        self.width = width + width % 2
        self.height = height + height % 2
        self.fps = float(fps)
        self.quality = max(1, min(95, quality))
        self.frame_count = 0
        self._index: list[tuple[int, int]] = []
        self._file = path.open("wb")
        self._riff_size_pos = 0
        self._movi_size_pos = 0
        self._movi_list_data_start = 0
        self._avih_total_frames_pos = 0
        self._avih_micro_per_frame_pos = 0
        self._strh_length_pos = 0
        self._strh_scale_pos = 0
        self._pending_fps: float | None = None
        self._closed = False
        self._write_header()

    def set_actual_fps(self, fps: float) -> None:
        """Override the playback fps when closing (used after the real rate is measured)."""
        if fps > 0:
            self._pending_fps = float(fps)

    def _write_u32(self, value: int) -> None:
        self._file.write(_u32(value))

    def _start_list(self, list_type: bytes) -> int:
        self._file.write(b"LIST")
        size_pos = self._file.tell()
        self._write_u32(0)
        self._file.write(list_type)
        return size_pos

    def _end_list(self, size_pos: int) -> None:
        end = self._file.tell()
        self._file.seek(size_pos)
        self._write_u32(end - (size_pos + 4))
        self._file.seek(end)

    def _write_header(self) -> None:
        suggested_size = self.width * self.height * 3
        # RIFF header
        self._file.write(b"RIFF")
        self._riff_size_pos = self._file.tell()
        self._write_u32(0)
        self._file.write(b"AVI ")
        # hdrl LIST
        hdrl_pos = self._start_list(b"hdrl")
        # avih
        self._file.write(b"avih")
        self._write_u32(56)
        self._avih_micro_per_frame_pos = self._file.tell()
        self._write_u32(int(round(1_000_000 / self.fps)))
        self._write_u32(int(suggested_size * self.fps))
        self._write_u32(0)
        self._write_u32(16)
        self._avih_total_frames_pos = self._file.tell()
        self._write_u32(0)
        self._write_u32(0)
        self._write_u32(1)
        self._write_u32(suggested_size)
        self._write_u32(self.width)
        self._write_u32(self.height)
        self._file.write(_u32(0) * 4)
        # strl LIST
        strl_pos = self._start_list(b"strl")
        # strh
        self._file.write(b"strh")
        self._write_u32(56)
        self._file.write(b"vids")
        self._file.write(b"MJPG")
        self._write_u32(0)
        self._file.write(_u16(0))
        self._file.write(_u16(0))
        self._write_u32(0)
        self._strh_scale_pos = self._file.tell()
        self._write_u32(1000)
        self._write_u32(int(round(self.fps * 1000)))
        self._write_u32(0)
        self._strh_length_pos = self._file.tell()
        self._write_u32(0)
        self._write_u32(suggested_size)
        self._write_u32(0xFFFFFFFF)
        self._write_u32(0)
        self._file.write(_i16(0))
        self._file.write(_i16(0))
        self._file.write(_i16(self.width))
        self._file.write(_i16(self.height))
        # strf
        self._file.write(b"strf")
        self._write_u32(40)
        self._file.write(_u32(40))
        self._file.write(_i32(self.width))
        self._file.write(_i32(self.height))
        self._file.write(_u16(1))
        self._file.write(_u16(24))
        self._file.write(_u32(_fourcc_int(b"MJPG")))
        self._file.write(_u32(suggested_size))
        self._file.write(_i32(0))
        self._file.write(_i32(0))
        self._file.write(_u32(0))
        self._file.write(_u32(0))
        self._end_list(strl_pos)
        self._end_list(hdrl_pos)
        # movi LIST (content written hereafter)
        self._file.write(b"LIST")
        self._movi_size_pos = self._file.tell()
        self._write_u32(0)
        self._movi_list_data_start = self._file.tell()
        self._file.write(b"movi")

    def add_frame(self, image: Image.Image) -> None:
        if self._closed:
            raise RuntimeError("AVI writer is closed")
        if image.mode != "RGB":
            image = image.convert("RGB")
        if image.size != (self.width, self.height):
            canvas = Image.new("RGB", (self.width, self.height), (0, 0, 0))
            if image.width <= self.width and image.height <= self.height:
                canvas.paste(image, (0, 0))
                image = canvas
            else:
                image = image.resize((self.width, self.height), Image.Resampling.BICUBIC)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=self.quality, subsampling=0)
        data = buffer.getvalue()
        chunk_start = self._file.tell()
        self._file.write(b"00dc")
        self._write_u32(len(data))
        self._file.write(data)
        if len(data) % 2:
            self._file.write(b"\x00")
        self._index.append((chunk_start - self._movi_list_data_start, len(data)))
        self.frame_count += 1

    def close(self) -> None:
        if self._closed:
            return
        # idx1
        idx_start = self._file.tell()
        self._file.write(b"idx1")
        self._write_u32(len(self._index) * 16)
        for offset, size in self._index:
            self._file.write(b"00dc")
            self._write_u32(16)
            self._write_u32(offset)
            self._write_u32(size)
        file_end = self._file.tell()
        # Patch RIFF size
        self._file.seek(self._riff_size_pos)
        self._write_u32(file_end - 8)
        # Patch movi LIST size
        self._file.seek(self._movi_size_pos)
        self._write_u32(idx_start - (self._movi_size_pos + 4))
        # Patch total frames
        self._file.seek(self._avih_total_frames_pos)
        self._write_u32(self.frame_count)
        self._file.seek(self._strh_length_pos)
        self._write_u32(self.frame_count)
        # Patch fps if overridden
        if self._pending_fps is not None and self._pending_fps > 0:
            actual_fps = self._pending_fps
            if self.frame_count > 1:
                micro_per_frame = int(round(1_000_000 / actual_fps))
            else:
                micro_per_frame = int(round(1_000_000 / self.fps))
            self._file.seek(self._avih_micro_per_frame_pos)
            self._write_u32(micro_per_frame)
            self._file.seek(self._strh_scale_pos)
            self._write_u32(1000)
            self._write_u32(int(round(actual_fps * 1000)))
        self._file.close()
        self._closed = True


# ---------------------------------------------------------------------------
# Frame rendering (PIL conversion + overlays)
# ---------------------------------------------------------------------------

class _FrameRenderer:
    """Converts QImage packets to PIL Images with cursor / exclusion overlays."""

    def render(self, packet: _FramePacket) -> Image.Image:
        image = self._qimage_to_pil(packet.image)
        draw = ImageDraw.Draw(image)
        self._draw_excluded_rects(draw, image.size, packet)
        self._draw_mouse_cursor(draw, image.size, packet)
        return image

    @staticmethod
    def _qimage_to_pil(image: QImage) -> Image.Image:
        rgb = image.convertToFormat(QImage.Format.Format_RGB888)
        ptr = rgb.bits()
        ptr.setsize(rgb.sizeInBytes())
        return Image.frombytes(
            "RGB",
            (rgb.width(), rgb.height()),
            bytes(ptr),
            "raw",
            "RGB",
            rgb.bytesPerLine(),
            1,
        )

    def _draw_mouse_cursor(
        self, draw: ImageDraw.ImageDraw, size: tuple[int, int], packet: _FramePacket
    ) -> None:
        if not packet.rect.contains(packet.cursor_x, packet.cursor_y):
            return
        width, height = size
        scale_x = width / max(1, packet.rect.width())
        scale_y = height / max(1, packet.rect.height())
        x = int((packet.cursor_x - packet.rect.x()) * scale_x)
        y = int((packet.cursor_y - packet.rect.y()) * scale_y)
        if x < 0 or y < 0 or x >= width or y >= height:
            return
        scale = max(0.75, min(1.5, max(scale_x, scale_y)))
        points = [
            (0, 0), (0, 24), (6, 18), (11, 29),
            (16, 27), (12, 17), (21, 17),
        ]
        scaled = [(int(px * scale) + x, int(py * scale) + y) for px, py in points]
        draw.polygon(scaled, fill=(0, 0, 0))

    def _draw_excluded_rects(
        self, draw: ImageDraw.ImageDraw, size: tuple[int, int], packet: _FramePacket
    ) -> None:
        if not packet.excluded_rects:
            return
        width, height = size
        scale_x = width / max(1, packet.rect.width())
        scale_y = height / max(1, packet.rect.height())
        for excluded in packet.excluded_rects:
            clipped = excluded.intersected(packet.rect)
            if clipped.isNull() or clipped.width() <= 0 or clipped.height() <= 0:
                continue
            x1 = int((clipped.left() - packet.rect.left()) * scale_x)
            y1 = int((clipped.top() - packet.rect.top()) * scale_y)
            x2 = int((clipped.right() - packet.rect.left()) * scale_x)
            y2 = int((clipped.bottom() - packet.rect.top()) * scale_y)
            draw.rectangle(
                [max(0, x1), max(0, y1), min(width - 1, x2), min(height - 1, y2)],
                fill=(255, 255, 255),
            )


# ---------------------------------------------------------------------------
# Async AVI encoder (generic — used by Qt screenshot path)
# ---------------------------------------------------------------------------

class _AsyncAviEncoder:
    """Background encoder that receives frames via a queue and writes AVI."""

    def __init__(
        self,
        path: Path,
        width: int,
        height: int,
        fps: int,
        quality: int,
        *,
        queue_size: int = 6,
    ):
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.quality = quality
        self.frame_count = 0
        self.error: str | None = None
        self._queue: queue.Queue = queue.Queue(maxsize=max(2, queue_size))
        self._stop = object()
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run, name="eDrawVideoEncoder", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def submit(self, packet: _FramePacket) -> None:
        try:
            self._queue.put_nowait(packet)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(packet)

    def is_backlogged(self) -> bool:
        return self._queue.qsize() >= max(1, self._queue.maxsize - 1)

    def stop(self, timeout: float = 10.0) -> tuple[int, str | None]:
        try:
            self._queue.put_nowait(self._stop)
        except queue.Full:
            pass
        self._thread.join(timeout)
        if self._thread.is_alive():
            self._set_error("Video encoder did not stop in time")
        return self.frame_count, self.error

    def _set_error(self, error: str) -> None:
        with self._lock:
            if not self.error:
                self.error = error

    def _run(self) -> None:
        writer: MjpegAviWriter | None = None
        renderer = _FrameRenderer()
        last_elapsed = 0.0
        try:
            while True:
                item = self._queue.get()
                if item is self._stop:
                    break
                packet: _FramePacket = item
                elapsed = packet.timestamp
                if writer is None:
                    writer = MjpegAviWriter(
                        self.path, self.width, self.height,
                        fps=self.fps, quality=self.quality,
                    )
                pil_img = renderer.render(packet)
                writer.add_frame(pil_img)
                self.frame_count += 1
                last_elapsed = elapsed
        except Exception as exc:
            self._set_error(str(exc))
        finally:
            if writer is not None:
                if self.frame_count > 1 and last_elapsed > 0:
                    writer.set_actual_fps(self.frame_count / last_elapsed)
                writer.close()


# ---------------------------------------------------------------------------
# Win32 capture (conditionally imported)
# ---------------------------------------------------------------------------

_WIN32_ENABLED = sys.platform == "win32"
if _WIN32_ENABLED:
    import ctypes
    from ctypes import wintypes

    _SRCCOPY = 13369376
    _DIB_RGB_COLORS = 0
    _BI_RGB = 0
    _CURSOR_SHOWING = 1
    _DI_NORMAL = 3

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class _BITMAPINFO(ctypes.Structure):
        _fields_ = [
            ("bmiHeader", _BITMAPINFOHEADER),
            ("bmiColors", wintypes.DWORD * 3),
        ]

    class _CURSORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hCursor", wintypes.HANDLE),
            ("ptScreenPos", wintypes.POINT),
        ]

    class _ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL),
            ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HANDLE),
            ("hbmColor", wintypes.HANDLE),
        ]

    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32

    _user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetClientRect.restype = wintypes.BOOL
    _user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    _user32.ClientToScreen.restype = wintypes.BOOL
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.GetCursorInfo.argtypes = [ctypes.POINTER(_CURSORINFO)]
    _user32.GetCursorInfo.restype = wintypes.BOOL
    _user32.GetIconInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ICONINFO)]
    _user32.GetIconInfo.restype = wintypes.BOOL
    _user32.DrawIconEx.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HANDLE,
        ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT,
    ]
    _user32.DrawIconEx.restype = wintypes.BOOL
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.ReleaseDC.restype = ctypes.c_int
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.BitBlt.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
    ]
    _gdi32.BitBlt.restype = wintypes.BOOL
    _gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.POINTER(_BITMAPINFO), wintypes.UINT,
    ]
    _gdi32.GetDIBits.restype = ctypes.c_int
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteObject.restype = wintypes.BOOL
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.DeleteDC.restype = wintypes.BOOL


# ---------------------------------------------------------------------------
# Shared frame utilities
# ---------------------------------------------------------------------------

def _fit_frame_size(width: int, height: int, max_dimension: int = 2560) -> tuple[int, int]:
    width = max(1, int(width))
    height = max(1, int(height))
    limit = max(480, int(max_dimension))
    largest = max(width, height)
    if largest <= limit:
        return width, height
    scale = limit / largest
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _resize_frame_if_needed(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    if image.size == size:
        return image
    return image.resize(size, Image.Resampling.LANCZOS)


_CAPTURE_TOP_INSET = 3
_TOOLBAR_FALLBACK_COLOR = (255, 255, 255)


def _mask_rect_with_neighbor(
    image: Image.Image, rect: tuple[int, int, int, int]
) -> None:
    """Fill *rect* on *image* by stretching a neighbouring strip (toolbar colour patch)."""
    x1, y1, x2, y2 = rect
    w = x2 - x1
    h = y2 - y1
    if w <= 0 or h <= 0:
        return
    img_w, img_h = image.size
    half_h = h // 2
    margin = max(2, min(8, half_h))
    sample = None
    if y1 - margin >= 0:
        sample = image.crop((x1, y1 - margin, x2, y1))
    elif y2 + margin <= img_h:
        sample = image.crop((x1, y2, x2, y2 + margin))
    elif x1 - margin >= 0:
        sample = image.crop((x1 - margin, y1, x1, y2))
    elif x2 + margin <= img_w:
        sample = image.crop((x2, y1, x2 + margin, y2))
    if sample is None or sample.width == 0 or sample.height == 0:
        ImageDraw.Draw(image).rectangle(
            [x1, y1, x2 - 1, y2 - 1], fill=_TOOLBAR_FALLBACK_COLOR
        )
        return
    stretched = sample.resize((w, h), Image.Resampling.NEAREST)
    image.paste(stretched, (x1, y1))


def _draw_excluded_rects_on_pil(
    image: Image.Image,
    capture_rect: tuple[int, int, int, int],
    excluded_rects: Iterable[tuple[int, int, int, int]],
) -> None:
    if not excluded_rects:
        return
    left, top, right, bottom = capture_rect
    width, height = image.size
    capture_w = max(1, right - left)
    capture_h = max(1, bottom - top)
    scale_x = width / capture_w
    scale_y = height / capture_h
    for ex_left, ex_top, ex_right, ex_bottom in excluded_rects:
        clipped_left = max(left, ex_left)
        clipped_top = max(top, ex_top)
        clipped_right = min(right, ex_right)
        clipped_bottom = min(bottom, ex_bottom)
        if clipped_right <= clipped_left or clipped_bottom <= clipped_top:
            continue
        x1 = max(0, int((clipped_left - left) * scale_x))
        y1 = max(0, int((clipped_top - top) * scale_y))
        x2 = min(width, int((clipped_right - left) * scale_x) + 1)
        y2 = min(height, int((clipped_bottom - top) * scale_y) + 1)
        if x2 <= x1 or y2 <= y1:
            continue
        _mask_rect_with_neighbor(image, (x1, y1, x2, y2))


# ---------------------------------------------------------------------------
# Win32 capture context
# ---------------------------------------------------------------------------

def _win32_client_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Return the client area rect in screen coords — excludes the OS title bar/borders."""
    if not _WIN32_ENABLED:
        return None
    if not hwnd or _user32.IsIconic(hwnd) or not _user32.IsWindowVisible(hwnd):
        return None
    crect = wintypes.RECT()
    if not _user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(crect)):
        return None
    pt = wintypes.POINT(0, 0)
    if not _user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(pt)):
        return None
    width = int(crect.right) - int(crect.left)
    height = int(crect.bottom) - int(crect.top) - _CAPTURE_TOP_INSET
    if width <= 0 or height <= 0:
        return None
    left = int(pt.x)
    top = int(pt.y) + _CAPTURE_TOP_INSET
    return left, top, left + width, top + height


def _win32_draw_cursor(hdc, capture_rect: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = capture_rect
    info = _CURSORINFO()
    info.cbSize = ctypes.sizeof(_CURSORINFO)
    if not _user32.GetCursorInfo(ctypes.byref(info)):
        return
    if not (info.flags & _CURSOR_SHOWING) or not info.hCursor:
        return
    cursor_x = int(info.ptScreenPos.x)
    cursor_y = int(info.ptScreenPos.y)
    if (cursor_x < left - 128 or cursor_x > right + 128
            or cursor_y < top - 128 or cursor_y > bottom + 128):
        return
    hot_x = 0
    hot_y = 0
    icon = _ICONINFO()
    if _user32.GetIconInfo(info.hCursor, ctypes.byref(icon)):
        hot_x = int(icon.xHotspot)
        hot_y = int(icon.yHotspot)
        if icon.hbmMask:
            _gdi32.DeleteObject(icon.hbmMask)
        if icon.hbmColor:
            _gdi32.DeleteObject(icon.hbmColor)
    _user32.DrawIconEx(
        hdc, cursor_x - left - hot_x, cursor_y - top - hot_y,
        info.hCursor, 0, 0, 0, None, _DI_NORMAL,
    )


class _Win32CaptureContext:
    """Cached GDI capture context — reuses the screen DC, memory DC and bitmap between frames."""

    def __init__(self) -> None:
        self._hdc_screen = _user32.GetDC(None) if _WIN32_ENABLED else 0
        self._hdc_mem = _gdi32.CreateCompatibleDC(self._hdc_screen) if self._hdc_screen else 0
        self._bitmap = 0
        self._old_obj = 0
        self._buffer = None
        self._size = (0, 0)
        if _WIN32_ENABLED:
            self._info = _BITMAPINFO()
        else:
            self._info = None

    def _ensure_size(self, width: int, height: int) -> bool:
        if not self._hdc_screen or not self._hdc_mem:
            return False
        if (width, height) == self._size and self._bitmap:
            return True
        if self._old_obj:
            _gdi32.SelectObject(self._hdc_mem, self._old_obj)
            self._old_obj = 0
        if self._bitmap:
            _gdi32.DeleteObject(self._bitmap)
            self._bitmap = 0
        bitmap = _gdi32.CreateCompatibleBitmap(self._hdc_screen, width, height)
        if not bitmap:
            self._size = (0, 0)
            return False
        self._bitmap = bitmap
        self._old_obj = _gdi32.SelectObject(self._hdc_mem, bitmap)
        self._buffer = ctypes.create_string_buffer(width * height * 4)
        self._size = (width, height)
        return True

    def capture(self, rect: tuple[int, int, int, int]) -> Image.Image | None:
        if not _WIN32_ENABLED:
            return None
        left, top, right, bottom = rect
        width = max(1, right - left)
        height = max(1, bottom - top)
        if not self._ensure_size(width, height):
            return None
        if not _gdi32.BitBlt(
            self._hdc_mem, 0, 0, width, height, self._hdc_screen, left, top, _SRCCOPY
        ):
            return None
        _win32_draw_cursor(self._hdc_mem, rect)
        info = self._info
        info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = _BI_RGB
        info.bmiHeader.biSizeImage = 0
        rows = _gdi32.GetDIBits(
            self._hdc_mem, self._bitmap, 0, height,
            self._buffer, ctypes.byref(info), _DIB_RGB_COLORS,
        )
        if rows != height:
            return None
        return Image.frombuffer(
            "RGB", (width, height), self._buffer, "raw", "BGRX", 0, 1,
        ).copy()

    def close(self) -> None:
        if self._old_obj and self._hdc_mem:
            _gdi32.SelectObject(self._hdc_mem, self._old_obj)
            self._old_obj = 0
        if self._bitmap:
            _gdi32.DeleteObject(self._bitmap)
            self._bitmap = 0
        if self._hdc_mem:
            _gdi32.DeleteDC(self._hdc_mem)
            self._hdc_mem = 0
        if self._hdc_screen:
            _user32.ReleaseDC(None, self._hdc_screen)
            self._hdc_screen = 0
        self._buffer = None
        self._size = (0, 0)


def _win32_capture_rect(capture_rect: tuple[int, int, int, int]) -> Image.Image | None:
    ctx = _Win32CaptureContext()
    try:
        return ctx.capture(capture_rect)
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Win32 async recorder
# ---------------------------------------------------------------------------

class _AsyncWin32AviRecorder:
    """Background recorder using Win32 GDI capture."""

    def __init__(
        self,
        path: Path,
        hwnd: int,
        fps: int,
        quality: int,
        first_image: Image.Image,
        first_rect: tuple[int, int, int, int],
        *,
        max_dimension: int = 2560,
    ):
        self.path = path
        self.hwnd = hwnd
        self.fps = fps
        self.quality = quality
        self.frame_count = 0
        self.error: str | None = None
        self._first_image = first_image
        self._first_rect = first_rect
        self._target_size = _fit_frame_size(
            first_image.width, first_image.height, max_dimension
        )
        self._excluded_rects: tuple = ()
        self._excluded_lock = threading.Lock()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run, name="eDrawWin32Recorder", daemon=True
        )

    @classmethod
    def is_available(cls) -> bool:
        return _WIN32_ENABLED

    def start(self) -> None:
        self._thread.start()

    def update_excluded_rects(self, rects: tuple) -> None:
        with self._excluded_lock:
            self._excluded_rects = rects

    def stop(self, timeout: float = 10.0) -> tuple[int, str | None]:
        self._stop.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            self._set_error("Video recorder did not stop in time")
        return self.frame_count, self.error

    def _set_error(self, error: str) -> None:
        with self._lock:
            if not self.error:
                self.error = error

    def _current_excluded_rects(self) -> tuple:
        with self._excluded_lock:
            return self._excluded_rects

    def _prepare_frame(
        self, image: Image.Image, capture_rect: tuple[int, int, int, int]
    ) -> Image.Image:
        image = _resize_frame_if_needed(image, self._target_size)
        _draw_excluded_rects_on_pil(image, capture_rect, self._current_excluded_rects())
        return image

    def _run(self) -> None:
        writer: MjpegAviWriter | None = None
        context = _Win32CaptureContext()
        interval = 1 / max(1, self.fps)
        start_time = time.monotonic()
        last_capture_time = start_time
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                elapsed = now - start_time
                if now - last_capture_time < interval:
                    time.sleep(min(0.005, interval - (now - last_capture_time)))
                    continue
                last_capture_time = now
                frame = context.capture(self._first_rect)
                if frame is None:
                    time.sleep(0.01)
                    continue
                frame = self._prepare_frame(frame, self._first_rect)
                if writer is None:
                    writer = MjpegAviWriter(
                        self.path,
                        frame.width,
                        frame.height,
                        fps=self.fps,
                        quality=self.quality,
                    )
                writer.add_frame(frame)
                self.frame_count += 1
        except Exception as exc:
            self._set_error(str(exc))
        finally:
            context.close()
            if writer is not None:
                if self.frame_count > 1:
                    writer.set_actual_fps(self.frame_count / max(0.001, elapsed))
                writer.close()


# ---------------------------------------------------------------------------
# Public QObject-based recorder (used by the UI)
# ---------------------------------------------------------------------------

class WindowScreenRecorder(QObject):
    """Record the visible rectangle of a QWidget without blocking drawing input."""

    def __init__(
        self,
        window: QWidget,
        fps: int = 15,
        quality: int = 80,
        max_frame_dimension: int = 1920,
        excluded_rect_provider: Callable[[], list[QRect]] | None = None,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._fps = max(1, min(30, fps))
        self._quality = quality
        self._max_frame_dimension = max(480, int(max_frame_dimension))
        self._excluded_rect_provider = excluded_rect_provider
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.setInterval(int(1000 / self._fps))
        self._timer.timeout.connect(self._capture_frame)
        self._excluded_timer = QTimer(self)
        self._excluded_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._excluded_timer.setInterval(250)
        self._excluded_timer.timeout.connect(self._sync_worker_excluded_rects)
        self._encoder: _AsyncAviEncoder | None = None
        self._win32_worker: _AsyncWin32AviRecorder | None = None
        self._hwnd = 0
        self._path: Path | None = None
        self._started_at = 0.0
        self._last_elapsed = 0.0
        self._last_error: str | None = None

    @property
    def is_recording(self) -> bool:
        return self._encoder is not None or self._win32_worker is not None

    @property
    def current_path(self) -> Path | None:
        return self._path

    @property
    def elapsed_seconds(self) -> float:
        if self._encoder is not None or self._win32_worker is not None:
            return max(0.0, time.monotonic() - self._started_at)
        return self._last_elapsed

    def start(self) -> Path:
        if self.is_recording and self._path is not None:
            return self._path
        path = self._default_output_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._try_start_win32_worker(path):
            return path
        captured = self._grab_current_frame()
        if captured is None:
            raise RuntimeError("Could not capture the eDraw window")
        image, rect = captured
        self._path = path
        self._started_at = time.monotonic()
        self._last_elapsed = 0.0
        self._last_error = None
        encoder = _AsyncAviEncoder(
            path,
            image.width(),
            image.height(),
            self._fps,
            self._quality,
        )
        encoder.start()
        self._encoder = encoder
        encoder.submit(self._make_frame_packet(image, rect))
        self._timer.start()
        return path

    def stop(self) -> RecordingResult | None:
        encoder = self._encoder
        worker = self._win32_worker
        path = self._path
        if encoder is None and worker is None:
            return None
        if path is None:
            return None
        self._timer.stop()
        self._excluded_timer.stop()
        elapsed = max(0.0, time.monotonic() - self._started_at)
        if worker is not None:
            frame_count, error = worker.stop()
        else:
            assert encoder is not None
            frame_count, error = encoder.stop()
        error = error or self._last_error
        self._encoder = None
        self._win32_worker = None
        self._hwnd = 0
        self._path = None
        self._started_at = 0.0
        self._last_elapsed = elapsed
        return RecordingResult(
            path=path,
            frame_count=frame_count,
            elapsed_seconds=elapsed,
            error=error,
        )

    def _capture_frame(self) -> None:
        encoder = self._encoder
        if encoder is None:
            return
        if encoder.error:
            self._last_error = encoder.error
            self._timer.stop()
            return
        if encoder.is_backlogged():
            return
        captured = self._grab_current_frame()
        if captured is None:
            return
        image, rect = captured
        if not encoder.submit(self._make_frame_packet(image, rect)):
            self._last_error = encoder.error
            if self._last_error:
                self._timer.stop()
                return

    def _make_frame_packet(self, image: QImage, rect: QRect) -> _FramePacket:
        cursor = QCursor.pos()
        return _FramePacket(
            image=image,
            rect=QRect(rect),
            cursor_x=cursor.x(),
            cursor_y=cursor.y(),
            elapsed_seconds=max(0.0, time.monotonic() - self._started_at),
            excluded_rects=self._excluded_rects_for_frame(),
        )

    def _excluded_rects_for_frame(self) -> tuple[QRect, ...]:
        provider = self._excluded_rect_provider
        if provider is None:
            return ()
        try:
            return tuple(QRect(rect) for rect in provider() if rect is not None and not rect.isNull())
        except Exception:
            return ()

    def _try_start_win32_worker(self, path: Path) -> bool:
        if not _AsyncWin32AviRecorder.is_available():
            return False
        hwnd = int(self._window.winId())
        rect = _win32_client_rect(hwnd)
        if rect is None:
            return False
        image = _win32_capture_rect(rect)
        if image is None:
            return False
        self._path = path
        self._started_at = time.monotonic()
        self._last_elapsed = 0.0
        self._last_error = None
        self._hwnd = hwnd
        worker = _AsyncWin32AviRecorder(
            path,
            hwnd,
            self._fps,
            self._quality,
            image,
            rect,
            max_dimension=self._max_frame_dimension,
        )
        worker.update_excluded_rects(self._excluded_rects_for_worker(rect))
        worker.start()
        self._win32_worker = worker
        self._sync_worker_excluded_rects()
        self._excluded_timer.start()
        return True

    def _sync_worker_excluded_rects(self) -> None:
        worker = self._win32_worker
        if worker is None:
            return
        rect = _win32_client_rect(self._hwnd)
        if rect is None:
            worker.update_excluded_rects(())
            return
        worker.update_excluded_rects(self._excluded_rects_for_worker(rect))

    def _excluded_rects_for_worker(self, win_rect: tuple[int, int, int, int]) -> tuple[tuple[int, int, int, int], ...]:
        qt_window_rect = self._capture_rect()
        if qt_window_rect.isNull() or qt_window_rect.width() <= 0 or qt_window_rect.height() <= 0:
            return ()
        scale_x = (win_rect[2] - win_rect[0]) / max(1, qt_window_rect.width())
        scale_y = (win_rect[3] - win_rect[1]) / max(1, qt_window_rect.height())
        out = []
        for rect in self._excluded_rects_for_frame():
            x1 = win_rect[0] + int(round((rect.left() - qt_window_rect.left()) * scale_x))
            y1 = win_rect[1] + int(round((rect.top() - qt_window_rect.top()) * scale_y))
            x2 = win_rect[0] + int(round((rect.right() - qt_window_rect.left() + 1) * scale_x))
            y2 = win_rect[1] + int(round((rect.bottom() - qt_window_rect.top() + 1) * scale_y))
            if x2 > x1 and y2 > y1:
                out.append((x1, y1, x2, y2))
        return tuple(out)

    def _grab_current_frame(self) -> tuple[QImage, QRect] | None:
        rect = self._capture_rect()
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            return None
        screen = self._screen_for_rect(rect)
        if screen is None:
            return None
        pixmap = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
        if pixmap.isNull():
            return None
        image = pixmap.toImage().copy()
        return image, rect

    def _capture_rect(self) -> QRect:
        window = self._window
        if window.isMinimized() or not window.isVisible():
            return QRect()
        rect = QRect(window.geometry())
        rect.adjust(0, _CAPTURE_TOP_INSET, 0, 0)
        if rect.height() <= 0:
            return QRect()
        screen = self._screen_for_rect(rect)
        if screen is None:
            return rect
        return rect.intersected(screen.geometry())

    def _screen_for_rect(self, rect: QRect) -> QScreen | None:
        center = rect.center()
        screen = QGuiApplication.screenAt(center)
        if screen is not None:
            return screen
        handle = self._window.windowHandle()
        if handle is not None and handle.screen() is not None:
            return handle.screen()
        return QGuiApplication.primaryScreen()

    def _default_output_path(self) -> Path:
        movies = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)
        base = Path(movies) if movies else Path.home() / "Videos"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return base / f"eDraw_recording_{stamp}.avi"
