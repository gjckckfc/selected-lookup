# -*- coding: utf-8 -*-
"""用户设置的读写。

设置存在项目根目录的 settings.json, 改完立即生效, 下次启动自动读回来。
"""
from __future__ import annotations

import json
from pathlib import Path

import wordrank

DEFAULTS = {
    "enabled": True,          # 启动时是否开启取词
    "drag_threshold": 6,      # 判定为拖选的像素阈值
    "hide_after": 5.0,        # 浮窗最长停留秒数, 取消选中会立刻收起
    # --- 浮窗内容 ---
    "popup_order": wordrank.DEFAULT_ORDER,  # 逐词释义的排序: hard 生词优先 / text 原文顺序 / easy 基础词优先
    # --- 生词本（本地 Markdown 沉淀，不联网）---
    "notebook_enabled": True,  # 选中即自动收录进 vocabulary/raw/
    # --- 朗读（用系统自带语音，不联网）---
    "speak_enabled": True,     # 右键朗读
    "speak_mode": "en",        # en = 只读英文; both = 中英都读
    "speak_voice": "",         # 英语用哪个声音; 空 = 自动挑
    "speak_rate": 0,           # 语速档位: -6 慢 ~ 0 正常 ~ +6 快
    "speak_prewarm": True,     # 选中就提前合成语音(界面不再暴露, 默认开)
    # --- 界面偏好 ---
    "ui_topmost": True,        # 设置窗口是否置顶
    # --- 整句翻译（走用户自己的 API 密钥）---
    "translate_enabled": False,
    "api_key": "",
    "model": "deepseek-flash",
}

# 字符串型设置, 不做数值夹取
STR_KEYS = {"api_key", "model", "speak_mode", "speak_voice", "popup_order"}

# 只能取固定几个值的字符串设置
CHOICES = {
    "speak_mode": ("en", "both"),
    "popup_order": wordrank.ORDERS,
}

# 每项的合法范围, 越界会被夹回来
RANGES = {
    "drag_threshold": (2, 40),
    "hide_after": (2.0, 60.0),
    "speak_rate": (-6, 6),
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
                elif key in STR_KEYS:
                    self.values[key] = self._str_value(key, raw[key])
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
        elif key in STR_KEYS:
            self.values[key] = self._str_value(key, value)
        else:
            self.values[key] = clamp(key, value)
        self.save()
        return self.values[key]

    @staticmethod
    def _str_value(key, value):
        text = str(value)
        allowed = CHOICES.get(key)
        if allowed and text not in allowed:
            return DEFAULTS[key]
        return text

    def reset(self):
        self.values = dict(DEFAULTS)
        self.save()
