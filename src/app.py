# -*- coding: utf-8 -*-
"""把鼠标钩子、词典、浮窗串起来。

线程模型:
  - 主线程: tkinter 事件循环(浮窗) + 每 25ms 轮询结果队列
  - 钩子线程: 底层鼠标钩子 + 热键消息循环
  - 取词线程: 真正做 Ctrl+C 和读剪贴板(慢活)
"""
from __future__ import annotations

import queue
import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture import MOD_ALT, MOD_CONTROL, SelectionWatcher  # noqa: E402
from dictionary import Dictionary, Result  # noqa: E402
from popup import Popup  # noqa: E402

HOTKEYS = [
    (MOD_CONTROL | MOD_ALT, ord("Q"), "quit"),
    (MOD_CONTROL | MOD_ALT, ord("P"), "pause"),
]


class App:
    def __init__(self, db_path, index_path=None, drag_threshold=6,
                 hide_after=9.0, log_path=None):
        self.log_path = Path(log_path) if log_path else None
        self.dictionary = Dictionary(db_path, index_path)
        self.root = tk.Tk()
        self.root.withdraw()
        self.popup = Popup(self.root, hide_after=hide_after)
        self.results = queue.Queue()
        self.watcher = SelectionWatcher(
            on_selection=self._on_selection,
            on_hotkey=self._on_hotkey,
            drag_threshold=drag_threshold,
            hotkeys=HOTKEYS,
            logger=self.log,
        )
        self._paused = False

    def log(self, message):
        line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message)
        if self.log_path:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                pass

    def _on_selection(self, text, x, y):
        """在取词线程里被调用, 只投递, 不碰界面。"""
        self.results.put((text, x, y))

    def _on_hotkey(self, name):
        """在钩子线程里被调用。"""
        if name == "quit":
            self.root.after(0, self.quit)
        elif name == "pause":
            self._paused = not self._paused
            self.watcher.paused = self._paused
            self.log("paused=%s" % self._paused)
            self.root.after(0, self._flash_pause)

    def _flash_pause(self):
        state = "已暂停" if self._paused else "已恢复"
        notice = Result(kind="miss", query=state)
        self.popup.show(notice, self.root.winfo_pointerx(), self.root.winfo_pointery())

    def _pump(self):
        """主线程: 消费取词结果。"""
        try:
            while True:
                text, x, y = self.results.get_nowait()
                if len(text) > 4000:
                    text = text[:4000]
                started = time.perf_counter()
                result = self.dictionary.lookup(text)
                cost = (time.perf_counter() - started) * 1000
                self.log("查词 %.1fms  kind=%s  %r" % (cost, result.kind, text[:60]))
                self.popup.show(result, x, y)
        except queue.Empty:
            pass
        self.root.after(25, self._pump)

    def quit(self):
        try:
            self.watcher.stop()
        finally:
            self.root.quit()

    def run(self):
        stats = self.dictionary.stats()
        self.log("启动, 词条 %s, 词形 %s" % (format(stats["entries"], ","),
                                             format(stats["forms"], ",")))
        self.watcher.start()
        self.root.after(25, self._pump)
        self.root.mainloop()
        self.dictionary.close()
        self.log("退出")
