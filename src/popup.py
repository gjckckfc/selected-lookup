# -*- coding: utf-8 -*-
"""贴边浮窗: 显示查词结果, 可以拖动, 可以一键复制。

外观:
  - 圆角: CreateRoundRectRgn + SetWindowRgn
  - 半透明: WS_EX_LAYERED + SetLayeredWindowAttributes, 默认 88%
  - 鼠标移上去自动变完全不透明, 移开恢复

交互:
  - WS_EX_NOACTIVATE 保证不抢焦点, 不影响你正在打字的窗口
  - 可以按住拖走; 拖动期间由 capture.py 的忽略区域让全局钩子不插手
  - 悬停时不自动收起
"""
from __future__ import annotations

import ctypes
import tkinter as tk

from capture import write_clipboard_text

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

BUTTON_BG = "#2c3648"
BUTTON_FG = "#c9d6ea"
BUTTON_ACTIVE = "#3b4a63"

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
    def __init__(self, master, hide_after=5.0, radius=14, opacity=88,
                 hover_opaque=True, on_geometry=None):
        self.master = master
        self.hide_after = hide_after
        self.radius = radius
        self.opacity = max(40, min(100, opacity))
        self.hover_opaque = hover_opaque
        self.on_geometry = on_geometry

        self._timer = None
        self._hover_timer = None
        self._hovering = False
        self._hwnd = None
        self._drag_offset = None
        self._clipboard_text = ""
        self._copy_btn = None
        self._copy_timer = None

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
    # 拖动
    # ------------------------------------------------------------------

    def _bind_drag(self, widget):
        widget.bind("<Button-1>", self._on_drag_start)
        widget.bind("<B1-Motion>", self._on_drag_move)
        for child in widget.winfo_children():
            if isinstance(child, tk.Button):
                continue
            self._bind_drag(child)

    def _on_drag_start(self, event):
        self._drag_offset = (event.x_root - self.win.winfo_x(),
                             event.y_root - self.win.winfo_y())

    def _on_drag_move(self, event):
        if not self._drag_offset:
            return
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        self.win.geometry("+%d+%d" % (x, y))
        if self.on_geometry:
            self.on_geometry()

    def rect(self):
        """当前窗口占据的屏幕矩形; 不可见时返回 None。"""
        if not self.win.winfo_viewable():
            return None
        left = self.win.winfo_rootx()
        top = self.win.winfo_rooty()
        return (left, top, left + self.win.winfo_width(), top + self.win.winfo_height())

    # ------------------------------------------------------------------
    # 内容渲染
    # ------------------------------------------------------------------

    def _clear(self):
        self._copy_btn = None
        for child in self.card.winfo_children():
            child.destroy()

    def _label(self, parent, text, fg, size=10, bold=False, pady=0, wraplength=None):
        label = tk.Label(
            parent,
            text=text,
            bg=CARD_BG,
            fg=fg,
            justify="left",
            anchor="w",
            wraplength=wraplength or (CARD_WIDTH - 32),
            font=(FONT_FAMILY, size, "bold" if bold else "normal"),
        )
        label.pack(fill="x", pady=pady)
        return label

    def _title_with_copy(self, title):
        header = tk.Frame(self.card, bg=CARD_BG)
        header.pack(fill="x")
        tk.Label(header, text=title, bg=CARD_BG, fg=TITLE_FG, justify="left",
                 anchor="nw", wraplength=CARD_WIDTH - 118,
                 font=(FONT_FAMILY, 12, "bold")).pack(side="left", anchor="nw")
        button = tk.Button(
            header, text="复制", command=self._copy,
            bg=BUTTON_BG, fg=BUTTON_FG, activebackground=BUTTON_ACTIVE,
            activeforeground=TITLE_FG, relief="flat", bd=0, highlightthickness=0,
            font=(FONT_FAMILY, 8), padx=9, pady=2, cursor="hand2",
        )
        button.pack(side="right", anchor="ne", padx=(10, 0))
        self._copy_btn = button

    def _copy(self):
        if not self._clipboard_text:
            return
        try:
            write_clipboard_text(self._clipboard_text)
        except Exception:
            return
        if self._copy_btn:
            self._copy_btn.configure(text="已复制")
            if self._copy_timer:
                self.master.after_cancel(self._copy_timer)
            self._copy_timer = self.master.after(1400, self._reset_copy_label)

    def _reset_copy_label(self):
        self._copy_timer = None
        if self._copy_btn and self._copy_btn.winfo_exists():
            self._copy_btn.configure(text="复制")

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
        self._clipboard_text = ""

        if result.kind == "miss":
            self._label(self.card, result.query, TITLE_FG, size=12, bold=True)
            self._label(self.card, "词典里没有这个词条", NOTE_FG, size=9, pady=(6, 0))
            self._bind_drag(self.card)
            return

        if result.kind in ("word", "phrase"):
            entry = result.entry
            head = entry.word
            if result.matched_form and result.matched_form.lower() != entry.word.lower():
                head = "%s  <-  %s" % (entry.word, result.matched_form)
            title = head
            if entry.phonetic:
                title += "   /%s/" % entry.phonetic.strip("/")
            self._title_with_copy(title)

            lines = ["%s  /%s/" % (entry.word, entry.phonetic.strip("/")) if entry.phonetic
                     else entry.word]

            marks = []
            if entry.tags:
                marks.append("、".join(entry.tags))
            if entry.collins:
                marks.append("柯林斯 %d 星" % entry.collins)
            if entry.oxford:
                marks.append("牛津核心")
            if marks:
                self._label(self.card, " · ".join(marks), TAG_FG, size=9, pady=(5, 0))
                lines.append(" · ".join(marks))

            body = (entry.translation or entry.definition)[:6]
            for index, line in enumerate(body):
                self._label(self.card, line, BODY_FG, size=10,
                            pady=(9 if index == 0 else 3, 0))
                lines.append(line)

            if entry.exchange:
                note = self._exchange_note(entry.exchange)
                self._label(self.card, note, NOTE_FG, size=8, pady=(9, 0))
                lines.append(note)

            self._clipboard_text = "\n".join(lines)
            self._bind_drag(self.card)
            return

        # breakdown: 整串没查到, 退回逐词
        self._title_with_copy(result.query)
        lines = [result.query, "（整串没有词条，逐词释义）"]
        self._label(self.card, "整串没有词条, 下面是逐词释义", NOTE_FG, size=9, pady=(5, 0))
        for entry, matched, token in result.parts:
            head = "%s -> %s" % (token, entry.word) if matched else token
            first = (entry.translation or entry.definition or ["—"])[0]
            self._label(self.card, head, PHONETIC_FG, size=10, bold=True, pady=(10, 0))
            self._label(self.card, first, BODY_FG, size=9, pady=(2, 0))
            lines.append("%s: %s" % (head, first))
        self._clipboard_text = "\n".join(lines)
        self._bind_drag(self.card)

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
        self._drag_offset = None

        self._restart_timer()
        self._schedule_hover_check()
        if self.on_geometry:
            self.on_geometry()

    def _restart_timer(self):
        if self._timer:
            self.master.after_cancel(self._timer)
        self._timer = self.master.after(int(self.hide_after * 1000), self.hide)

    def _schedule_hover_check(self):
        if self._hover_timer:
            self.master.after_cancel(self._hover_timer)
        self._hover_timer = self.master.after(150, self._poll_hover)

    def _poll_hover(self):
        """鼠标压到浮窗上就变实; 停在上面时不要自动收起。"""
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
        if inside:
            # 你正在看它的时候别把它收走
            self._restart_timer()
        self._schedule_hover_check()

    def hide(self):
        if self._timer:
            self.master.after_cancel(self._timer)
            self._timer = None
        if self._hover_timer:
            self.master.after_cancel(self._hover_timer)
            self._hover_timer = None
        if self._copy_timer:
            self.master.after_cancel(self._copy_timer)
            self._copy_timer = None
        self._hovering = False
        self._drag_offset = None
        self.win.withdraw()
        if self.on_geometry:
            self.on_geometry()
