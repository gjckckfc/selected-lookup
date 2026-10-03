# -*- coding: utf-8 -*-
"""设置窗口。

按"工具类界面"来做: 用系统原生控件, 不做模态弹窗, 改一下就立即生效。
分三个组——取词触发、浮窗外观、开关, 每组里控件紧凑, 组与组之间留白。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

FONT = ("Microsoft YaHei UI", 9)
TITLE_FONT = ("Microsoft YaHei UI", 11, "bold")


class SettingsWindow:
    def __init__(self, master, settings, on_change, on_reset=None):
        self.master = master
        self.settings = settings
        self.on_change = on_change
        self.on_reset = on_reset
        self.win = None
        self._loading = False
        self._scales = {}
        self._value_labels = {}
        self._checks = {}

    # ------------------------------------------------------------------

    def open(self):
        if self.win is not None and self.win.winfo_exists():
            self.refresh()
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            return

        self._build()

    def _build(self):
        self.win = tk.Toplevel(self.master)
        self.win.title("设置 · 选中即查")
        self.win.resizable(False, False)
        self.win.configure(padx=18, pady=16)

        style = ttk.Style(self.win)
        for theme in ("vista", "winnative", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure(".", font=FONT)
        style.configure("Title.TLabel", font=TITLE_FONT)
        style.configure("Hint.TLabel", foreground="#6b7280", font=(FONT[0], 8))
        style.configure("Group.TLabelframe.Label", font=(FONT[0], 9, "bold"))

        ttk.Label(self.win, text="设置", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.win, text="改完立即生效，自动保存", style="Hint.TLabel").pack(
            anchor="w", pady=(2, 12))

        # ---- 取词触发 ----
        trigger = ttk.LabelFrame(self.win, text="取词触发", padding=12, style="Group.TLabelframe")
        trigger.pack(fill="x")
        self._check(trigger, "启用取词（关闭后拖选什么都不弹）", "enabled")
        self._scale(trigger, "拖选判定阈值", "drag_threshold", 2, 40, 1, "px",
                    "只有拖动超过这个距离才认作选择，误弹就调大")

        # ---- 浮窗外观 ----
        look = ttk.LabelFrame(self.win, text="浮窗外观", padding=12, style="Group.TLabelframe")
        look.pack(fill="x", pady=(14, 0))
        self._scale(look, "最长停留时间", "hide_after", 2, 30, 1, "秒",
                    "取消选中会立刻收起；一直选着不动则超过这个时间收起")
        self._scale(look, "圆角半径", "corner_radius", 0, 28, 1, "px",
                    "0 = 直角，建议 12–16")
        self._scale(look, "不透明度", "opacity", 40, 100, 1, "%",
                    "数值越大越不透明")
        self._check(look, "鼠标移到浮窗上时变清晰", "hover_opaque")

        # ---- 底部按钮 ----
        footer = ttk.Frame(self.win)
        footer.pack(fill="x", pady=(16, 0))
        ttk.Button(footer, text="恢复默认", command=self._reset).pack(side="left")
        ttk.Button(footer, text="关闭", command=self.win.withdraw).pack(side="right")

        self.refresh()
        self.win.update_idletasks()
        self._center()
        self.win.lift()
        self.win.focus_force()

    def _center(self):
        width = self.win.winfo_reqwidth()
        height = self.win.winfo_reqheight()
        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 3
        self.win.geometry("+%d+%d" % (x, y))

    # ------------------------------------------------------------------

    def _check(self, parent, text, key):
        var = tk.BooleanVar(value=bool(self.settings.get(key)))
        box = ttk.Checkbutton(parent, text=text, variable=var,
                              command=lambda: self._on_check(key, var))
        box.pack(anchor="w", pady=(0, 6))
        self._checks[key] = var

    def _scale(self, parent, text, key, low, high, step, unit, hint=None):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text=text).pack(side="left")
        value_label = ttk.Label(row, text="", width=8, anchor="e")
        value_label.pack(side="right")

        scale = ttk.Scale(parent, from_=low, to=high, orient="horizontal")
        scale.pack(fill="x", pady=(3, 0))
        scale.configure(command=lambda value: self._on_scale(key, value))
        self._scales[key] = scale
        self._value_labels[key] = (value_label, step, unit)

        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").pack(anchor="w", pady=(2, 0))

    # ------------------------------------------------------------------

    def _on_check(self, key, var):
        if self._loading:
            return
        self.settings.set(key, var.get())
        self.on_change(key, self.settings.get(key))

    def _on_scale(self, key, raw):
        if self._loading:
            return
        step = self._value_labels[key][1]
        value = round(float(raw) / step) * step
        self.settings.set(key, value)
        self._show_value(key)
        self.on_change(key, self.settings.get(key))

    def _show_value(self, key):
        label, step, unit = self._value_labels[key]
        value = self.settings.get(key)
        text = "%d%s" % (round(value), unit) if step >= 1 else "%.1f%s" % (value, unit)
        label.configure(text=text)

    def refresh(self):
        if self.win is None or not self.win.winfo_exists():
            return
        self._loading = True
        try:
            for key, var in self._checks.items():
                var.set(bool(self.settings.get(key)))
            for key, scale in self._scales.items():
                scale.set(self.settings.get(key))
                self._show_value(key)
        finally:
            self._loading = False

    def _reset(self):
        self.settings.reset()
        self.refresh()
        if self.on_reset:
            self.on_reset()
