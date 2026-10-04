# -*- coding: utf-8 -*-
"""调试用: 读默认声卡当前的输出峰值, 用来判断"到底还有没有声音在放"。

背景: MCI 的播放设备属于"打开它的那个线程", 跨线程 stop 是停不掉的,
只看日志会以为停掉了, 只有量声卡才知道真相。

用法:
    python scripts/audio_probe.py            # 每 0.2 秒打一行峰值
    python scripts/audio_probe.py --seconds 10

峰值说明: 0.000 就是没声音; 测试用的 300Hz/20% 音量大约读到 0.36。
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import POINTER, byref, c_float, c_int, c_uint, c_void_p

ole32 = ctypes.windll.ole32


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text):
    value = GUID()
    ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(value))
    return value


def _call(pointer, index, restype, *argtypes):
    """按 vtable 下标调 COM 方法。"""
    methods = ctypes.cast(pointer, POINTER(POINTER(c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    return prototype(methods[index])


CLSID_MM_DEVICE_ENUMERATOR = _guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMM_DEVICE_ENUMERATOR = _guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAUDIO_METER_INFORMATION = _guid("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")


class Meter:
    """默认播放设备(扬声器)的实时峰值。"""

    def __init__(self):
        ole32.CoInitializeEx(None, 0)
        enumerator = c_void_p()
        ole32.CoCreateInstance(byref(CLSID_MM_DEVICE_ENUMERATOR), None, 1,
                               byref(IID_IMM_DEVICE_ENUMERATOR),
                               byref(enumerator))
        device = c_void_p()
        _call(enumerator, 4, ctypes.c_long, c_int, c_int,
              POINTER(c_void_p))(enumerator, 0, 0, byref(device))
        self._meter = c_void_p()
        _call(device, 3, ctypes.c_long, POINTER(GUID), c_uint, c_void_p,
              POINTER(c_void_p))(device, byref(IID_IAUDIO_METER_INFORMATION), 1,
                                 None, byref(self._meter))

    def peak(self):
        value = c_float(0.0)
        _call(self._meter, 3, ctypes.c_long,
              POINTER(c_float))(self._meter, byref(value))
        return value.value


def main(argv=None):
    parser = argparse.ArgumentParser(description="默认声卡输出峰值探针")
    parser.add_argument("--seconds", type=float, default=30.0,
                        help="采样多久(秒), 默认 30")
    parser.add_argument("--interval", type=float, default=0.2,
                        help="采样间隔(秒), 默认 0.2")
    args = parser.parse_args(argv)
    try:
        meter = Meter()
    except OSError as exc:
        print("读不到声卡峰值: %s" % exc)
        return 1
    start = time.perf_counter()
    print("时间     峰值    状态")
    while time.perf_counter() - start < args.seconds:
        value = meter.peak()
        print("%5.1fs  %.3f   %s" % (
            time.perf_counter() - start, value,
            "有声音" if value > 0.005 else "静音"))
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
