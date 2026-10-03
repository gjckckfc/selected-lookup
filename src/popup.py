# -*- coding: utf-8 -*-
"""贴边浮窗: 显示查词结果。

外观:
  - 圆角: CreateRoundRectRgn + SetWindowRgn
  - 半透明: WS_EX_LAYERED + SetLayeredWindowAttributes, 默认 88%
  - 鼠标移上去变完全不透明, 移开恢复; 停在上面时不自动收起

布局:
  - 顶部标题区固定不动(词头或原文 + 复制全部按钮)
  - 下面是内容区, 内容过多时限制最大高度并支持滚轮滚动
  - 原文用小字号, 超过两行自动收起, 点「展开全文」看全部

交互:
  - WS_EX_NOACTIVATE 不抢焦点
  - 每个"单词块"(词 + 释义)鼠标移上去整块高亮, 点一下复制这一块
  - 按住任意位置拖动浮窗; 拖动与点击靠位移区分
"""
from __future__ import annotations

import ctypes
import tkinter as tk
import tkinter.font as tkfont

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
LINK_FG = "#7fb2e5"

BLOCK_HOVER = "#2b374b"
BLOCK_COPIED = "#2c4a3c"

BUTTON_BG = "#2c3648"
BUTTON_FG = "#c9d6ea"
BUTTON_ACTIVE = "#3b4a63"

FONT_FAMILY = "Microsoft YaHei UI"
CARD_WIDTH = 420
DRAG_SLOP = 4            # 松开时位移小于这个值算"点击", 否则算"拖动"
MAX_DEF_LINES = 3        # 每个单词块最多显示几行释义
MAX_ORIGIN_LINES = 2     # 原文最多显示几行, 超出收起
SCROLL_STEP = 26         # 滚轮一格滚多少像素

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
                 hover_opaque=True, max_height=460, on_geometry=None):
        self.master = master
        self.hide_after = hide_after
        self.radius = radius
        self.opacity = max(40, min(100, opacity))
        self.hover_opaque = hover_opaque
        self.max_height = max_height
        self.on_geometry = on_geometry

        self._timer = None
        self._hover_timer = None
        self._hovering = False
        self._hwnd = None
        self._drag_offset = None
        self._press = None
        self._moved = False
        self._hover_block = None
        self._leave_timer = None
        self._flash_timer = None
        self._clipboard_text = ""
        self._copy_btn = None
        self._copy_timer = None
        self._scrollable = False
        self._origin_full = ""
        self._origin_expanded = False

        self._small_font = tkfont.Font(family=FONT_FAMILY, size=9)

        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BORDER)

        self.card = tk.Frame(self.win, bg=CARD_BG, padx=15, pady=12)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)

        # 标题区固定, 不跟着滚动
        self.header_frame = tk.Frame(self.card, bg=CARD_BG)
        self.header_frame.pack(fill="x")

        # 内容区: Canvas + 内嵌 Frame, 内容超出时才能滚动
        self.canvas = tk.Canvas(self.card, bg=CARD_BG, highlightthickness=0,
                                bd=0, width=CARD_WIDTH, height=10,
                                yscrollincrement=SCROLL_STEP)
        self.canvas.pack(fill="x", pady=(0, 0))
        self.inner = tk.Frame(self.canvas, bg=CARD_BG)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.inner,
                                                       anchor="nw", width=CARD_WIDTH)
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.win.bind("<MouseWheel>", self._on_wheel)

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
                       hover_opaque=None, max_height=None):
        if radius is not None:
            self.radius = radius
        if opacity is not None:
            self.opacity = max(40, min(100, opacity))
        if hide_after is not None:
            self.hide_after = hide_after
        if hover_opaque is not None:
            self.hover_opaque = hover_opaque
        if max_height is not None:
            self.max_height = max_height
        self._hovering = False
        if not self._hwnd:
            return
        self._layout()
        width = self.win.winfo_width() or self.win.winfo_reqwidth()
        height = self.win.winfo_height() or self.win.winfo_reqheight()
        self._apply_alpha(self.opacity)
        self._apply_round_region(width, height)

    # ------------------------------------------------------------------
    # 滚动
    # ------------------------------------------------------------------

    def _on_inner_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_wheel(self, event):
        if not self._scrollable:
            return "break"
        steps = int(-event.delta / 120)
        if steps == 0:
            steps = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(steps, "units")
        return "break"

    def _sync_scroll_hint(self):
        if not hasattr(self, "_subtitle_label") or self._subtitle_label is None:
            return
        if self._scrollable:
            self._subtitle_label.configure(text="滚轮可查看更多内容")
        elif self._subtitle_base:
            self._subtitle_label.configure(text=self._subtitle_base)

    # ------------------------------------------------------------------
    # 交互: 拖动 / 悬停高亮 / 点击复制
    # ------------------------------------------------------------------

    @staticmethod
    def _set_bg(widget, color):
        try:
            widget.configure(bg=color)
        except tk.TclError:
            return
        for child in widget.winfo_children():
            if isinstance(child, tk.Button):
                continue
            Popup._set_bg(child, color)

    @staticmethod
    def _block_of(widget):
        while widget is not None:
            if getattr(widget, "_is_block", False):
                return widget
            widget = getattr(widget, "master", None)
        return None

    @staticmethod
    def _alive(widget):
        try:
            return widget is not None and bool(widget.winfo_exists())
        except tk.TclError:
            return False

    @staticmethod
    def _point_in_block(block, x, y):
        try:
            left = block.winfo_rootx()
            top = block.winfo_rooty()
            return (left <= x <= left + block.winfo_width()
                    and top <= y <= top + block.winfo_height())
        except tk.TclError:
            return False

    def _bind_interactive(self, widget, block=None):
        if getattr(widget, "_is_block", False):
            block = widget
        widget.bind("<Button-1>", self._on_press)
        widget.bind("<B1-Motion>", self._on_drag_move)
        widget.bind("<ButtonRelease-1>", self._on_release)
        if block is not None:
            # 块里每个子控件都要绑: 鼠标从块挪到块内文字上时块也会发 Leave,
            # 只绑块本身就会"闪一下又灭"。
            widget.bind("<Enter>", lambda event, b=block: self._block_enter(b))
            widget.bind("<Leave>", lambda event, b=block: self._block_leave(b))
        for child in widget.winfo_children():
            if isinstance(child, tk.Button):
                continue
            self._bind_interactive(child, block)

    def _on_press(self, event):
        self._press = (event.x_root, event.y_root)
        self._moved = False
        self._drag_offset = (event.x_root - self.win.winfo_x(),
                             event.y_root - self.win.winfo_y())

    def _on_drag_move(self, event):
        if not self._drag_offset or not self._press:
            return
        if not self._moved:
            if (abs(event.x_root - self._press[0]) > DRAG_SLOP
                    or abs(event.y_root - self._press[1]) > DRAG_SLOP):
                self._moved = True
        if self._moved:
            self.win.geometry("+%d+%d" % (event.x_root - self._drag_offset[0],
                                          event.y_root - self._drag_offset[1]))
            if self.on_geometry:
                self.on_geometry()

    def _on_release(self, event):
        moved = self._moved
        widget = event.widget
        self._press = None
        self._moved = False
        self._drag_offset = None
        if moved:
            return
        block = self._block_of(widget)
        if block is not None:
            text = getattr(block, "_copy_text", "")
            if text:
                self._copy(text)
                self._flash(block)

    def _block_enter(self, block):
        if self._leave_timer:
            self.master.after_cancel(self._leave_timer)
            self._leave_timer = None
        if self._hover_block is not block:
            if self._alive(self._hover_block):
                self._set_bg(self._hover_block, CARD_BG)
            self._hover_block = block
            self._set_bg(block, BLOCK_HOVER)

    def _block_leave(self, block):
        if self._leave_timer:
            self.master.after_cancel(self._leave_timer)
        # 延迟一点点: 鼠标从块挪到块内子控件时也会触发 Leave, 别闪
        self._leave_timer = self.master.after(70, lambda: self._do_leave(block))

    def _do_leave(self, block):
        self._leave_timer = None
        if self._hover_block is block:
            self._hover_block = None
            if self._alive(block):
                self._set_bg(block, CARD_BG)

    def _flash(self, block):
        self._set_bg(block, BLOCK_COPIED)
        if self._flash_timer:
            self.master.after_cancel(self._flash_timer)
        self._flash_timer = self.master.after(420, lambda: self._unflash(block))

    def _unflash(self, block):
        self._flash_timer = None
        if not self._alive(block):
            return
        self._set_bg(block, BLOCK_HOVER if block is self._hover_block else CARD_BG)

    # ------------------------------------------------------------------

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
        self._subtitle_label = None
        self._hover_block = None
        for parent in (self.header_frame, self.inner):
            for child in parent.winfo_children():
                child.destroy()

    def _label(self, parent, text, fg, size=10, bold=False, pady=0, wraplength=None):
        label = tk.Label(parent, text=text, bg=CARD_BG, fg=fg, justify="left",
                         anchor="w", wraplength=wraplength or (CARD_WIDTH - 24),
                         font=(FONT_FAMILY, size, "bold" if bold else "normal"))
        label.pack(fill="x", pady=pady)
        return label

    def _header(self, title, subtitle=None, small_title=False):
        box = tk.Frame(self.header_frame, bg=CARD_BG)
        box.pack(side="left", fill="x", expand=True)
        self._header_box = box
        self._title_label = tk.Label(
            box, text=title, bg=CARD_BG, fg=TITLE_FG, justify="left", anchor="nw",
            wraplength=CARD_WIDTH - 108,
            font=(FONT_FAMILY, 9 if small_title else 12, "normal" if small_title else "bold"))
        self._title_label.pack(anchor="w")
        self._subtitle_base = subtitle or ""
        self._subtitle_label = tk.Label(box, text=self._subtitle_base, bg=CARD_BG,
                                        fg=NOTE_FG, justify="left", anchor="w",
                                        wraplength=CARD_WIDTH - 24,
                                        font=(FONT_FAMILY, 8))
        if subtitle:
            self._subtitle_label.pack(anchor="w", pady=(3, 0))
        button = tk.Button(self.header_frame, text="复制全部", command=self._copy_all,
                           bg=BUTTON_BG, fg=BUTTON_FG, activebackground=BUTTON_ACTIVE,
                           activeforeground=TITLE_FG, relief="flat", bd=0,
                           highlightthickness=0, font=(FONT_FAMILY, 8),
                           padx=9, pady=2, cursor="hand2")
        button.pack(side="right", anchor="ne", padx=(10, 0))
        self._copy_btn = button

    # ---- 原文区: 小字号 + 超行收起 ----

    def _wrap_lines(self, text, font, max_px):
        """按像素宽度手工折行, 这样才能准确知道有几行。"""
        lines = []
        current = ""
        for word in text.split():
            trial = (current + " " + word).strip()
            if not current or font.measure(trial) <= max_px:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

    def _origin_area(self, text):
        self._origin_full = text
        self._origin_expanded = False
        holder = tk.Frame(self._header_box, bg=CARD_BG)
        holder.pack(anchor="w", fill="x", pady=(4, 0))
        label = tk.Label(holder, text="", bg=CARD_BG, fg=NOTE_FG, justify="left",
                         anchor="w", wraplength=CARD_WIDTH - 108,
                         font=(FONT_FAMILY, 9))
        label.pack(anchor="w")
        link = tk.Label(holder, text="展开全文", bg=CARD_BG, fg=LINK_FG,
                        font=(FONT_FAMILY, 8), cursor="hand2")
        self._origin_holder = holder
        self._origin_label = label
        self._origin_link = link
        # 原文本身也当做一个可点块: 悬停高亮, 点击复制整段原文
        label._is_block = True
        label._copy_text = text
        link.bind("<Button-1>", lambda event: self._toggle_origin())
        self._apply_origin()

    def _apply_origin(self):
        text = self._origin_full
        if self._origin_expanded:
            self._origin_label.configure(text=text)
            self._origin_link.configure(text="收起")
            self._origin_link.pack(anchor="w", pady=(2, 0))
            return
        lines = self._wrap_lines(text, self._small_font, CARD_WIDTH - 120)
        if len(lines) > MAX_ORIGIN_LINES:
            shown = "\n".join(lines[:MAX_ORIGIN_LINES]) + " …"
            self._origin_label.configure(text=shown)
            self._origin_link.configure(text="展开全文")
            self._origin_link.pack(anchor="w", pady=(2, 0))
        else:
            self._origin_label.configure(text="\n".join(lines))
            self._origin_link.pack_forget()

    def _toggle_origin(self):
        self._origin_expanded = not self._origin_expanded
        self._apply_origin()
        self._resize_in_place()

    def _sync_scroll_state(self):
        """按窗口真实落地后的尺寸, 判断到底需不需要滚动。"""
        self.win.update_idletasks()
        content_h = self.inner.winfo_reqheight()
        # 用"请求高度"而不是"实际高度": 刚改完几何时实际高度还没刷新, 会误判
        actual = self.canvas.winfo_reqheight()
        self._scrollable = content_h > actual + 1
        if not self._scrollable:
            self.canvas.yview_moveto(0)
        self._on_inner_configure()
        self._sync_scroll_hint()

    def _resize_in_place(self):
        """标题区或内容变了以后, 就地重新算一次窗口大小。"""
        self._layout()
        self.win.update_idletasks()
        width = self.win.winfo_reqwidth()
        height = self.win.winfo_reqheight()
        x = self.win.winfo_x()
        y = self.win.winfo_y()
        screen_h = self.win.winfo_screenheight()
        if y + height > screen_h - 8:
            y = max(8, screen_h - height - 8)
        self.win.geometry("%dx%d+%d+%d" % (width, height, x, y))
        self._apply_round_region(width, height)
        self._sync_scroll_state()
        if self.on_geometry:
            self.on_geometry()

    # ---- 单词块 ----

    def _block(self, parent, title, lines, copy_text):
        block = tk.Frame(parent, bg=CARD_BG, padx=7, pady=5)
        block.pack(fill="x", pady=(6, 0))
        block._is_block = True
        block._copy_text = copy_text
        if title:
            tk.Label(block, text=title, bg=CARD_BG, fg=PHONETIC_FG, justify="left",
                     anchor="w", wraplength=CARD_WIDTH - 34,
                     font=(FONT_FAMILY, 10, "bold")).pack(fill="x")
        for index, line in enumerate(lines):
            tk.Label(block, text=line, bg=CARD_BG, fg=BODY_FG, justify="left",
                     anchor="w", wraplength=CARD_WIDTH - 34,
                     font=(FONT_FAMILY, 9)).pack(fill="x",
                                                  pady=(3 if index == 0 else 1, 0))
        return block

    # ------------------------------------------------------------------

    def _copy(self, text):
        try:
            write_clipboard_text(text)
        except Exception:
            return
        if self._copy_btn and self._copy_btn.winfo_exists():
            self._copy_btn.configure(text="已复制")
            if self._copy_timer:
                self.master.after_cancel(self._copy_timer)
            self._copy_timer = self.master.after(1400, self._reset_copy_label)

    def _copy_all(self):
        if self._clipboard_text:
            self._copy(self._clipboard_text)

    def _reset_copy_label(self):
        self._copy_timer = None
        if self._copy_btn and self._copy_btn.winfo_exists():
            self._copy_btn.configure(text="复制全部")

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
            self._header(result.query)
            self._label(self.inner, "词典里没有这个词条", NOTE_FG, size=9, pady=(6, 0))
            self._bind_interactive(self.header_frame)
            self._bind_interactive(self.inner)
            return

        if result.kind in ("word", "phrase"):
            entry = result.entry
            title = entry.word
            if entry.phonetic:
                title += "   /%s/" % entry.phonetic.strip("/")
            self._header(title)

            all_lines = ["%s  /%s/" % (entry.word, entry.phonetic.strip("/"))
                         if entry.phonetic else entry.word]
            marks = []
            if entry.tags:
                marks.append("、".join(entry.tags))
            if entry.collins:
                marks.append("柯林斯 %d 星" % entry.collins)
            if entry.oxford:
                marks.append("牛津核心")
            if marks:
                mark_text = " · ".join(marks)
                self._label(self.inner, mark_text, TAG_FG, size=9, pady=(0, 0))
                all_lines.append(mark_text)

            body = (entry.translation or entry.definition)[:MAX_DEF_LINES]
            block_text = "\n".join([all_lines[0]] + body)
            self._block(self.inner, None, body, block_text)
            all_lines.extend(body)

            if entry.exchange:
                note = self._exchange_note(entry.exchange)
                self._label(self.inner, note, NOTE_FG, size=8, pady=(9, 0))
                all_lines.append(note)

            self._clipboard_text = "\n".join(all_lines)
            self._bind_interactive(self.header_frame)
            self._bind_interactive(self.inner)
            return

        # breakdown: 整串没查到, 退回逐词
        self._header("逐词释义", "整串没有词条，下面按词拆开")
        self._origin_area(result.query)
        all_lines = ["【原文】%s" % result.query, ""]
        for entry, matched, token in result.parts:
            head = "%s -> %s" % (token, entry.word) if matched else token
            body = (entry.translation or entry.definition)[:MAX_DEF_LINES]
            copy_text = "\n".join([head] + body)
            self._block(self.inner, head, body, copy_text)
            all_lines.append(copy_text)
            all_lines.append("")
        self._clipboard_text = "\n".join(all_lines).rstrip()
        self._bind_interactive(self.header_frame)
        self._bind_interactive(self.inner)

    # ------------------------------------------------------------------
    # 布局与显示
    # ------------------------------------------------------------------

    def _layout(self):
        """按内容算出窗口大小; 整窗高度不超过 max_height, 超出就打开滚动。"""
        self.win.update_idletasks()
        self.inner.update_idletasks()
        content_h = self.inner.winfo_reqheight()

        # 先量出"除内容区以外"的固定高度(边框 + 内边距 + 标题区)
        self.canvas.configure(height=1)
        self.win.update_idletasks()
        chrome = max(self.win.winfo_reqheight() - 1, 0)

        visible = min(content_h, max(self.max_height - chrome, 40))
        self.canvas.configure(height=max(visible, 1))
        self.canvas.itemconfigure(self.canvas_window, width=CARD_WIDTH)
        self.win.update_idletasks()

    def show(self, result, x, y):
        self._render(result)
        self._layout()
        self.canvas.yview_moveto(0)

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
        if pos_y < 8:
            pos_y = 8

        self.win.geometry("%dx%d+%d+%d" % (width, height, pos_x, pos_y))
        self.win.deiconify()
        self.win.lift()
        self._apply_styles()
        self._apply_round_region(width, height)
        self._hovering = False
        self._apply_alpha(self.opacity)
        self._drag_offset = None
        self._press = None
        self._moved = False
        self._sync_scroll_state()

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
            self._restart_timer()
        # 兜底: 万一漏掉了 Leave, 这里按坐标把高亮纠正过来
        if self._hover_block is not None:
            block = self._hover_block
            if not self._alive(block):
                self._hover_block = None
            elif block.winfo_width() > 1 and not self._point_in_block(block, pointer_x, pointer_y):
                # 宽度还是 1 说明布局没落定, 这时别下结论
                self._hover_block = None
                self._set_bg(block, CARD_BG)
        self._schedule_hover_check()

    def hide(self):
        for attr in ("_timer", "_hover_timer", "_leave_timer", "_copy_timer",
                     "_flash_timer"):
            timer = getattr(self, attr)
            if timer:
                try:
                    self.master.after_cancel(timer)
                except Exception:
                    pass
                setattr(self, attr, None)
        self._hovering = False
        self._hover_block = None
        self._drag_offset = None
        self._press = None
        self._moved = False
        self.win.withdraw()
        if self.on_geometry:
            self.on_geometry()
