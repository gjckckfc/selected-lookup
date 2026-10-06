# -*- coding: utf-8 -*-
"""全局鼠标钩子 + 剪贴板取词。

设计要点:
  - 底层钩子回调必须尽快返回，否则会拖慢整个系统的鼠标响应，
    所以回调里只做"记录坐标 + 投递事件"，真正的取词交给独立线程。
  - 取词用"模拟 Ctrl+C + 读剪贴板"，兼容性最好；
    取完把剪贴板原样还回去，不打扰用户原本复制的东西。
  - 用 GetClipboardSequenceNumber 判断这次复制是否真的产生了新内容，
    避免"选了但没复制到"时弹出空结果。
"""
from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_HOTKEY = 0x0312

VK_ESCAPE = 0x1B

VK_CONTROL = 0x11
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# 热键修饰符
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]


# --------------------------------------------------------------------------
# 剪贴板
# --------------------------------------------------------------------------

def _open_clipboard(retries=6, delay=0.03):
    """打开剪贴板。别的进程可能正占着, 所以要重试几次。"""
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(delay)
    return False


def read_clipboard_text():
    """读剪贴板里的文本；没有文本返回 None。"""
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    if not _open_clipboard():
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def write_clipboard_text(text):
    """把文本写回剪贴板。"""
    if not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        size = (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar)
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return False
        ctypes.memmove(ptr, ctypes.create_unicode_buffer(text), size)
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(CF_UNICODETEXT, handle)
        return True
    finally:
        user32.CloseClipboard()


def send_ctrl_c():
    """模拟一次 Ctrl+C。"""
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_C, 0, 0, 0)
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def grab_selected_text(timeout=0.45):
    """复制当前选中内容并返回，同时把用户原来的剪贴板还回去。

    返回 None 表示这次没有取到文本（没选中、或目标程序不支持复制）。
    """
    backup = read_clipboard_text()
    seq_before = user32.GetClipboardSequenceNumber()
    send_ctrl_c()

    text = None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.02)
        if user32.GetClipboardSequenceNumber() != seq_before:
            text = read_clipboard_text()
            if text:
                break
            seq_before = user32.GetClipboardSequenceNumber()

    if backup is not None:
        # 稍微等一下，避免和源程序的剪贴板写入打架
        time.sleep(0.06)
        write_clipboard_text(backup)

    return text


# --------------------------------------------------------------------------
# 鼠标钩子
# --------------------------------------------------------------------------

class SelectionWatcher:
    """监听鼠标与键盘, 判断"现在还有没有选中文字"。

    两种事件:
      - 拖选一段距离后松开  -> 触发取词(显示浮窗)
      - 不带拖动的单击 / 按 Esc -> 视为取消选中(收起浮窗)
    """

    def __init__(self, on_selection, on_dismiss=None, on_hotkey=None,
                 drag_threshold=6, hotkeys=(), logger=None, on_fault=None):
        self.on_selection = on_selection
        self.on_dismiss = on_dismiss
        self.on_hotkey = on_hotkey
        self.on_fault = on_fault
        self.drag_threshold = drag_threshold
        self.hotkeys = list(hotkeys)
        self.log = logger or (lambda msg: None)

        self._events = queue.Queue()
        self._down_pt = None
        self._ignore_rect = None         # 浮窗占的区域, 按在这里的手势全局逻辑不参与
        self._ignored = False
        self._last_down_time = 0.0
        self._click_count = 0
        self.double_click_window = 0.4   # 两次按下间隔小于这个值算双击
        self._proc_ref = HOOKPROC(self._hook_proc)
        self._kb_proc_ref = HOOKPROC(self._kb_proc)
        self._thread = None
        self._thread_id = None
        self._hook = None
        self._kb_hook = None
        self._stop = threading.Event()
        self.paused = False

        # 取词线程：钩子回调只投递，这里做慢活
        self._worker = threading.Thread(target=self._work, name="grab", daemon=True)
        self._worker.start()

    # ----- 钩子回调：必须是"快进快出" -----

    def set_ignore_rect(self, rect):
        """告诉钩子: 这块矩形是浮窗自己的地盘(拖动、点按钮用)。传 None 表示没有。"""
        self._ignore_rect = tuple(rect) if rect else None

    def _in_ignore_rect(self, x, y):
        rect = self._ignore_rect
        if not rect:
            return False
        left, top, right, bottom = rect
        return left <= x <= right and top <= y <= bottom

    def _hook_proc(self, n_code, w_param, l_param):
        if n_code == 0:
            try:
                if w_param == WM_LBUTTONDOWN:
                    data = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    x, y = data.pt.x, data.pt.y
                    self._ignored = self._in_ignore_rect(x, y)
                    if self._ignored:
                        # 按在浮窗上: 这次手势完全交给浮窗, 不取词也不收起
                        self._down_pt = None
                    else:
                        self._down_pt = (x, y)
                        now = time.monotonic()
                        if now - self._last_down_time <= self.double_click_window:
                            self._click_count += 1
                        else:
                            self._click_count = 1
                        self._last_down_time = now
                elif w_param == WM_LBUTTONUP:
                    data = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    start = self._down_pt
                    self._down_pt = None
                    if self._ignored:
                        self._ignored = False
                    elif start and not self.paused:
                        dx = abs(data.pt.x - start[0])
                        dy = abs(data.pt.y - start[1])
                        if dx >= self.drag_threshold or dy >= self.drag_threshold:
                            self._events.put((data.pt.x, data.pt.y))
                        elif self._click_count >= 2:
                            # 双击/三击也能选中词, 按取词处理
                            self._events.put((data.pt.x, data.pt.y))
                        elif self.on_dismiss:
                            # 普通单击 = 取消选中, 立即收起
                            self.on_dismiss()
            except Exception as exc:  # 钩子里绝不能抛异常出去
                self.log("hook error: %s" % exc)
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _kb_proc(self, n_code, w_param, l_param):
        """只观察, 不吞按键: 按 Esc 视为取消选中。"""
        if n_code == 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
            try:
                data = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if data.vkCode == VK_ESCAPE and not self.paused and self.on_dismiss:
                    self.on_dismiss()
            except Exception as exc:
                self.log("kb hook error: %s" % exc)
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    # ----- 取词线程 -----

    def _work(self):
        while not self._stop.is_set():
            try:
                x, y = self._events.get(timeout=0.02)
            except queue.Empty:
                x = y = None

            if x is not None:
                try:
                    text = grab_selected_text()
                except Exception as exc:
                    self.log("grab error: %s" % exc)
                    continue
                if text and text.strip() and self.on_selection:
                    try:
                        self.on_selection(text.strip(), x, y)
                    except Exception as exc:
                        self.log("callback error: %s" % exc)

    # ----- 生命周期 -----

    def _report_fault(self, reason):
        """钩子这一层坏了就上报, 让托盘亮红灯。"""
        if not self.on_fault:
            return
        try:
            self.on_fault(reason)
        except Exception as exc:
            self.log("fault callback error: %s" % exc)

    def start(self):
        self._thread = threading.Thread(target=self._run, name="hook", daemon=True)
        self._thread.start()
        return self

    def _run(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc_ref, None, 0)
        if not self._hook:
            code = ctypes.get_last_error()
            self.log("SetWindowsHookExW 失败，错误码 %d" % code)
            self._report_fault("鼠标钩子挂载失败（错误码 %d）" % code)
            return
        self._kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc_ref, None, 0)
        self.log("鼠标钩子已挂载，键盘钩子%s" % ("已挂载" if self._kb_hook else "挂载失败"))
        if not self._kb_hook:
            self._report_fault("键盘钩子挂载失败（Esc 收起和热键会失效）")

        for index, (_mods, _vk, name) in enumerate(self.hotkeys, start=1):
            mods, vk, _ = self.hotkeys[index - 1]
            if not user32.RegisterHotKey(None, 100 + index, mods, vk):
                # 热键冲突很常见（别的程序占了同样的组合）, 取词本身还能用,
                # 所以这里只记日志, 不亮故障灯。
                self.log("热键注册失败: %s" % name)

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and self.on_hotkey:
                slot = msg.wParam - 100
                if 1 <= slot <= len(self.hotkeys):
                    try:
                        self.on_hotkey(self.hotkeys[slot - 1][2])
                    except Exception as exc:
                        self.log("hotkey error: %s" % exc)

        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        if self._kb_hook:
            user32.UnhookWindowsHookEx(self._kb_hook)
            self._kb_hook = None

    def stop(self):
        self._stop.set()
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
