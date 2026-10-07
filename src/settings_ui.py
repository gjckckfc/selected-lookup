# -*- coding: utf-8 -*-
"""设置窗口。

按"工具类界面"来做: 用系统原生控件, 不做模态弹窗, 改一下就立即生效。
窗口默认置顶, 方便一边看设置一边调。

只放"经常要调"的东西: AI 翻译、朗读。取词的判定阈值/停留时间不再暴露
(用系统默认 6px / 5 秒), 需要时直接改 settings.json; 开关取词在托盘右键菜单里。
"""
from __future__ import annotations

import ctypes
import os
import queue
import threading
import tkinter as tk
from ctypes import wintypes
from tkinter import ttk

FONT = ("Microsoft YaHei UI", 9)
TITLE_FONT = ("Microsoft YaHei UI", 11, "bold")
AUTO_VOICE = "自动（推荐）"
# 对齐用的字段标签(标签宽度按"中文算两格"折算, 取最长的那个 + 1)
FIELD_LABELS = ("朗读内容", "英语声音", "语速", "释义排序")


def _field_width():
    widest = 0
    for text in FIELD_LABELS:
        units = sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)
        widest = max(widest, units)
    return widest + 1


class SettingsWindow:
    def __init__(self, master, settings, on_change, on_reset=None):
        self.master = master
        self.settings = settings
        self.on_change = on_change
        self.on_reset = on_reset
        self.on_test_translate = None
        self.on_speech_info = None
        self.on_voice_list = None
        self.on_voice_missing = None
        self.win = None
        self._loading = False
        self._scales = {}
        self._pending_scale = {}
        self._scale_timer = None
        self._value_labels = {}
        self._checks = {}
        self._radios = {}
        self._entries = {}
        self._voice_combo = None
        self._voice_var = None
        self._top_var = None
        self._speak_hint = None
        self._speech_help = None
        self._field = _field_width()
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
        self.win.configure(padx=18, pady=14)

        style = ttk.Style(self.win)
        for theme in ("vista", "winnative", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure(".", font=FONT)
        style.configure("Title.TLabel", font=TITLE_FONT)
        style.configure("Hint.TLabel", foreground="#6b7280", font=(FONT[0], 8))
        style.configure("Group.TLabelframe.Label", font=(FONT[0], 9, "bold"))

        head = ttk.Frame(self.win)
        head.pack(fill="x", pady=(0, 10))
        ttk.Label(head, text="设置", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="改完立即生效，自动保存", style="Hint.TLabel").pack(
            side="left", padx=(10, 0), pady=(4, 0))
        top_var = tk.BooleanVar(value=bool(self.settings.get("ui_topmost")))
        ttk.Checkbutton(head, text="置顶", variable=top_var,
                        command=lambda v=top_var: self._set_topmost(v.get())
                        ).pack(side="right", pady=(4, 0))
        self._top_var = top_var

        # ---- 翻译 ----
        tr = ttk.LabelFrame(self.win, text="AI 翻译（DeepSeek）", padding=10,
                            style="Group.TLabelframe")
        tr.pack(fill="x")
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
        sp = ttk.LabelFrame(self.win, text="朗读（微软神经网络语音）", padding=10,
                            style="Group.TLabelframe")
        sp.pack(fill="x", pady=(12, 0))
        self._check(sp, "启用右键朗读（右键浮窗里的词或句子就念出来）", "speak_enabled")
        self._radio_row(sp, "speak_mode",
                        (("只读英文", "en"), ("中英都读", "both")), label="朗读内容")
        self._voice_row(sp)
        self._scale(sp, "语速", "speak_rate", -6, 6, 1, "",
                    None, fmt=self._rate_text)
        self._speak_hint = ttk.Label(sp, text="", style="Hint.TLabel",
                                     wraplength=330, justify="left")
        self._speak_hint.pack(anchor="w", pady=(6, 0))
        # 只有找不到英语语音时才需要这条"外援"路径
        self._speech_help = ttk.Button(sp, text="这台机器没有英语语音？去 Windows 里加一个",
                                       command=self._open_speech_settings)

        # ---- 浮窗内容 ----
        pc = ttk.LabelFrame(self.win, text="浮窗内容", padding=10,
                            style="Group.TLabelframe")
        pc.pack(fill="x", pady=(12, 0))
        self._radio_row(pc, "popup_order",
                        (("生词优先", "hard"), ("原文顺序", "text"), ("基础词优先", "easy")),
                        label="释义排序")
        ttk.Label(pc, text="整串查不到词条时，浮窗会把选中的文字拆成一个个词。"
                           "排序决定哪个词排在最上面；生词优先按词频、柯林斯星级和考纲标签估算难度。",
                  style="Hint.TLabel", wraplength=330, justify="left").pack(
                      anchor="w", pady=(6, 0))

        # ---- 底部按钮 ----
        footer = ttk.Frame(self.win)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Button(footer, text="恢复默认", command=self._reset).pack(side="left")
        ttk.Button(footer, text="关闭", command=self.win.withdraw).pack(side="right")

        self.refresh()
        self.win.update_idletasks()
        self._set_topmost(bool(self.settings.get("ui_topmost")))
        self._center()
        self.win.lift()
        self.win.focus_force()
        self._poll_queue()

    def _set_topmost(self, on):
        try:
            self.win.attributes("-topmost", bool(on))
        except tk.TclError:
            pass
        if self._top_var is not None and bool(self._top_var.get()) != bool(on):
            self._top_var.set(bool(on))
        if self._loading:
            return
        self.settings.set("ui_topmost", bool(on))

    def _center(self):
        width = self.win.winfo_reqwidth()
        height = self.win.winfo_reqheight()
        left, top, right, bottom = self._work_area()
        x = left + max(0, (right - left - width) // 2)
        y = top + max(0, (bottom - top - height) // 3)
        self.win.geometry("+%d+%d" % (x, y))

    def _work_area(self):
        """屏幕可用区域(去掉任务栏)。取不到就退回整屏。"""
        try:
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0,
                                                          ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except OSError:
            pass
        return 0, 0, self.win.winfo_screenwidth(), self.win.winfo_screenheight()

    # ------------------------------------------------------------------

    def _check(self, parent, text, key):
        var = tk.BooleanVar(value=bool(self.settings.get(key)))
        box = ttk.Checkbutton(parent, text=text, variable=var,
                              command=lambda: self._on_check(key, var))
        box.pack(anchor="w", pady=(0, 4))
        self._checks[key] = var

    def _scale(self, parent, text, key, low, high, step, unit, hint=None, fmt=None):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text=text, width=self._field, anchor="w").pack(side="left")
        value_label = ttk.Label(row, text="", width=8, anchor="e")
        value_label.pack(side="right")
        scale = ttk.Scale(row, from_=low, to=high, orient="horizontal",
                          command=lambda value: self._on_scale(key, value))
        scale.pack(side="left", fill="x", expand=True, padx=(4, 8))
        self._scales[key] = scale
        self._value_labels[key] = (value_label, step, unit, fmt)

        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel", wraplength=380,
                      justify="left").pack(anchor="w", pady=(1, 0))

    def _entry(self, parent, text, key, hint=None, secret=False):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text=text, width=8).pack(side="left")
        var = tk.StringVar(value=str(self.settings.get(key) or ""))
        entry = ttk.Entry(row, textvariable=var, show="*" if secret else "")
        entry.pack(side="left", fill="x", expand=True)
        # 边打边存会把磁盘写爆, 所以失焦或回车时才落盘
        entry.bind("<FocusOut>", lambda event, k=key, v=var: self._on_entry(k, v))
        entry.bind("<Return>", lambda event, k=key, v=var: self._on_entry(k, v))
        self._entries[key] = var
        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").pack(anchor="w", pady=(1, 0))
        return entry

    def _radio_row(self, parent, key, options, label=None):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(8, 0))
        if label:
            ttk.Label(row, text=label, width=self._field, anchor="w").pack(side="left")
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

    @staticmethod
    def _rate_text(value):
        value = int(value)
        if value == 0:
            return "正常"
        return ("慢 %d 档" % -value) if value < 0 else ("快 %d 档" % value)

    def _voice_row(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="英语声音", width=self._field, anchor="w").pack(side="left")
        var = tk.StringVar(value=AUTO_VOICE)
        combo = ttk.Combobox(row, textvariable=var, state="readonly", width=27)
        combo.pack(side="left", padx=(8, 0))
        combo.bind("<<ComboboxSelected>>", lambda event: self._on_voice(var.get()))
        self._voice_combo = combo
        self._voice_var = var

    def _on_voice(self, choice):
        if self._loading or not self._voice_var:
            return
        value = "" if choice == AUTO_VOICE else choice
        self.settings.set("speak_voice", value)
        self.on_change("speak_voice", value)
        if self._speak_hint is not None and self.on_speech_info:
            self._speak_hint.configure(text=self.on_speech_info())

    def _fill_voices(self):
        if self._voice_combo is None or self._voice_var is None:
            return
        names = list(self.on_voice_list()) if self.on_voice_list else []
        values = [AUTO_VOICE] + names
        self._voice_combo.configure(values=values)
        current = self.settings.get("speak_voice") or AUTO_VOICE
        self._voice_var.set(current if current in values else AUTO_VOICE)

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
        """拖动时只更新显示, 停手 0.4 秒才落盘——别每一步都写一次配置文件。"""
        if self._loading:
            return
        step = self._value_labels[key][1]
        value = round(float(raw) / step) * step
        self._pending_scale[key] = value
        self._show_value(key, value)
        if self._scale_timer:
            try:
                self.win.after_cancel(self._scale_timer)
            except Exception:
                pass
        self._scale_timer = self.win.after(400, lambda k=key: self._commit_scale(k))

    def _commit_scale(self, key):
        self._scale_timer = None
        value = self._pending_scale.pop(key, None)
        if value is None:
            return
        saved = self.settings.set(key, value)
        self.on_change(key, saved)

    def _show_value(self, key, value=None):
        label, step, unit, fmt = self._value_labels[key]
        if value is None:
            value = self.settings.get(key)
        if fmt:
            text = fmt(value)
        else:
            text = "%d%s" % (round(value), unit) if step >= 1 else "%.1f%s" % (value, unit)
        label.configure(text=text)

    def refresh(self):
        if self.win is None or not self.win.winfo_exists():
            return
        self._loading = True
        try:
            if self._scale_timer:
                try:
                    self.win.after_cancel(self._scale_timer)
                except Exception:
                    pass
                self._scale_timer = None
            self._pending_scale.clear()
            for key, var in self._checks.items():
                var.set(bool(self.settings.get(key)))
            for key, scale in self._scales.items():
                scale.set(self.settings.get(key))
                self._show_value(key)
            for key, var in self._radios.items():
                var.set(str(self.settings.get(key)))
            self._fill_voices()
            for key, var in self._entries.items():
                var.set(str(self.settings.get(key) or ""))
            if self._speak_hint is not None and self.on_speech_info:
                self._speak_hint.configure(text=self.on_speech_info())
            if self._speech_help is not None:
                missing = bool(self.on_voice_missing()) if self.on_voice_missing else False
                if missing:
                    self._speech_help.pack(anchor="w", pady=(6, 0))
                else:
                    self._speech_help.pack_forget()
        finally:
            self._loading = False

    def _reset(self):
        self.settings.reset()
        self.refresh()
        if self.on_reset:
            self.on_reset()
