# -*- coding: utf-8 -*-
"""贴边浮窗: 显示查词结果。

外观上做了三件事:
  - 圆角: CreateRoundRectRgn + SetWindowRgn 把矩形窗口裁成圆角
  - 半透明: WS_EX_LAYERED + SetLayeredWindowAttributes, 默认 88%
  - 鼠标移上去自动变完全不透明, 移开恢复, 兼顾"不挡阅读"和"看得清"

还有两个关键点:
  - WS_EX_NOACTIVATE 让窗口不抢焦点, 否则一弹出来你正在打字的窗口就失焦了
  - 位置贴着鼠标松开的地方, 并避开屏幕边界
"""
from __future__ import annotations

import ctypes
import tkinter as tk

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002

# 配色: 深色底 + 高对比文字。正文与底色的对比度都在 4.5:1 以上。
CARD_BG = "#1e2430"
BORDER = "#33405a"
TITLE_FG = "#eef4ff"
PHONETIC_FG = "#8fc0ee"
TAG_FG = "#ffcf6b"
BODY_FG = "#e3eaf4"
NOTE_FG = "#96a2b5"

FONT_FAMILY = "Microsoft YaHei UI"
CARD_WIDTH = 430

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# 64 位下必须声明参数类型, 否则句柄会被当成 32 位整数截断
user32.GetParent.restype = ctypes.c_void_p
user32.GetParent.argtypes = [ctypes.c_void_p]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
user32.SetWindowRgn.restype = ctypes.c_int
user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
user32.SetLayeredWindowAttributes.restype = ctypes.c_int
user32.SetLayeredWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                              ctypes.c_ubyte, ctypes.c_uint32]
gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6


class Popup:
    def __init__(self, master, hide_after=9.0, radius=14, opacity=88,
                 hover_opaque=True):
        self.master = master
        self.hide_after = hide_after
        self.radius = radius
        self.opacity = max(40, min(100, opacity))
        self.hover_opaque = hover_opaque
        self._timer = None
        self._hover_timer = None
        self._hovering = False
        self._hwnd = None

        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BORDER)

        self.card = tk.Frame(self.win, bg=CARD_BG, padx=15, pady=12)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)

        self.win.update_idletasks()
        self._hwnd = user32.GetParent(self.win.winfo_id())
        self._apply_styles()

    # ------------------------------------------------------------------
    # Windows 层面的外观
    # ------------------------------------------------------------------

    def _apply_styles(self):
        if not self._hwnd:
            return
        style = user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
        style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_LAYERED
        user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, style)

    def _apply_alpha(self, percent):
        if not self._hwnd:
            return
        alpha = int(max(0, min(100, percent)) * 255 / 100)
        user32.SetLayeredWindowAttributes(self._hwnd, 0, alpha, LWA_ALPHA)

    def _apply_round_region(self, width, height):
        """把窗口裁成圆角。半径 0 时恢复成矩形。"""
        if not self._hwnd:
            return
        if self.radius <= 0:
            user32.SetWindowRgn(self._hwnd, None, True)
            return
        diameter = self.radius * 2
        region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, diameter, diameter)
        if region:
            # SetWindowRgn 会接管这块 region 的所有权, 不需要我们释放
            user32.SetWindowRgn(self._hwnd, region, True)

    def apply_settings(self, radius=None, opacity=None, hide_after=None,
                       hover_opaque=None):
        """设置面板改了值以后即时生效。"""
        if radius is not None:
            self.radius = radius
        if opacity is not None:
            self.opacity = max(40, min(100, opacity))
        if hide_after is not None:
            self.hide_after = hide_after
        if hover_opaque is not None:
            self.hover_opaque = hover_opaque
        self._hovering = False
        if not self._hwnd:
            return
        self.win.update_idletasks()
        self._apply_alpha(self.opacity)
        width = self.win.winfo_width() or self.win.winfo_reqwidth()
        height = self.win.winfo_height() or self.win.winfo_reqheight()
        self._apply_round_region(width, height)

    # ------------------------------------------------------------------
    # 内容渲染
    # ------------------------------------------------------------------

    def _clear(self):
        for child in self.card.winfo_children():
            child.destroy()

    def _label(self, text, fg, size=10, bold=False, pady=0):
        label = tk.Label(
            self.card,
            text=text,
            bg=CARD_BG,
            fg=fg,
            justify="left",
            anchor="w",
            wraplength=CARD_WIDTH - 32,
            font=(FONT_FAMILY, size, "bold" if bold else "normal"),
        )
        label.pack(fill="x", pady=pady)
        return label

    @staticmethod
    def _exchange_note(exchange):
        names = {
            "p": "过去式", "d": "过去分词", "i": "现在分词",
            "3": "三单", "r": "比较级", "t": "最高级", "s": "复数",
        }
        bits = []
        for part in exchange.split("/"):
            code, _, value = part.partition(":")
            if code in names and value:
                bits.append("%s %s" % (names[code], value))
        return "  ".join(bits[:4])

    def _render(self, result):
        self._clear()
        if result.kind == "miss":
            self._label(result.query, TITLE_FG, size=12, bold=True)
            self._label("词典里没有这个词条", NOTE_FG, size=9, pady=(6, 0))
            return

        if result.kind in ("word", "phrase"):
            entry = result.entry
            head = entry.word
            if result.matched_form and result.matched_form.lower() != entry.word.lower():
                head = "%s  <-  %s" % (entry.word, result.matched_form)
            title = head
            if entry.phonetic:
                title += "   /%s/" % entry.phonetic.strip("/")
            self._label(title, TITLE_FG, size=12, bold=True)

            marks = []
            if entry.tags:
                marks.append("、".join(entry.tags))
            if entry.collins:
                marks.append("柯林斯 %d 星" % entry.collins)
            if entry.oxford:
                marks.append("牛津核心")
            if marks:
                self._label(" · ".join(marks), TAG_FG, size=9, pady=(5, 0))

            # 释义块与标题之间留更多空间, 形成明显的段落层次
            for index, line in enumerate((entry.translation or entry.definition)[:6]):
                self._label(line, BODY_FG, size=10, pady=(9 if index == 0 else 3, 0))

            if entry.exchange:
                self._label(self._exchange_note(entry.exchange), NOTE_FG, size=8, pady=(9, 0))
            return

        self._label(result.query, TITLE_FG, size=12, bold=True)
        self._label("整串没有词条, 下面是逐词释义", NOTE_FG, size=9, pady=(5, 0))
        for entry, matched, token in result.parts:
            head = token
            if matched:
                head = "%s -> %s" % (token, entry.word)
            first = (entry.translation or entry.definition or ["—"])[0]
            self._label(head, PHONETIC_FG, size=10, bold=True, pady=(10, 0))
            self._label(first, BODY_FG, size=9, pady=(2, 0))

    # ------------------------------------------------------------------
    # 显示与隐藏
    # ------------------------------------------------------------------

    def show(self, result, x, y):
        self._render(result)
        self.win.update_idletasks()

        width = self.win.winfo_reqwidth()
        height = self.win.winfo_reqheight()
        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()

        # 贴着鼠标右下方, 避开 Edge 选中后冒出来的小工具条
        pos_x = x + 14
        pos_y = y + 18
        if pos_x + width > screen_w - 8:
            pos_x = max(8, screen_w - width - 8)
        if pos_y + height > screen_h - 8:
            pos_y = max(8, y - height - 12)

        self.win.geometry("%dx%d+%d+%d" % (width, height, pos_x, pos_y))
        self.win.deiconify()
        self.win.lift()
        self._apply_styles()
        self._apply_round_region(width, height)
        self._hovering = False
        self._apply_alpha(self.opacity)

        if self._timer:
            self.master.after_cancel(self._timer)
        self._timer = self.master.after(int(self.hide_after * 1000), self.hide)
        self._schedule_hover_check()

    def _schedule_hover_check(self):
        if self._hover_timer:
            self.master.after_cancel(self._hover_timer)
        self._hover_timer = self.master.after(150, self._poll_hover)

    def _poll_hover(self):
        """鼠标压到浮窗上就变实, 移开恢复半透明。"""
        self._hover_timer = None
        if not self.win.winfo_viewable():
            return
        pointer_x, pointer_y = self.win.winfo_pointerxy()
        left = self.win.winfo_rootx()
        top = self.win.winfo_rooty()
        inside = (left <= pointer_x <= left + self.win.winfo_width()
                  and top <= pointer_y <= top + self.win.winfo_height())
        if inside != self._hovering:
            self._hovering = inside
            if self.hover_opaque:
                self._apply_alpha(100 if inside else self.opacity)
        self._schedule_hover_check()

    def hide(self):
        if self._timer:
            self.master.after_cancel(self._timer)
            self._timer = None
        if self._hover_timer:
            self.master.after_cancel(self._hover_timer)
            self._hover_timer = None
        self._hovering = False
        self.win.withdraw()
