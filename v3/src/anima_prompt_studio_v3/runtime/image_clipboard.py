"""Put an existing image file on the Windows clipboard for Explorer paste.

CF_HDROP points at the original file. PNG and CF_DIB are immediate-rendered
extras for applications that paste pixels rather than files. No clipboard
contents are read by this module.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import struct
import sys
import threading
import time

from PIL import Image, ImageOps


CF_HDROP = 15
CF_DIB = 8
GMEM_MOVEABLE = 0x0002
DROPEFFECT_COPY = 1
_OPEN_ATTEMPTS = 6
_OPEN_PAUSE_SECONDS = 0.035
_COPY_LOCK = threading.Lock()


class ClipboardUnsupportedError(RuntimeError):
    """Native file clipboard is unavailable on this platform."""


class ClipboardWriteError(RuntimeError):
    """The original image could not be prepared or published to the clipboard."""


@dataclass(frozen=True)
class _PreparedImage:
    path: Path
    dropfiles: bytes
    png: bytes
    dib: bytes


def _is_windows() -> bool:
    return sys.platform == "win32"


def _prepare(path: Path) -> _PreparedImage:
    try:
        original = Path(path).resolve(strict=True)
        if not original.is_file():
            raise ValueError("Not a file")
        with Image.open(original) as source:
            source.seek(0)  # Multi-frame inputs contribute their first image.
            source.load()
            displayed = ImageOps.exif_transpose(source)
            width, height = displayed.size
            if width < 1 or height < 1:
                raise ValueError("Image has no pixels")
            rgba = displayed.convert("RGBA")
            if source.format == "PNG":
                png = original.read_bytes()
            else:
                output = BytesIO()
                rgba.save(output, format="PNG")
                png = output.getvalue()
            # Positive biHeight means bottom-up scanlines. BI_RGB, 32 bpp BGRA.
            pixels = rgba.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes("raw", "BGRA")
            header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 32, 0,
                                 len(pixels), 0, 0, 0, 0)
        dropfiles = struct.pack("<IiiII", 20, 0, 0, 0, 1) + (str(original) + "\0\0").encode("utf-16-le")
        return _PreparedImage(original, dropfiles, png, header + pixels)
    except Exception as exc:
        raise ClipboardWriteError("无法读取或准备原图，剪贴板未修改。") from exc


class _Win32Api:
    """Pointer-size-safe declarations for immediate Windows clipboard data."""

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32, kernel32 = self.user32, self.kernel32

        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HGLOBAL]
        user32.SetClipboardData.restype = wintypes.HGLOBAL
        user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterClipboardFormatW.restype = wintypes.UINT

        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL

    def register_format(self, name: str) -> int:
        value = self.user32.RegisterClipboardFormatW(name)
        if not value:
            raise ClipboardWriteError(f"无法注册剪贴板格式：{name}。")
        return value

    def alloc(self, data: bytes) -> int:
        handle = self.kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise ClipboardWriteError("无法分配剪贴板内存。")
        try:
            address = self.kernel32.GlobalLock(handle)
            if not address:
                raise ClipboardWriteError("无法写入剪贴板内存。")
            try:
                ctypes.memmove(address, data, len(data))
            finally:
                self.kernel32.GlobalUnlock(handle)
        except BaseException:
            self.kernel32.GlobalFree(handle)
            raise
        return handle

    def free(self, handle: int) -> None:
        self.kernel32.GlobalFree(handle)

    def create_owner(self) -> int:
        # Built-in STATIC class, top-level and never shown. Passing NULL to
        # OpenClipboard would leave no owner after EmptyClipboard.
        owner = self.user32.CreateWindowExW(0, "STATIC", "Anima Clipboard Owner", 0,
                                            0, 0, 0, 0, None, None, None, None)
        if not owner:
            raise ClipboardWriteError("无法创建剪贴板窗口。")
        return owner

    def destroy_owner(self, owner: int) -> None:
        self.user32.DestroyWindow(owner)

    def open(self, owner: int) -> bool:
        return bool(self.user32.OpenClipboard(owner))

    def empty(self) -> bool:
        return bool(self.user32.EmptyClipboard())

    def set(self, format_id: int, handle: int) -> bool:
        return bool(self.user32.SetClipboardData(format_id, handle))

    def close(self) -> None:
        self.user32.CloseClipboard()


def _windows_api() -> _Win32Api:
    return _Win32Api()


def _publish(payload: _PreparedImage) -> None:
    api = _windows_api()
    preferred_format = api.register_format("Preferred DropEffect")
    png_format = api.register_format("PNG")
    formats = [
        (preferred_format, struct.pack("<I", DROPEFFECT_COPY), True),
        (CF_HDROP, payload.dropfiles, True),
        (png_format, payload.png, False),
        (CF_DIB, payload.dib, False),
    ]
    allocated: list[tuple[int, int, bool]] = []
    owner: int | None = None
    opened = False
    try:
        # All bytes and HGLOBAL blocks exist before EmptyClipboard can run.
        for format_id, data, required in formats:
            allocated.append((format_id, api.alloc(data), required))
        owner = api.create_owner()
        for attempt in range(_OPEN_ATTEMPTS):
            if api.open(owner):
                opened = True
                break
            if attempt + 1 < _OPEN_ATTEMPTS:
                time.sleep(_OPEN_PAUSE_SECONDS)
        if not opened:
            raise ClipboardWriteError("剪贴板正忙，请稍后重试。")
        if not api.empty():
            raise ClipboardWriteError("无法清空剪贴板以写入图片。")
        for format_id, handle, required in tuple(allocated):
            if api.set(format_id, handle):
                allocated.remove((format_id, handle, required))  # System now owns it.
            elif required:
                raise ClipboardWriteError("无法写入图片文件到剪贴板。")
            # Pixel formats are supplementary; CF_HDROP remains useful alone.
    except ClipboardWriteError:
        raise
    except Exception as exc:
        raise ClipboardWriteError("无法写入图片文件到剪贴板。") from exc
    finally:
        if opened:
            api.close()
        for _, handle, _ in allocated:
            api.free(handle)
        if owner is not None:
            api.destroy_owner(owner)


def copy_image_file(path: Path) -> None:
    """Copy an existing image file for Explorer and image-aware paste targets."""
    if not _is_windows():
        raise ClipboardUnsupportedError("仅 Windows 支持复制图片文件到系统剪贴板。")
    payload = _prepare(path)
    with _COPY_LOCK:
        _publish(payload)
