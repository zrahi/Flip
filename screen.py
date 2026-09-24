"""Screen sharing: lists what can be shared (screens and windows) and grabs a picture of it."""

import base64
import io
import logging
import sys

log = logging.getLogger("flip")

MAX_SIDE = 1280  # pictures get shrunk to this so they're quick for the brain to look at
SKIP_TITLES = {"Program Manager", "Flip pet", "Windows Input Experience", "Settings", "Microsoft Text Input Application"}


def sources(own_titles=()):
    """[{"id", "title", "kind"}] of screens and open windows you can share."""
    items = [{"id": f"screen:{i}", "title": title, "kind": "screen"} for i, title in enumerate(_screens_titles())]
    if sys.platform == "win32":
        skip = SKIP_TITLES | set(own_titles)
        items += [w for w in _windows() if w["title"] not in skip]
    return items


def capture(source_id):
    """A JPEG (as a data: URL) of what's on the chosen screen/window right now, or None."""
    img = _grab(source_id)
    if img is None:
        return None
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _grab(source_id):
    from PIL import ImageGrab

    kind, _, ref = source_id.partition(":")
    try:
        if kind == "screen":
            monitors = _monitor_rects()
            i = int(ref)
            if i < len(monitors):
                return ImageGrab.grab(bbox=monitors[i], all_screens=True)
            return ImageGrab.grab(all_screens=True)
        if kind == "win" and sys.platform == "win32":
            return _grab_window(int(ref))
    except Exception:
        log.exception("Screen grab failed")
    return None


# ---------- Windows plumbing ----------

def _user32():
    import ctypes
    from ctypes import wintypes as wt

    u = ctypes.windll.user32
    u.GetWindowDC.restype = wt.HDC
    u.GetWindowDC.argtypes = [wt.HWND]
    u.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    u.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
    u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    u.IsWindowVisible.argtypes = [wt.HWND]
    u.IsIconic.argtypes = [wt.HWND]
    u.IsWindow.argtypes = [wt.HWND]
    u.GetWindowTextLengthW.argtypes = [wt.HWND]
    u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    u.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
    return u


def _windows():
    import ctypes
    from ctypes import wintypes as wt

    user32 = _user32()
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        if user32.GetWindowLongW(hwnd, -20) & 0x80:  # WS_EX_TOOLWINDOW: little helper windows
            return True
        cloaked = wt.DWORD()
        ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), 14, ctypes.byref(cloaked), 4)
        if cloaked.value:  # hidden by Windows (other virtual desktop, suspended app…)
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        found.append({"id": f"win:{hwnd}", "title": buf.value, "kind": "window"})
        return True

    user32.EnumWindows(each, 0)
    return found


def _monitor_rects():
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes as wt

    rects = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
    def each(_mon, _hdc, rect, _):
        r = rect.contents
        rects.append((r.left, r.top, r.right, r.bottom))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, each, 0)
    return rects


def _screens_titles():
    n = len(_monitor_rects()) or 1
    return ["Entire screen"] if n == 1 else [f"Screen {i + 1}" for i in range(n)]


def _grab_window(hwnd):
    """Pictures one window, even if other windows are on top of it."""
    import ctypes
    from ctypes import wintypes as wt

    from PIL import Image, ImageGrab

    user32 = _user32()
    gdi32 = ctypes.windll.gdi32
    gdi32.CreateCompatibleDC.restype = wt.HDC
    gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
    gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = wt.HGDIOBJ
    gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
    gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wt.HDC]

    if not user32.IsWindow(hwnd):
        return None
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        user32.PrintWindow(hwnd, mem, 2)  # PW_RENDERFULLCONTENT: works for browsers and modern apps too
        info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem, bmp, 0, h, pixels, ctypes.byref(info), 0)
        img = Image.frombuffer("RGB", (w, h), pixels, "raw", "BGRX", 0, 1)
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)
    # Some games draw straight to the graphics card and come out black this way;
    # then take that part of the screen instead.
    if img.convert("L").getextrema()[1] < 8:
        img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True)
    return img
