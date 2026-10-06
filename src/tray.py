# -*- coding: utf-8 -*-
"""任务栏托盘图标（开关）。

纯 ctypes 调用 Windows 原生接口, 不引入第三方库:
  - Shell_NotifyIconW 注册托盘图标
  - 自己构造 RT_ICON 数据, 用 CreateIconFromResourceEx 生成图标
  - 右键弹出菜单用 TrackPopupMenu 的 TPM_RETURNCMD 模式, 直接拿到选中项

图标在 run() 所在的线程里跑自己的消息循环, 所以要放在独立线程里启动。
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

WM_APP = 0x8000
WM_DESTROY = 0x0002
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_CHECKED = 0x00000008
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100

ID_TOGGLE = 1001
ID_SETTINGS = 1003
ID_QUIT = 1002
ID_NOTEBOOK_TOGGLE = 1004
ID_NOTEBOOK_OPEN = 1005

CALLBACK_MESSAGE = WM_APP + 1
ICON_SIZE = 32

# 状态灯只分"开"和"关"两大块:
#   开   -> 绿（不管 API 有没有接）
#   关   -> 黄（正常）/ 红（API 没接入）
# 红黄是"关"这一档里的细分, 所以关掉之后才需要区分。
STATE_COLORS = {
    "on": (46, 204, 113),
    "off": (241, 196, 15),
    "noapi": (231, 76, 60),
}
STATE_LABELS = {
    "on": "已开启",
    "off": "已关闭",
    "noapi": "API 未接入",
}
# 悬停提示里的操作说明
HINT = "（左键切换，双击设置，右键菜单）"

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeout", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
    ]


user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateIconFromResourceEx.restype = wintypes.HICON
user32.CreateIconFromResourceEx.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL,
                                            wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                            wintypes.UINT]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetDoubleClickTime.restype = wintypes.UINT
user32.RegisterClassW.restype = wintypes.ATOM
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.DestroyMenu.argtypes = [wintypes.HMENU]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]


def make_icon_data(rgb, size=ICON_SIZE, radius=None):
    """手工构造一份 RT_ICON 数据: BITMAPINFOHEADER + 颜色位图 + 掩码。

    画一个实心圆, 边缘做一点抗锯齿, 免得在托盘里显得毛毛躁躁。
    """
    if radius is None:
        radius = size / 2.0 - 1.0
    cx = cy = (size - 1) / 2.0
    r, g, b = rgb
    rows = []
    for y in range(size - 1, -1, -1):      # 位图是自下而上存的
        row = bytearray()
        for x in range(size):
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if dist <= radius - 0.5:
                alpha = 255
            elif dist >= radius + 0.5:
                alpha = 0
            else:
                alpha = int(255 * (radius + 0.5 - dist))
            row += bytes((b, g, r, alpha))
        rows.append(bytes(row))
    xor = b"".join(rows)

    mask_stride = ((size + 31) // 32) * 4
    mask = b"\x00" * (mask_stride * size)

    header = ctypes.create_string_buffer(40)
    ctypes.memmove(header, ctypes.byref(ctypes.c_uint32(40)), 4)
    ctypes.memmove(ctypes.byref(header, 4), ctypes.byref(ctypes.c_int32(size)), 4)
    ctypes.memmove(ctypes.byref(header, 8), ctypes.byref(ctypes.c_int32(size * 2)), 4)
    ctypes.memmove(ctypes.byref(header, 12), ctypes.byref(ctypes.c_uint16(1)), 2)
    ctypes.memmove(ctypes.byref(header, 14), ctypes.byref(ctypes.c_uint16(32)), 2)
    return bytes(header) + xor + mask


def create_icon(rgb, size=ICON_SIZE):
    data = make_icon_data(rgb, size)
    buffer = ctypes.create_string_buffer(data, len(data))
    return user32.CreateIconFromResourceEx(buffer, len(data), True, 0x00030000,
                                           0, 0, 0)


class TrayIcon:
    """托盘图标。左键单击切换开关, 双击打开设置, 右键出菜单。

    状态灯只表达两件大事: 开着还是关着。
      绿 = 开启（API 接没接都算开启, 一律绿灯）
      黄 = 关闭, 且 API 已接入
      红 = 关闭, 且 API 没接入（提醒去设置里补密钥）
    所以"开关"永远优先于"API 状态"; 那盏红/黄灯只在关掉时才出来说话。

    单击和双击要分开处理: Windows 收到双击时, 会先发一次单击再发双击,
    所以单击不能立刻执行, 得压到"双击间隔"之后再算数——否则双击会先切一次
    开关、再打开设置, 用户看到的就是"点一下开关自己变了"。
    """

    def __init__(self, enabled=True, api_ready=True, on_toggle=None, on_quit=None,
                 on_settings=None, notebook_enabled=True,
                 on_notebook_toggle=None, on_notebook_open=None,
                 tip="选中即查", logger=None):
        self.enabled = enabled
        self.api_ready = bool(api_ready)
        self.notebook_enabled = bool(notebook_enabled)
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self.on_settings = on_settings
        self.on_notebook_toggle = on_notebook_toggle
        self.on_notebook_open = on_notebook_open
        self.tip = tip
        self.log = logger or (lambda message: None)

        self._icons = {name: create_icon(rgb) for name, rgb in STATE_COLORS.items()}
        self._hwnd = None
        self._proc = WNDPROC(self._wnd_proc)
        self._class_atom = None
        self._ready = threading.Event()
        self._thread = None
        self._nid = None
        self._pending_click = None       # 等待中的单击（还没确定是不是双击）
        self._skip_next_up = False       # 双击之后紧跟的那个抬起要丢掉
        try:
            self.double_click_interval = user32.GetDoubleClickTime() / 1000.0
        except Exception:
            self.double_click_interval = 0.5

    # ------------------------------------------------------------------

    @property
    def state(self):
        """当前该显示哪盏灯。先看开没开, 关着的时候才细分黄/红。"""
        if self.enabled:
            return "on"
        return "off" if self.api_ready else "noapi"

    def _tip_text(self):
        if self.state == "noapi":
            return "%s · 已关闭 · API 未接入（去设置里填密钥）%s" % (self.tip, HINT)
        return "%s · %s%s" % (self.tip, STATE_LABELS[self.state], HINT)

    def _wnd_proc(self, hwnd, msg, w_param, l_param):
        if msg == CALLBACK_MESSAGE:
            if l_param == WM_LBUTTONUP:
                self._on_lbutton_up()
            elif l_param == WM_LBUTTONDBLCLK:
                self._on_lbutton_dblclk()
            elif l_param == WM_RBUTTONUP:
                self._show_menu()
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, w_param, l_param)

    # ----- 单击 / 双击 -----

    def _on_lbutton_up(self):
        if self._skip_next_up:
            # 这是双击里跟出来的那一次抬起, 丢掉
            self._skip_next_up = False
            return
        if self._pending_click is not None:
            # 双击间隔内又点了一次: 当双击算
            self._cancel_pending_click()
            self._open_settings()
            return
        timer = threading.Timer(self.double_click_interval, self._fire_pending_click)
        timer.daemon = True
        self._pending_click = timer
        timer.start()

    def _on_lbutton_dblclk(self):
        self._skip_next_up = True
        self._cancel_pending_click()
        self._open_settings()

    def _cancel_pending_click(self):
        timer = self._pending_click
        self._pending_click = None
        if timer is not None:
            timer.cancel()

    def _fire_pending_click(self):
        """等到双击间隔过完还没等到第二次点击, 那就确实是单击。"""
        self._pending_click = None
        self._fire_toggle()

    def _open_settings(self):
        self._fire("on_settings", "tray settings error")

    def _fire_toggle(self):
        if self.on_toggle:
            try:
                self.on_toggle()
            except Exception as exc:
                self.log("tray toggle error: %s" % exc)

    def _show_menu(self):
        menu = user32.CreatePopupMenu()
        flags = MF_STRING | (MF_CHECKED if self.enabled else 0)
        user32.AppendMenuW(menu, flags, ID_TOGGLE, "启用取词")
        note_flags = MF_STRING | (MF_CHECKED if self.notebook_enabled else 0)
        user32.AppendMenuW(menu, note_flags, ID_NOTEBOOK_TOGGLE, "自动收录到生词本")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_NOTEBOOK_OPEN, "打开生词本")
        user32.AppendMenuW(menu, MF_STRING, ID_SETTINGS, "设置...")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_QUIT, "退出")

        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        # 这是 Windows 的经典要求, 否则菜单点外面不会消失
        user32.SetForegroundWindow(self._hwnd)
        choice = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                       point.x, point.y, 0, self._hwnd, None)
        user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)

        if choice == ID_TOGGLE:
            self._fire_toggle()
        elif choice == ID_NOTEBOOK_TOGGLE:
            self._fire("on_notebook_toggle", "tray notebook toggle error")
        elif choice == ID_NOTEBOOK_OPEN:
            self._fire("on_notebook_open", "tray notebook open error")
        elif choice == ID_SETTINGS:
            self._fire("on_settings", "tray settings error")
        elif choice == ID_QUIT:
            self._fire("on_quit", "tray quit error")

    def _fire(self, name, message):
        callback = getattr(self, name, None)
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            self.log("%s: %s" % (message, exc))

    # ------------------------------------------------------------------

    def _refresh(self):
        """把当前状态同步到托盘上。没注册好就什么都不做。"""
        if not self._hwnd or not self._nid:
            return
        self._nid.hIcon = self._icons[self.state]
        self._nid.szTip = self._tip_text()
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))

    def _add_icon(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = CALLBACK_MESSAGE
        nid.hIcon = self._icons[self.state]
        nid.szTip = self._tip_text()
        self._nid = nid
        ok = shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        self.log("托盘图标注册%s" % ("成功" if ok else "失败"))
        return bool(ok)

    def set_enabled(self, enabled):
        """更新开关状态。开着就是绿灯, 关掉才分黄/红。"""
        self.enabled = bool(enabled)
        self._refresh()

    def set_api_ready(self, ready):
        """翻译用的 API 有没有接上。只在"关闭"状态下影响灯色（黄/红）。"""
        ready = bool(ready)
        if ready == self.api_ready:
            return
        self.api_ready = ready
        self.log("托盘状态: %s" % ("API 已接入" if ready else "API 未接入（红灯）"))
        self._refresh()

    def set_notebook_enabled(self, enabled):
        """只影响右键菜单里的勾选状态。"""
        self.notebook_enabled = bool(enabled)

    def run(self):
        """阻塞运行消息循环。请放在独立线程里。"""
        hinst = kernel32.GetModuleHandleW(None)
        name = "LookupTrayWnd_%d" % id(self)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = name
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            self.log("RegisterClassW 失败, 错误码 %d" % ctypes.get_last_error())
            self._ready.set()
            return
        self._class_atom = atom
        self._hwnd = user32.CreateWindowExW(0, name, name, 0, 0, 0, 0, 0,
                                            None, None, hinst, None)
        if not self._hwnd:
            self.log("CreateWindowExW 失败, 错误码 %d" % ctypes.get_last_error())
            self._ready.set()
            return
        self._add_icon()
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def start(self):
        self._thread = threading.Thread(target=self.run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)
        return self

    def stop(self):
        self._cancel_pending_click()
        if self._nid:
            try:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            except Exception:
                pass
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)
