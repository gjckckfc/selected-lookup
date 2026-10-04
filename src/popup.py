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
BLOCK_SPEAK = "#33405f"

BUTTON_BG = "#2c3648"
BUTTON_FG = "#c9d6ea"
BUTTON_ACTIVE = "#3b4a63"

FONT_FAMILY = "Microsoft YaHei UI"
# ---------------------------------------------------------------------------
# 外观常量: 这里是唯一的调整入口, 不再开放成用户设置。
# 浮窗是阅读时的配角, 样子和尺寸由我们先定好。
# ---------------------------------------------------------------------------
DEFAULT_WIDTH = 300             # 浮窗总宽度(px); 再窄标题和标签就会折行
DEFAULT_MAX_HEIGHT = 380        # 浮窗最大高度(px), 装不下就滚
DEFAULT_RADIUS = 14             # 圆角半径(px), 12-16 之间比较好看
DEFAULT_OPACITY = 88            # 不透明度(%), 100 = 完全不透明
DEFAULT_HOVER_OPAQUE = True     # 鼠标移上去时变完全不透明, 方便看清
PADDING_X = 32                  # 左右内边距 + 边框
DRAG_SLOP = 4            # 松开时位移小于这个值算"点击", 否则算"拖动"
MAX_DEF_LINES = 3        # 每个单词块最多显示几行释义
MAX_ORIGIN_LINES = 2     # 原文最多显示几行, 超出收起
SCROLL_STEP = 26         # 滚轮一格滚多少像素
PREWARM_DELAY = 250      # 鼠标在块上停多久就在后台预生成语音(毫秒)

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
    def __init__(self, master, hide_after=5.0, radius=DEFAULT_RADIUS,
                 opacity=DEFAULT_OPACITY,
                 hover_opaque=DEFAULT_HOVER_OPAQUE, width=DEFAULT_WIDTH,
                 max_height=DEFAULT_MAX_HEIGHT, on_geometry=None,
                 on_speak=None, on_stop_speak=None, on_prewarm=None):
        self.master = master
        self.hide_after = hide_after
        self.radius = radius
        self.opacity = max(40, min(100, opacity))
        self.hover_opaque = hover_opaque
        self.width = max(220, width)
        self.max_height = max_height
        self.on_geometry = on_geometry
        self.on_speak = on_speak
        self.on_stop_speak = on_stop_speak
        self.on_prewarm = on_prewarm
        self._last_result = None

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
        self._speak_widget = None
        self._speak_token = 0
        self._speak_timer = None
        self._prewarm_timer = None
        self._prewarmed = set()

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
        inner_w = self.inner_width
        self.canvas = tk.Canvas(self.card, bg=CARD_BG, highlightthickness=0,
                                bd=0, width=inner_w, height=10,
                                yscrollincrement=SCROLL_STEP)
        self.canvas.pack(fill="x", pady=(0, 0))
        self.inner = tk.Frame(self.canvas, bg=CARD_BG)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.inner,
                                                       anchor="nw", width=inner_w)
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.win.bind("<MouseWheel>", self._on_wheel)

        self.win.update_idletasks()
        self._hwnd = user32.GetParent(self.win.winfo_id())
        self._apply_styles()

    @property
    def inner_width(self):
        """内容区(Canvas)宽度。"""
        return max(self.width - PADDING_X, 160)

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

    def apply_settings(self, hide_after=None):
        """外观不开放给用户改, 这里只接受会影响行为的那一项。"""
        if hide_after is not None:
            self.hide_after = hide_after

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
        widget.bind("<Button-3>", self._on_right_click)
        if block is not None:
            # 块里每个子控件都要绑: 鼠标从块挪到块内文字上时块也会发 Leave,
            # 只绑块本身就会"闪一下又灭"。
            widget.bind("<Enter>", lambda event, b=block: self._block_enter(b))
            widget.bind("<Leave>", lambda event, b=block: self._block_leave(b))
        for child in widget.winfo_children():
            if isinstance(child, tk.Button):
                continue
            self._bind_interactive(child, block)

    # ---- 右键朗读 ----

    @staticmethod
    def _speak_target(widget):
        """往上找第一个带朗读文字的控件, 返回 (控件, 文字)。"""
        while widget is not None:
            text = getattr(widget, "_speak_text", "")
            if text:
                return widget, text
            widget = getattr(widget, "master", None)
        return None, ""

    @staticmethod
    def _lang_of(text):
        """按内容猜语种: 中文字占多数就用中文语音。"""
        cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        letters = sum(1 for char in text if char.isascii() and char.isalpha())
        return "zh" if cjk > letters else "en"

    def _on_right_click(self, event):
        widget, text = self._speak_target(event.widget)
        if not text or self.on_speak is None:
            return "break"
        block = self._block_of(widget) or widget
        self._speak_token += 1
        token = self._speak_token
        self._mark_speaking(block)
        if not self.on_speak(token, text, self._lang_of(text)):
            self._end_speaking()
        return "break"

    def _mark_speaking(self, widget):
        self._end_speaking()
        self._speak_widget = widget
        self._set_bg(widget, BLOCK_SPEAK)
        # 兜底: 万一声音没能开始, 3 秒后自己把高亮收掉
        self._speak_timer = self.master.after(3000, self._end_speaking)

    def mark_speaking(self, token, duration_ms):
        """声音真的开始了: 按音频时长决定高亮什么时候收起。"""
        if token != self._speak_token:
            return
        if self._speak_timer:
            try:
                self.master.after_cancel(self._speak_timer)
            except Exception:
                pass
        delay = int(duration_ms) + 250 if duration_ms else 3000
        self._speak_timer = self.master.after(max(delay, 500), self._end_speaking)

    def _end_speaking(self):
        if self._speak_timer:
            try:
                self.master.after_cancel(self._speak_timer)
            except Exception:
                pass
            self._speak_timer = None
        widget, self._speak_widget = self._speak_widget, None
        if self._alive(widget):
            self._set_bg(widget, BLOCK_HOVER if widget is self._hover_block else CARD_BG)

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
        # 自己带点击回调的控件(比如「展开全文」)优先
        handler = getattr(widget, "_on_click", None)
        if handler is not None:
            handler()
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
        self._schedule_prewarm(block)

    def _block_leave(self, block):
        if self._prewarm_timer:
            self.master.after_cancel(self._prewarm_timer)
            self._prewarm_timer = None
        if self._leave_timer:
            self.master.after_cancel(self._leave_timer)
        # 延迟一点点: 鼠标从块挪到块内子控件时也会触发 Leave, 别闪
        self._leave_timer = self.master.after(70, lambda: self._do_leave(block))

    def _schedule_prewarm(self, block):
        """鼠标在块上停一下就在后台把音频合成好, 右键时就不用等了。"""
        if self.on_prewarm is None:
            return
        text = getattr(block, "_speak_text", "")
        if not text:
            return
        if self._prewarm_timer:
            self.master.after_cancel(self._prewarm_timer)
        self._prewarm_timer = self.master.after(
            PREWARM_DELAY, lambda b=block: self._do_prewarm(b))

    def _do_prewarm(self, block):
        self._prewarm_timer = None
        if not self._alive(block) or self._hover_block is not block:
            return
        text = getattr(block, "_speak_text", "")
        if not text:
            return
        lang = self._lang_of(text)
        key = (text, lang)
        if key in self._prewarmed:
            return
        self._prewarmed.add(key)
        try:
            self.on_prewarm(text, lang)
        except Exception:
            pass

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
        self._end_speaking()
        if self._prewarm_timer:
            try:
                self.master.after_cancel(self._prewarm_timer)
            except Exception:
                pass
            self._prewarm_timer = None
        self._prewarmed.clear()
        self._copy_btn = None
        self._subtitle_label = None
        self._hover_block = None
        for parent in (self.header_frame, self.inner):
            for child in parent.winfo_children():
                child.destroy()

    def _label(self, parent, text, fg, size=10, bold=False, pady=0, wraplength=None):
        label = tk.Label(parent, text=text, bg=CARD_BG, fg=fg, justify="left",
                         anchor="w", wraplength=wraplength or (self.inner_width - 14),
                         font=(FONT_FAMILY, size, "bold" if bold else "normal"))
        label.pack(fill="x", pady=pady)
        return label

    def _header(self, title, subtitle=None, small_title=False, speak=None):
        # 标题行单独一个容器, 这样后面加进来的原文区才会落在它下面,
        # 而不是被塞进"标题和按钮之间的空隙"。
        top = tk.Frame(self.header_frame, bg=CARD_BG)
        # 和下面的释义块对齐: 那些块自带 7px 内边距, 标题行也缩进同样的量
        top.pack(fill="x", padx=7)
        box = tk.Frame(top, bg=CARD_BG)
        box.pack(side="left", fill="x", expand=True)
        self._header_box = box
        self._title_label = tk.Label(
            box, text=title, bg=CARD_BG, fg=TITLE_FG, justify="left", anchor="nw",
            wraplength=self.inner_width - 78,
            font=(FONT_FAMILY, 9 if small_title else 12, "normal" if small_title else "bold"))
        self._title_label.pack(anchor="w")
        self._title_label._speak_text = speak or ""
        self._subtitle_base = subtitle or ""
        self._subtitle_label = tk.Label(box, text=self._subtitle_base, bg=CARD_BG,
                                        fg=NOTE_FG, justify="left", anchor="w",
                                        wraplength=self.inner_width,
                                        font=(FONT_FAMILY, 8))
        if subtitle:
            self._subtitle_label.pack(anchor="w", pady=(3, 0))
        button = tk.Button(top, text="复制全部", command=self._copy_all,
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
        # 原文放进可滚动区, 和译文、单词块是同一页:
        # 滚轮滚的是整页, 而且原文再长也顶不破高度上限。
        holder = tk.Frame(self.inner, bg=CARD_BG)
        holder.pack(fill="x", pady=(0, 4), padx=7)
        label = tk.Label(holder, text="", bg=CARD_BG, fg=NOTE_FG, justify="left",
                         anchor="w", wraplength=self.inner_width - 14,
                         font=(FONT_FAMILY, 9))
        label.pack(fill="x")
        link = tk.Label(holder, text="展开全文", bg=CARD_BG, fg=LINK_FG,
                        font=(FONT_FAMILY, 8), cursor="hand2")
        self._origin_holder = holder
        self._origin_label = label
        self._origin_link = link
        # 原文本身也当做一个可点块: 悬停高亮, 点击复制整段原文
        label._is_block = True
        label._copy_text = text
        label._speak_text = text
        # 不能用 link.bind("<Button-1>", ...): 之后 _bind_interactive 会把
        # 每个控件的 <Button-1> 重绑成拖动起点, 把那次的处理覆盖掉。
        # 所以改用自定义属性, 由 _on_release 在"没拖动"时调用。
        link._on_click = self._toggle_origin
        link.bind("<Enter>", lambda event: link.configure(fg=TITLE_FG))
        link.bind("<Leave>", lambda event: link.configure(fg=LINK_FG))
        self._apply_origin()
        return ["【原文】%s" % text, ""]

    def _apply_origin(self):
        text = self._origin_full
        if self._origin_expanded:
            self._origin_label.configure(text=text)
            self._origin_link.configure(text="收起")
            self._origin_link.pack(anchor="w", pady=(2, 0))
            return
        lines = self._wrap_lines(text, self._small_font, self.inner_width - 18)
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

    def _block(self, parent, title, lines, copy_text, speak=None):
        block = tk.Frame(parent, bg=CARD_BG, padx=7, pady=5)
        block.pack(fill="x", pady=(6, 0))
        block._is_block = True
        block._copy_text = copy_text
        block._speak_text = speak or ""
        if title:
            tk.Label(block, text=title, bg=CARD_BG, fg=PHONETIC_FG, justify="left",
                     anchor="w", wraplength=self.inner_width - 14,
                     font=(FONT_FAMILY, 10, "bold")).pack(fill="x")
        for index, line in enumerate(lines):
            tk.Label(block, text=line, bg=CARD_BG, fg=BODY_FG, justify="left",
                     anchor="w", wraplength=self.inner_width - 14,
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

    def _leading(self, translation, pending, failed):
        """翻译区放在内容最上面: 翻译中 -> 占位; 译文到了 -> 一个可点块。"""
        if pending:
            self._label(self.inner, "翻译中…", NOTE_FG, size=9, pady=(0, 4))
            return ["（翻译中…）"]
        if translation:
            self._block(self.inner, "译文", [translation], translation,
                        speak=translation)
            return [translation, ""]
        if failed:
            self._label(self.inner, "翻译失败，详见 logs/app.log", NOTE_FG,
                        size=9, pady=(0, 4))
        return []

    def _render(self, result, translation=None, pending=False, failed=False):
        self._clear()
        self._clipboard_text = ""
        # 原文必须先放, 它和译文、单词块同属一个滚动区
        origin_lines = self._origin_area(result.query) if result.kind == "breakdown" else []
        lead = self._leading(translation, pending, failed)

        if result.kind == "miss":
            self._header(result.query, speak=result.query)
            self._label(self.inner, "词典里没有这个词条", NOTE_FG, size=9, pady=(6, 0))
            self._bind_interactive(self.header_frame)
            self._bind_interactive(self.inner)
            return

        if result.kind in ("word", "phrase"):
            entry = result.entry
            title = entry.word
            if entry.phonetic:
                title += "   /%s/" % entry.phonetic.strip("/")
            self._header(title, speak=entry.word)

            all_lines = ["%s  /%s/" % (entry.word, entry.phonetic.strip("/"))
                         if entry.phonetic else entry.word]
            all_lines = lead + all_lines
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
            self._block(self.inner, None, body, block_text, speak=entry.word)
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
        all_lines = origin_lines + lead
        for entry, matched, token in result.parts:
            head = "%s -> %s" % (token, entry.word) if matched else token
            body = (entry.translation or entry.definition)[:MAX_DEF_LINES]
            copy_text = "\n".join([head] + body)
            self._block(self.inner, head, body, copy_text, speak=token)
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

        # 宽度固定, 不随内容伸缩
        target_w = self.inner_width
        self.canvas.configure(width=target_w)
        self.canvas.itemconfigure(self.canvas_window, width=target_w)
        self.win.update_idletasks()

        # 先量出"除内容区以外"的固定高度(边框 + 内边距 + 标题区)
        self.canvas.configure(height=1)
        self.win.update_idletasks()
        chrome = max(self.win.winfo_reqheight() - 1, 0)

        visible = min(content_h, max(self.max_height - chrome, 40))
        self.canvas.configure(height=max(visible, 1))
        self.win.update_idletasks()

    def show(self, result, x, y, translation=None, pending=False, failed=False):
        self._last_result = result
        self._render(result, translation=translation, pending=pending, failed=failed)
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

    def update_translation(self, result, translation=None, failed=False):
        """译文到了以后就地更新内容, 窗口位置不动。"""
        self._render(result, translation=translation, failed=failed)
        self._resize_in_place()

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
        self._end_speaking()
        if self._prewarm_timer:
            try:
                self.master.after_cancel(self._prewarm_timer)
            except Exception:
                pass
            self._prewarm_timer = None
        if self.on_stop_speak:
            try:
                self.on_stop_speak()
            except Exception:
                pass
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
