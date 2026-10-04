# -*- coding: utf-8 -*-
"""设置窗口。

按"工具类界面"来做: 用系统原生控件, 不做模态弹窗, 改一下就立即生效。
分三个组——取词触发、浮窗外观、开关, 每组里控件紧凑, 组与组之间留白。
"""
from __future__ import annotations

import os
import queue
import threading
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
        self.on_test_translate = None
        self.on_speech_info = None
        self.win = None
        self._loading = False
        self._scales = {}
        self._value_labels = {}
        self._checks = {}
        self._radios = {}
        self._entries = {}
        self._test_queue = queue.Queue()
        self._testing = False

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

        # ---- 取词 ----
        group = ttk.LabelFrame(self.win, text="取词", padding=12, style="Group.TLabelframe")
        group.pack(fill="x")
        self._check(group, "启用取词（关闭后拖选什么都不弹）", "enabled")
        self._scale(group, "拖选判定阈值", "drag_threshold", 2, 40, 1, "px",
                    "只有拖动超过这个距离才认作选择，误弹就调大")
        self._scale(group, "最长停留时间", "hide_after", 2, 30, 1, "秒",
                    "取消选中会立刻收起；一直选着不动则超过这个时间收起")

        # ---- 翻译 ----
        tr = ttk.LabelFrame(self.win, text="整句翻译（DeepSeek）", padding=12,
                            style="Group.TLabelframe")
        tr.pack(fill="x", pady=(14, 0))
        self._check(tr, "启用整句翻译（选中句子时自动翻译）", "translate_enabled")
        self._entry(tr, "API 密钥", "api_key",
                    "在 platform.deepseek.com 申请；明文存在 settings.json 里", secret=True)
        self._entry(tr, "模型名", "model",
                    "建议用非推理模型（如 deepseek-flash），推理模型会多花思考 token")
        test_row = ttk.Frame(tr)
        test_row.pack(fill="x", pady=(10, 0))
        ttk.Button(test_row, text="保存", command=self._save).pack(side="left")
        ttk.Button(test_row, text="测试连接", command=self._test).pack(side="left", padx=(8, 0))
        self._test_label = ttk.Label(test_row, text="", style="Hint.TLabel",
                                     wraplength=210, justify="left")
        self._test_label.pack(side="left", padx=(10, 0))
        ttk.Label(tr, text="选中文字会发送给你填写的服务商；不上传其他任何内容。",
                  style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

        # ---- 朗读 ----
        sp = ttk.LabelFrame(self.win, text="朗读（用系统自带语音，不联网）", padding=12,
                            style="Group.TLabelframe")
        sp.pack(fill="x", pady=(14, 0))
        self._check(sp, "启用右键朗读（右键浮窗里的词或句子就念出来）", "speak_enabled")
        self._radio_row(sp, "speak_mode",
                        (("只读英文", "en"), ("中英都读", "both")))
        self._speak_hint = ttk.Label(sp, text="", style="Hint.TLabel",
                                     wraplength=300, justify="left")
        self._speak_hint.pack(anchor="w", pady=(6, 0))
        ttk.Button(sp, text="打开 Windows 语音设置",
                   command=self._open_speech_settings).pack(anchor="w", pady=(6, 0))

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
        self._poll_queue()

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

    def _entry(self, parent, text, key, hint=None, secret=False):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text=text, width=8).pack(side="left")
        var = tk.StringVar(value=str(self.settings.get(key) or ""))
        entry = ttk.Entry(row, textvariable=var, show="*" if secret else "")
        entry.pack(side="left", fill="x", expand=True)
        # 边打边存会把磁盘写爆, 所以失焦或回车时才落盘
        entry.bind("<FocusOut>", lambda event, k=key, v=var: self._on_entry(k, v))
        entry.bind("<Return>", lambda event, k=key, v=var: self._on_entry(k, v))
        self._entries[key] = var
        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").pack(anchor="w", pady=(2, 0))
        return entry

    def _radio_row(self, parent, key, options):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(8, 0))
        var = tk.StringVar(value=str(self.settings.get(key)))
        for text, value in options:
            ttk.Radiobutton(row, text=text, value=value, variable=var,
                            command=lambda v=var, k=key: self._on_radio(k, v)
                            ).pack(side="left", padx=(0, 14))
        self._radios[key] = var
        return var

    def _on_radio(self, key, var):
        if self._loading:
            return
        self.settings.set(key, var.get())
        self.on_change(key, self.settings.get(key))

    def _open_speech_settings(self):
        """跳到 Windows 的语音设置页, 让用户自己装英语语音。"""
        try:
            os.startfile("ms-settings:speech")
        except OSError:
            pass

    def _on_entry(self, key, var):
        if self._loading:
            return
        value = var.get().strip()
        if value == (self.settings.get(key) or ""):
            return
        self.settings.set(key, value)
        self.on_change(key, value)

    def _save_entries(self):
        """把输入框里的当前值写进设置, 返回有改动的键。"""
        changed = []
        for key, var in self._entries.items():
            value = var.get().strip()
            if value != (self.settings.get(key) or ""):
                self.settings.set(key, value)
                self.on_change(key, value)
                changed.append(key)
        return changed

    def _save(self):
        changed = self._save_entries()
        self._test_label.configure(text="已保存" if changed else "已保存（没有改动）")

    def _test(self):
        if self._testing or self.on_test_translate is None:
            return
        # 先落盘, 否则测试读到的还是没保存的旧值
        self._save_entries()
        self._testing = True
        self._test_label.configure(text="测试中…")

        def work():
            try:
                ok, message = self.on_test_translate()
            except Exception as exc:
                ok, message = False, str(exc)
            self._test_queue.put((ok, message))

        threading.Thread(target=work, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                ok, message = self._test_queue.get_nowait()
                self._testing = False
                self._test_label.configure(text=("成功 " if ok else "失败 ") + message)
        except queue.Empty:
            pass
        if self.win is not None:
            try:
                if self.win.winfo_exists():
                    self.win.after(150, self._poll_queue)
            except tk.TclError:
                pass

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
            for key, var in self._radios.items():
                var.set(str(self.settings.get(key)))
            for key, var in self._entries.items():
                var.set(str(self.settings.get(key) or ""))
            if self._speak_hint is not None and self.on_speech_info:
                self._speak_hint.configure(text=self.on_speech_info())
        finally:
            self._loading = False

    def _reset(self):
        self.settings.reset()
        self.refresh()
        if self.on_reset:
            self.on_reset()
