# -*- coding: utf-8 -*-
"""用户设置的读写。

设置存在项目根目录的 settings.json, 改完立即生效, 下次启动自动读回来。
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "enabled": True,          # 启动时是否开启取词
    "drag_threshold": 6,      # 判定为拖选的像素阈值
    "hide_after": 5.0,        # 浮窗最长停留秒数, 取消选中会立刻收起
    "corner_radius": 14,      # 浮窗圆角半径 (px)
    "opacity": 88,            # 浮窗不透明度 (%), 100 = 完全不透明
    "hover_opaque": True,     # 鼠标移到浮窗上时变完全不透明
    "popup_width": 300,       # 浮窗宽度 (px), 固定值
    "max_height": 380,        # 浮窗最大高度 (px), 超出用滚轮看
}

# 每项的合法范围, 越界会被夹回来
RANGES = {
    "drag_threshold": (2, 40),
    "hide_after": (2.0, 60.0),
    "corner_radius": (0, 28),
    "opacity": (40, 100),
    "max_height": (160, 1000),
    "popup_width": (220, 560),
}


def clamp(key, value):
    low, high = RANGES.get(key, (None, None))
    if low is None:
        return value
    try:
        value = type(DEFAULTS[key])(value)
    except (TypeError, ValueError):
        value = DEFAULTS[key]
    return max(low, min(high, value))


class Settings:
    def __init__(self, path):
        self.path = Path(path)
        self.values = dict(DEFAULTS)
        self.load()

    def load(self):
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for key in DEFAULTS:
            if key in raw:
                if isinstance(DEFAULTS[key], bool):
                    self.values[key] = bool(raw[key])
                else:
                    self.values[key] = clamp(key, raw[key])

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(self.values, ensure_ascii=False, indent=2)
            self.path.write_text(text + "\n", encoding="utf-8")
        except OSError:
            pass

    def get(self, key):
        return self.values.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        if key in DEFAULTS and isinstance(DEFAULTS[key], bool):
            self.values[key] = bool(value)
        else:
            self.values[key] = clamp(key, value)
        self.save()
        return self.values[key]

    def reset(self):
        self.values = dict(DEFAULTS)
        self.save()
