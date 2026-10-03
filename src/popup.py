# -*- coding: utf-8 -*-
"""贴边浮窗: 显示查词结果。

两个关键点:
  - 用 WS_EX_NOACTIVATE 让窗口不抢焦点, 否则一弹出来你正在打字的窗口就失焦了。
  - 位置贴着鼠标松开的地方, 并避开屏幕边界。
"""
from __future__ import annotations

import ctypes
import tkinter as tk

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

CARD_BG = "#1e2430"
BORDER = "#3a465c"
TITLE_FG = "#eaf2ff"
PHONETIC_FG = "#7fb2e5"
TAG_FG = "#ffcf6b"
BODY_FG = "#dfe6f0"
NOTE_FG = "#8b98ab"

FONT_FAMILY = "Microsoft YaHei UI"
CARD_WIDTH = 430

user32 = ctypes.windll.user32


class Popup:
    def __init__(self, master, hide_after=9.0):
        self.master = master
        self.hide_after = hide_after
        self._timer = None

        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BORDER)

        self.card = tk.Frame(self.win, bg=CARD_BG, padx=14, pady=11)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)

        self.win.update_idletasks()
        self._make_no_activate()

    def _make_no_activate(self):
        hwnd = user32.GetParent(self.win.winfo_id())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)

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
            wraplength=CARD_WIDTH - 30,
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
            self._label("词典里没有这个词条", NOTE_FG, size=9, pady=(4, 0))
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
                self._label(" · ".join(marks), TAG_FG, size=9, pady=(3, 0))

            for line in (entry.translation or entry.definition)[:6]:
                self._label(line, BODY_FG, size=10, pady=(3, 0))

            if entry.exchange:
                self._label(self._exchange_note(entry.exchange), NOTE_FG, size=8, pady=(6, 0))
            return

        self._label(result.query, TITLE_FG, size=12, bold=True)
        self._label("整串没有词条, 下面是逐词释义", NOTE_FG, size=9, pady=(3, 0))
        for entry, matched, token in result.parts:
            head = token
            if matched:
                head = "%s -> %s" % (token, entry.word)
            first = (entry.translation or entry.definition or ["—"])[0]
            self._label(head, PHONETIC_FG, size=10, bold=True, pady=(6, 0))
            self._label(first, BODY_FG, size=9, pady=(1, 0))

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
        self._make_no_activate()

        if self._timer:
            self.master.after_cancel(self._timer)
        self._timer = self.master.after(int(self.hide_after * 1000), self.hide)

    def hide(self):
        if self._timer:
            self.master.after_cancel(self._timer)
            self._timer = None
        self.win.withdraw()
