"""
Thin Win32 layer built only on ctypes (no pywin32 needed).

Everything the app does to *real* windows goes through this module:
listing top-level windows, listing monitors, moving/resizing, focusing,
always-on-top, minimise/restore, window icons.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes

from .icons import rgba_from_black_white
from .model import Monitor, Placement, Rect, WindowInfo

NAME = "win32"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------
GW_OWNER = 4
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
WS_CHILD = 0x40000000

SW_RESTORE = 9
SW_SHOW = 5
SW_MINIMIZE = 6
SW_SHOWNOACTIVATE = 4
SW_SHOWMAXIMIZED = 3
WPF_RESTORETOMAXIMIZED = 0x0002

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOOWNERZORDER = 0x0200
SWP_ASYNCWINDOWPOS = 0x4000

HWND_TOP = wintypes.HWND(0)
HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)

DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14

MONITORINFOF_PRIMARY = 1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
VK_LBUTTON = 0x01
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002

IGNORED_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "Windows.UI.Core.CoreWindow", "ThumbnailDeviceHelperWnd",
    "EdgeUiInputTopWndClass", "NotifyIconOverflowWindow",
    "tooltips_class32", "XamlExplorerHostIslandWindow",
}

# --------------------------------------------------------------------------
# prototypes (explicit types keep 64-bit handles from being truncated)
# --------------------------------------------------------------------------
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


def _proto(fn, restype, *argtypes):
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


_proto(user32.EnumWindows, wintypes.BOOL, WNDENUMPROC, wintypes.LPARAM)
_proto(user32.IsWindow, wintypes.BOOL, wintypes.HWND)
_proto(user32.IsWindowVisible, wintypes.BOOL, wintypes.HWND)
_proto(user32.IsIconic, wintypes.BOOL, wintypes.HWND)
_proto(user32.IsZoomed, wintypes.BOOL, wintypes.HWND)
_proto(user32.GetWindowTextLengthW, ctypes.c_int, wintypes.HWND)
_proto(user32.GetWindowTextW, ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_proto(user32.GetClassNameW, ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_proto(user32.GetWindow, wintypes.HWND, wintypes.HWND, wintypes.UINT)
_proto(user32.GetWindowThreadProcessId, wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_proto(user32.GetWindowRect, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_proto(user32.SetWindowPos, wintypes.BOOL, wintypes.HWND, wintypes.HWND,
       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
_proto(user32.ShowWindow, wintypes.BOOL, wintypes.HWND, ctypes.c_int)
_proto(user32.SetForegroundWindow, wintypes.BOOL, wintypes.HWND)
_proto(user32.GetForegroundWindow, wintypes.HWND)
_proto(user32.BringWindowToTop, wintypes.BOOL, wintypes.HWND)
_proto(user32.AttachThreadInput, wintypes.BOOL, wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
_proto(user32.GetAsyncKeyState, ctypes.c_short, ctypes.c_int)
_proto(user32.keybd_event, None, wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t)
_proto(user32.EnumDisplayMonitors, wintypes.BOOL, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
       MONITORENUMPROC, wintypes.LPARAM)
_proto(user32.GetMonitorInfoW, wintypes.BOOL, wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW))
_proto(user32.GetAncestor, wintypes.HWND, wintypes.HWND, wintypes.UINT)
_proto(user32.GetWindowPlacement, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT))
_proto(user32.SetWindowPlacement, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT))
_proto(kernel32.GetCurrentThreadId, wintypes.DWORD)
_proto(kernel32.OpenProcess, wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_proto(kernel32.CloseHandle, wintypes.BOOL, wintypes.HANDLE)
_proto(kernel32.QueryFullProcessImageNameW, wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD,
       wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
_proto(dwmapi.DwmGetWindowAttribute, ctypes.c_long, wintypes.HWND, wintypes.DWORD,
       ctypes.c_void_p, wintypes.DWORD)

if ctypes.sizeof(ctypes.c_void_p) == 8:
    _GetWindowLong = _proto(user32.GetWindowLongPtrW, ctypes.c_ssize_t, wintypes.HWND, ctypes.c_int)
else:  # pragma: no cover - 32-bit Python
    _GetWindowLong = _proto(user32.GetWindowLongW, ctypes.c_long, wintypes.HWND, ctypes.c_int)


# --------------------------------------------------------------------------
# DPI awareness - must run before any window (Tk) is created
# --------------------------------------------------------------------------
def enable_dpi_awareness() -> None:
    """Make coordinates physical pixels on every monitor (no Windows scaling blur)."""
    try:  # Windows 10 1703+: per-monitor v2
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:  # Windows 8.1+
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:  # Vista+
        user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _text(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _pid(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


_exe_cache: dict[int, str] = {}


def _exe_path(pid: int) -> str:
    if pid in _exe_cache:
        return _exe_cache[pid]
    path = ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if h:
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                path = buf.value
        finally:
            kernel32.CloseHandle(h)
    _exe_cache[pid] = path
    return path


def _is_cloaked(hwnd) -> bool:
    cloaked = ctypes.c_int(0)
    res = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return res == 0 and cloaked.value != 0


def _raw_rect(hwnd) -> Rect:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)


def _frame_rect(hwnd) -> Rect:
    """Visible bounds (without the invisible resize borders of Win10/11)."""
    r = wintypes.RECT()
    res = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r))
    if res != 0:
        return _raw_rect(hwnd)
    return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)


def _is_alt_tab_window(hwnd) -> bool:
    if not user32.IsWindowVisible(hwnd):
        return False
    if user32.GetWindow(hwnd, GW_OWNER):
        return False
    ex = _GetWindowLong(hwnd, GWL_EXSTYLE)
    if ex & WS_EX_TOOLWINDOW and not ex & WS_EX_APPWINDOW:
        return False
    if ex & WS_EX_NOACTIVATE and not ex & WS_EX_APPWINDOW:
        return False
    if _is_cloaked(hwnd):
        return False
    return True


# --------------------------------------------------------------------------
# public API (the fake backend implements the same functions)
# --------------------------------------------------------------------------
def list_windows() -> list[WindowInfo]:
    """Top-level windows the way Alt+Tab would show them, in Z-order (front first)."""
    own_pid = os.getpid()
    result: list[WindowInfo] = []

    def cb(hwnd, _lparam):
        try:
            if not _is_alt_tab_window(hwnd):
                return True
            title = _text(hwnd)
            if not title:
                return True
            cls = _class(hwnd)
            if cls in IGNORED_CLASSES:
                return True
            pid = _pid(hwnd)
            if pid == own_pid:
                return True
            path = _exe_path(pid)
            exe = os.path.basename(path) if path else "?"
            result.append(WindowInfo(int(hwnd), title, exe, path, cls, pid))
        except Exception:  # never let one odd window break the enumeration
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return result


def get_monitors() -> list[Monitor]:
    monitors: list[Monitor] = []

    def cb(hmon, _hdc, _rect, _lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            m, w = info.rcMonitor, info.rcWork
            monitors.append(Monitor(
                name=info.szDevice.replace("\\\\.\\", ""),
                full=Rect(m.left, m.top, m.right - m.left, m.bottom - m.top),
                work=Rect(w.left, w.top, w.right - w.left, w.bottom - w.top),
                primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
            ))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    monitors.sort(key=lambda mo: (not mo.primary, mo.full.x, mo.full.y))
    return monitors


def is_window(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def get_title(hwnd: int) -> str:
    return _text(hwnd)


def get_rect(hwnd: int) -> Rect:
    return _frame_rect(hwnd)


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))


def is_topmost(hwnd: int) -> bool:
    return bool(_GetWindowLong(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def place(hwnd: int, target: Rect, fast: bool = False) -> bool:
    """Move/resize so the *visible* frame exactly matches target.

    fast=True is used while the user is dragging something: one asynchronous
    pass, so a slow/hung app can never freeze Windower.
    """
    if not is_window(hwnd):
        return False
    if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER
    if fast:
        flags |= SWP_ASYNCWINDOWPOS
    ok = False
    # Twice: the first move can change the DPI (other monitor) and thus the borders.
    for _ in range(1 if fast else 2):
        raw, vis = _raw_rect(hwnd), _frame_rect(hwnd)
        dl, dt = vis.x - raw.x, vis.y - raw.y
        dr = (raw.x + raw.w) - (vis.x + vis.w)
        db = (raw.y + raw.h) - (vis.y + vis.h)
        ok = bool(user32.SetWindowPos(
            hwnd, None,
            target.x - dl, target.y - dt,
            target.w + dl + dr, target.h + dt + db,
            flags,
        ))
        if not ok:
            break
        if get_rect(hwnd).close_to(target, 2):
            break
    return ok


def save_placement(hwnd: int) -> Placement:
    """Remember where a window is so restore_placement() can put it back.

    A minimized window's rect is Windows' off-screen parking spot (-32000, -32000);
    moving it back there would leave it open but invisible and unreachable. So for
    minimized and maximized windows the WINDOWPLACEMENT (normal rect + state) is kept.
    """
    iconic, zoomed = bool(user32.IsIconic(hwnd)), bool(user32.IsZoomed(hwnd))
    if not iconic and not zoomed:
        return Placement(_frame_rect(hwnd))
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    if user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
        return Placement(None, zoomed or bool(wp.flags & WPF_RESTORETOMAXIMIZED), bytes(wp))
    return Placement(None if iconic else _frame_rect(hwnd))


def restore_placement(hwnd: int, p: Placement) -> bool:
    """Undo Windower's moves. A window that was minimized comes back un-minimized
    (maximized if that's what it was before minimizing), not hidden again."""
    if not is_window(hwnd):
        return False
    if p.native is None:
        return place(hwnd, p.rect) if p.rect else False
    wp = WINDOWPLACEMENT.from_buffer_copy(p.native)
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    wp.flags = 0
    wp.showCmd = SW_SHOWMAXIMIZED if p.maximized else SW_SHOWNOACTIVATE
    return bool(user32.SetWindowPlacement(hwnd, ctypes.byref(wp)))


def focus(hwnd: int) -> None:
    """Bring a window to the front and give it keyboard focus."""
    if not is_window(hwnd):
        return
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = False
    if fg_tid and fg_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
    try:
        user32.BringWindowToTop(hwnd)
        if not user32.SetForegroundWindow(hwnd):
            # Windows' focus-stealing prevention: a tapped Alt key unlocks it.
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, False)


def raise_no_focus(hwnd: int) -> None:
    """Show a window above the others without stealing keyboard focus."""
    if not is_window(hwnd):
        return
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def set_topmost(hwnd: int, on: bool) -> None:
    if is_window(hwnd):
        user32.SetWindowPos(hwnd, HWND_TOPMOST if on else HWND_NOTOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def minimize(hwnd: int) -> None:
    if is_window(hwnd):
        user32.ShowWindow(hwnd, SW_MINIMIZE)


def foreground() -> int:
    h = user32.GetForegroundWindow()
    return int(h) if h else 0


def root_window(hwnd: int) -> int:
    GA_ROOT = 2
    h = user32.GetAncestor(hwnd, GA_ROOT)
    return int(h) if h else hwnd


def mouse_button_down() -> bool:
    return bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)


def launch(exe_path: str) -> bool:
    try:
        if exe_path.lower().endswith(".exe"):
            subprocess.Popen([exe_path], close_fds=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        else:
            os.startfile(exe_path)  # type: ignore[attr-defined]
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# window icons
# --------------------------------------------------------------------------
WM_GETICON = 0x007F
ICON_SMALL, ICON_BIG, ICON_SMALL2 = 0, 1, 2
GCLP_HICON, GCLP_HICONSM = -14, -34
SMTO_ABORTIFHUNG = 0x0002
DI_NORMAL = 0x0003

gdi32 = ctypes.WinDLL("gdi32")


class BITMAPINFOHEADER(ctypes.Structure):
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


_proto(user32.SendMessageTimeoutW, wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
       wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
_proto(user32.DrawIconEx, wintypes.BOOL, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON,
       ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT)
_proto(user32.DestroyIcon, wintypes.BOOL, wintypes.HICON)
_proto(user32.PrivateExtractIconsW, wintypes.UINT, wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
       ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT), wintypes.UINT, wintypes.UINT)
_proto(gdi32.CreateCompatibleDC, wintypes.HDC, wintypes.HDC)
_proto(gdi32.CreateDIBSection, wintypes.HBITMAP, wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD)
_proto(gdi32.SelectObject, wintypes.HGDIOBJ, wintypes.HDC, wintypes.HGDIOBJ)
_proto(gdi32.DeleteObject, wintypes.BOOL, wintypes.HGDIOBJ)
_proto(gdi32.DeleteDC, wintypes.BOOL, wintypes.HDC)
_proto(gdi32.GdiFlush, wintypes.BOOL)

if ctypes.sizeof(ctypes.c_void_p) == 8:
    _GetClassLong = _proto(user32.GetClassLongPtrW, ctypes.c_size_t, wintypes.HWND, ctypes.c_int)
else:  # pragma: no cover - 32-bit Python
    _GetClassLong = _proto(user32.GetClassLongW, wintypes.DWORD, wintypes.HWND, ctypes.c_int)


def _hicon(hwnd: int, size: int) -> tuple[int, bool]:
    """(HICON, owned) for a window: its own icon, its class icon, or its exe's icon.
    Owned icons were created for us and must be destroyed."""
    small = size <= 16
    for kind in ((ICON_SMALL2, ICON_SMALL, ICON_BIG) if small else (ICON_BIG, ICON_SMALL2, ICON_SMALL)):
        res = ctypes.c_size_t(0)
        # timeout: a hung app must never freeze Windower
        if user32.SendMessageTimeoutW(hwnd, WM_GETICON, kind, 0, SMTO_ABORTIFHUNG, 100,
                                      ctypes.byref(res)) and res.value:
            return res.value, False
    for idx in ((GCLP_HICONSM, GCLP_HICON) if small else (GCLP_HICON, GCLP_HICONSM)):
        h = _GetClassLong(hwnd, idx)
        if h:
            return h, False
    path = _exe_path(_pid(hwnd))
    if path:
        h = wintypes.HICON()
        n = user32.PrivateExtractIconsW(path, 0, size, size, ctypes.byref(h), None, 1, 0)
        if n and n != 0xFFFFFFFF and h.value:
            return h.value, True
    return 0, False


def _render_icon(hicon: int, size: int) -> bytes | None:
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth, bmi.biHeight = size, -size  # negative height = rows top-down
    bmi.biPlanes, bmi.biBitCount = 1, 32
    dc = gdi32.CreateCompatibleDC(None)
    bits = ctypes.c_void_p()
    bmp = gdi32.CreateDIBSection(dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    if not bmp or not bits.value:
        gdi32.DeleteDC(dc)
        return None
    old = gdi32.SelectObject(dc, bmp)
    n = size * size * 4
    shots = []
    try:
        for bg in (0x00, 0xFF):
            ctypes.memset(bits, bg, n)
            if not user32.DrawIconEx(dc, 0, 0, hicon, size, size, 0, None, DI_NORMAL):
                return None
            gdi32.GdiFlush()
            shots.append(ctypes.string_at(bits, n))
    finally:
        gdi32.SelectObject(dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(dc)
    return rgba_from_black_white(*shots)


def window_icon(hwnd: int, size: int) -> bytes | None:
    """The window's icon as size x size RGBA pixels, or None if it has none."""
    hicon, owned = _hicon(hwnd, size)
    if not hicon:
        return None
    try:
        return _render_icon(hicon, size)
    finally:
        if owned:
            user32.DestroyIcon(hicon)


# --------------------------------------------------------------------------
# input state
# --------------------------------------------------------------------------
VK_SHIFT = 0x10
_proto(user32.GetCursorPos, wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
_proto(user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW,
       ctypes.c_ssize_t, wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
_SetWindowLong = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW


def cursor_pos() -> tuple[int, int]:
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def shift_down() -> bool:
    return bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)


WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020


def style_overlay(tk_hwnd: int, click_through: bool) -> None:
    """Make one of our own Tk popups a no-activate tool window (optionally click-through).

    No-activate means clicking it never steals keyboard focus from the app you
    are working in; tool window keeps it out of Alt+Tab and the taskbar.
    """
    hwnd = root_window(tk_hwnd)
    ex = _GetWindowLong(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    ex &= ~WS_EX_APPWINDOW
    if click_through:
        ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT
    _SetWindowLong(hwnd, GWL_EXSTYLE, ex)


# --------------------------------------------------------------------------
# background thread: window move/resize events + global hotkeys
# --------------------------------------------------------------------------
import queue  # noqa: E402
import threading  # noqa: E402

WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                  wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
EVENT_SYSTEM_MOVESIZESTART = 0x000A
EVENT_SYSTEM_MOVESIZEEND = 0x000B
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
WM_QUIT = 0x0012
WM_HOTKEY = 0x0312
WM_APP_HOTKEYS = 0x8001
MOD_NOREPEAT = 0x4000
PM_NOREMOVE = 0

_proto(user32.SetWinEventHook, wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
       WINEVENTPROC, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD)
_proto(user32.UnhookWinEvent, wintypes.BOOL, wintypes.HANDLE)
_proto(user32.RegisterHotKey, wintypes.BOOL, wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
_proto(user32.UnregisterHotKey, wintypes.BOOL, wintypes.HWND, ctypes.c_int)
_proto(user32.GetMessageW, wintypes.BOOL, ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
_proto(user32.PeekMessageW, wintypes.BOOL, ctypes.POINTER(wintypes.MSG), wintypes.HWND,
       wintypes.UINT, wintypes.UINT, wintypes.UINT)
_proto(user32.TranslateMessage, wintypes.BOOL, ctypes.POINTER(wintypes.MSG))
_proto(user32.DispatchMessageW, ctypes.c_ssize_t, ctypes.POINTER(wintypes.MSG))
_proto(user32.PostThreadMessageW, wintypes.BOOL, wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class EventSource:
    """
    Runs a tiny Win32 message loop on its own thread and reports:
      ("movesize_start", hwnd) / ("movesize_end", hwnd)  - a user starts/stops
                                                          dragging or resizing a window
      ("hotkey", id)                                      - a registered global hotkey
      ("hotkey_failed", [ids])                            - combos taken by another app
    The Tk thread reads them with poll(); no Tk calls ever happen on this thread.
    """

    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self._tid = 0
        self._hotkeys: list[tuple[int, int, int]] = []
        self._registered: list[int] = []
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="windower-events", daemon=True)
        self._thread.start()
        self._ready.wait(3)

    # -- called from the Tk thread --------------------------------------
    def poll(self) -> list[tuple]:
        out = []
        while True:
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                return out

    def set_hotkeys(self, hotkeys: list[tuple[int, int, int]]) -> None:
        """hotkeys = [(id, modifiers, virtual_key)]; registration happens on the event thread."""
        self._hotkeys = list(hotkeys)
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_APP_HOTKEYS, 0, 0)

    def stop(self) -> None:
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    # -- event thread ----------------------------------------------------
    def _on_event(self, _hook, event, hwnd, id_object, _id_child, _tid, _time):
        try:
            if id_object == 0 and hwnd:  # OBJID_WINDOW
                kind = "movesize_start" if event == EVENT_SYSTEM_MOVESIZESTART else "movesize_end"
                self.q.put((kind, int(hwnd)))
        except Exception:
            pass

    def _register(self) -> None:
        for hid in self._registered:
            user32.UnregisterHotKey(None, hid)
        self._registered, failed = [], []
        for hid, mods, vk in self._hotkeys:
            if user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
                self._registered.append(hid)
            else:
                failed.append(hid)
        if failed:
            self.q.put(("hotkey_failed", failed))

    def _run(self) -> None:
        msg = wintypes.MSG()
        self._tid = kernel32.GetCurrentThreadId()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)  # create the queue
        self._proc = WINEVENTPROC(self._on_event)  # keep a reference or it gets collected
        hook = user32.SetWinEventHook(EVENT_SYSTEM_MOVESIZESTART, EVENT_SYSTEM_MOVESIZEEND, None,
                                      self._proc, 0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
        self._ready.set()
        try:
            while True:
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0 or r == -1:
                    break
                if msg.message == WM_HOTKEY:
                    self.q.put(("hotkey", int(msg.wParam)))
                elif msg.message == WM_APP_HOTKEYS:
                    self._register()
                else:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            for hid in self._registered:
                user32.UnregisterHotKey(None, hid)
            if hook:
                user32.UnhookWinEvent(hook)
