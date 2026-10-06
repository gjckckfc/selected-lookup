# -*- coding: utf-8 -*-
"""第一次运行时的准备向导: 把词典下下来。

为什么要有它: 新用户本来得自己开命令行跑 `scripts/fetch_dict.py`, 盯着一个黑框
看 52 MB 慢慢下 —— 小白到这一步基本就放弃了。这里用程序自己的小窗口（和浮窗
同一套 tkinter）显示进度、速度、还剩多久, 失败了给重试, 全程不用碰命令行。

窗口只在词典缺席时出现一次, 装完就销毁; 之后每次启动都不再经过这里。
下载/校验/解包/建索引的实际逻辑都在 `dictpack.py`, 和命令行脚本共用一套。
"""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import dictpack

STAGE_TEXT = {
    "check": "检查词典…",
    "download": "正在下载词典…",
    "verify": "正在校验下载包…",
    "unzip": "正在解压…",
    "index": "正在整理词形索引…",
}

BAR_WIDTH = 400


def _mb(count):
    if count >= 1048576:
        return "%.1f MB" % (count / 1048576)
    return "%.0f KB" % (count / 1024)


def _duration(seconds):
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return "%d 秒" % seconds
    return "%d 分 %d 秒" % (seconds // 60, seconds % 60)


class SetupWizard:
    """跑起来就阻塞, 直到装完、失败、或者用户取消。"""

    def __init__(self, project_root, logger=None):
        self.project_root = project_root
        self.log = logger or (lambda message: None)
        self.events = queue.Queue()
        self.stop_flag = threading.Event()
        self.result = (False, "没有跑起来")
        self.db_path = None
        self.index_path = None
        self.samples = []
        self.finished = False
        self.root = None
        self.bar = None
        self.status = None
        self.button = None
        self.worker = None

    # ------------------------------------------------------------------

    def run(self):
        """显示窗口, 阻塞到结束。返回 (成功?, 说明)。"""
        self.root = tk.Tk()
        self.root.title("选中即查 · 第一次运行")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_cancel)

        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="第一次运行, 先把词典准备好",
                  font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="需要下载约 52 MB 的词典数据, 只会下载这一次。\n"
                 "装好之后查词完全在本机进行, 不再联网。",
            justify="left",
        ).pack(anchor="w", pady=(6, 14))

        self.bar = ttk.Progressbar(frame, length=BAR_WIDTH, maximum=100)
        self.bar.pack(fill="x")
        self.status = ttk.Label(frame, text="准备中…", width=58, anchor="w")
        self.status.pack(anchor="w", pady=(8, 12))

        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.button = ttk.Button(row, text="取消", command=self._on_cancel)
        self.button.pack(side="right")

        self.root.update_idletasks()
        self._center()
        self._start_worker()
        self.root.after(100, self._pump)
        self.root.mainloop()
        return self.result

    def _center(self):
        """摆到屏幕中间偏上, 别压住任务栏。"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - width) // 2
        y = max(0, int(self.root.winfo_screenheight() * 0.35) - height // 2)
        self.root.geometry("+%d+%d" % (x, y))

    # ------------------------------------------------------------------

    def _start_worker(self):
        self.stop_flag.clear()
        self.samples = []
        self.bar.configure(value=0)
        self.status.configure(text="准备中…")
        self.button.configure(text="取消", command=self._on_cancel)
        self.worker = threading.Thread(target=self._work, name="setup", daemon=True)
        self.worker.start()

    def _work(self):
        """在后台线程里干活, 只往队列里丢事件 —— 不碰任何 tkinter 控件。"""
        try:
            db_path, note = dictpack.ensure_dictionary(
                self.project_root,
                on_progress=lambda stage, done, total:
                    self.events.put(("progress", stage, done, total)),
                should_stop=self.stop_flag.is_set,
            )
            self.log("向导: 词典就绪 %s（%s），开始建索引" % (db_path, note))
            index_path, count = dictpack.build_index(
                db_path,
                on_progress=lambda stage, done, total:
                    self.events.put(("progress", stage, done, total)),
                should_stop=self.stop_flag.is_set,
            )
            self.events.put(("done", str(db_path), str(index_path), count))
        except dictpack.Cancelled:
            self.events.put(("cancelled",))
        except Exception as exc:              # noqa: BLE001 - 什么错都得让用户看见
            self.log("向导失败: %s" % exc)
            self.events.put(("error", str(exc)))

    # ------------------------------------------------------------------

    def _pump(self):
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        if not self.finished:
            self.root.after(100, self._pump)

    def _handle(self, event):
        kind = event[0]
        if kind == "progress":
            self._show_progress(*event[1:])
        elif kind == "done":
            self.db_path = event[1]
            self.index_path = event[2]
            self.log("向导: 准备完成，词典 %s" % self.db_path)
            self._finish(True, "准备完成")
        elif kind == "error":
            self._show_error(event[1])
        elif kind == "cancelled":
            self._finish(False, "已取消")

    def _show_progress(self, stage, done, total):
        text = STAGE_TEXT.get(stage, stage)
        if stage == "download" and total:
            percent = done * 100.0 / total
            self.bar.configure(mode="determinate", value=percent)
            speed = self._speed_text(done, total)
            line = "%s %.0f%%  %s / %s" % (text, percent, _mb(done), _mb(total))
            if speed:
                line += "  " + speed
            self.status.configure(text=line)
        elif stage in ("verify", "unzip") and total:
            self.bar.configure(mode="determinate", value=done * 100.0 / total)
            self.status.configure(text="%s %.0f%%" % (text, done * 100.0 / total))
        else:
            # check / index 这类说不清百分比的阶段: 让进度条来回走
            self.bar.configure(mode="indeterminate")
            self.bar.start(60)
            self.status.configure(text=text)

    def _speed_text(self, done, total):
        now = time.monotonic()
        self.samples.append((now, done))
        self.samples = [s for s in self.samples if s[0] >= now - 6]
        if len(self.samples) < 2:
            return ""
        first_t, first_done = self.samples[0]
        elapsed = now - first_t
        if elapsed < 0.3:
            return ""
        speed = (done - first_done) / elapsed
        if speed <= 0:
            return ""
        text = "%s/s" % _mb(speed)
        if total:
            text += "，还要 %s" % _duration((total - done) / speed)
        return text

    def _show_error(self, message):
        self.bar.stop()
        self.bar.configure(mode="determinate", value=0)
        self.status.configure(text="出错：%s" % message)
        self.button.configure(text="重试", command=self._retry)

    def _retry(self):
        self._start_worker()

    # ------------------------------------------------------------------

    def _on_cancel(self):
        if self.button.cget("text") == "重试":
            self._finish(False, "已取消")
            return
        self.status.configure(text="正在取消…")
        self.stop_flag.set()

    def _finish(self, ok, message):
        if self.finished:
            return
        self.finished = True
        self.result = (ok, message)
        if ok:
            self.bar.stop()
            self.bar.configure(mode="determinate", value=100)
            self.status.configure(text="准备完成，正在启动…")
            self.root.after(400, self.root.destroy)
        else:
            self.root.destroy()
