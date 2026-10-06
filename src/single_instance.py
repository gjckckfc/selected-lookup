# -*- coding: utf-8 -*-
"""单实例锁: 保证同一时间只有一个自己在跑。

为什么需要: 以后要加"开机自启"。开机时已经自动跑了一个, 用户再到桌面双击
一次就会起来第二个 —— 两个托盘图标、两套鼠标钩子, 选一次词弹两个浮窗,
两个还往同一个生词本里写。所以在加自启之前必须先把这个堵住。

做法（纯 ctypes, 不引入第三方库）:
  - CreateMutexW 建一个**带名字**的系统互斥体。第一次建是新建, 第二次建同一个
    名字时系统会返回 ERROR_ALREADY_EXISTS, 说明已经有一个在跑了。
  - 已经有一个在跑时, 用 FindWindowW 找到它的托盘窗口, 用 PostMessageW 丢一个
    "把设置窗口打开"的消息过去。这样用户双击快捷方式看到的是设置窗口, 而不是
    "双击了没反应"。

互斥体用默认的 Local 命名空间(每个登录会话一个), 同一台机器不同用户各开各的。
进程一退出内核自动释放, 不会留下要清理的残骸 —— 这也是不用"锁文件"的原因:
文件锁在程序崩溃后会留下脏文件, 还得额外处理。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

ERROR_ALREADY_EXISTS = 183

kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM]

MUTEX_NAME = "LookupPlugin_SingleInstance"

# 句柄要一直拿着: 一旦被回收, 互斥体可能提前释放, 锁就形同虚设
_handle = None


def acquire(name=MUTEX_NAME):
    """抢锁。返回 True = 可以继续跑; False = 已经有一个在跑了。"""
    global _handle
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        # 极罕见: 连互斥体都建不出来。宁可放行, 也别因为锁的问题打不开程序。
        return True
    _handle = handle
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def notify_existing(window_class, message, payload, timeout=2.0):
    """请已经在跑的那个把设置窗口打开。返回有没有送到。"""
    deadline = time.monotonic() + timeout
    while True:
        hwnd = user32.FindWindowW(window_class, None)
        if hwnd:
            user32.PostMessageW(hwnd, message, 0, payload)
            return True
        # 对方可能还在启动(托盘窗口还没建好), 稍等一下再看
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.15)
