# -*- coding: utf-8 -*-
"""把鼠标钩子、词典、浮窗、托盘、设置面板串起来。

线程模型:
  - 主线程: tkinter 事件循环(浮窗 + 设置窗) + 每 25ms 轮询命令与结果队列
  - 钩子线程: 底层鼠标钩子 + 热键消息循环
  - 取词线程: 真正做 Ctrl+C 和读剪贴板(慢活)
  - 托盘线程: Shell_NotifyIcon 的消息循环

所有跨线程动作都只往命令队列里放一个字符串, 由主线程执行,
避免在非主线程里碰 tkinter。
"""
from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture import MOD_ALT, MOD_CONTROL, SelectionWatcher  # noqa: E402
from dictionary import Dictionary  # noqa: E402
from popup import Popup  # noqa: E402
from settings_ui import SettingsWindow  # noqa: E402
from tray import TrayIcon  # noqa: E402
from translate import Translator  # noqa: E402

HOTKEYS = [
    (MOD_CONTROL | MOD_ALT, ord("Q"), "quit"),
    (MOD_CONTROL | MOD_ALT, ord("P"), "pause"),
]


class App:
    def __init__(self, db_path, index_path=None, settings=None, log_path=None):
        self.log_path = Path(log_path) if log_path else None
        self.settings_path = Path(settings) if settings else None
        if self.settings_path:
            from settings import Settings
            self.settings = Settings(self.settings_path)
        else:
            from settings import Settings
            self.settings = Settings(Path(__file__).resolve().parent.parent / "settings.json")

        self.dictionary = Dictionary(db_path, index_path)
        self.translator = Translator(
            Path(db_path).resolve().parent / "translate_cache.sqlite", logger=self.log)
        self._reload_translator()
        self.translate_results = queue.Queue()
        self._translate_seq = 0
        self.root = tk.Tk()
        self.root.withdraw()

        self.popup = Popup(
            self.root,
            hide_after=self.settings.get("hide_after"),
            on_geometry=self._sync_popup_rect,
        )
        self.results = queue.Queue()
        self.commands = queue.Queue()
        self.enabled = bool(self.settings.get("enabled"))

        self.watcher = SelectionWatcher(
            on_selection=self._on_selection,
            on_dismiss=lambda: self.commands.put("hide"),
            on_hotkey=self._on_hotkey,
            drag_threshold=self.settings.get("drag_threshold"),
            hotkeys=HOTKEYS,
            logger=self.log,
        )
        self.watcher.paused = not self.enabled

        self.tray = TrayIcon(
            enabled=self.enabled,
            on_toggle=lambda: self.commands.put("toggle"),
            on_settings=lambda: self.commands.put("settings"),
            on_quit=lambda: self.commands.put("quit"),
            logger=self.log,
        )
        self.settings_window = SettingsWindow(
            self.root, self.settings,
            on_change=self._on_setting_changed,
            on_reset=self._apply_all_settings,
        )
        self.settings_window.on_test_translate = self._test_translate

    # ------------------------------------------------------------------
    # 翻译
    # ------------------------------------------------------------------

    def _reload_translator(self):
        self.translator.configure(
            api_key=self.settings.get("api_key"),
            model=self.settings.get("model"),
        )

    def _test_translate(self):
        self._reload_translator()
        return self.translator.test()

    def _translate_ready(self):
        return bool(self.settings.get("translate_enabled")) and self.translator.available

    @staticmethod
    def _looks_like_sentence(text):
        """单词和词组交给词典, 只有句子才值得花 token 去翻译。"""
        stripped = text.strip()
        if len(stripped) < 12:
            return False
        words = stripped.split()
        if len(words) >= 3:
            return True
        return len(words) >= 2 and stripped.endswith((".", "!", "?"))

    def _do_translate(self, seq, text, result):
        translation = self.translator.translate(text)
        self.translate_results.put((seq, result, translation))

    def _sync_popup_rect(self):
        """把浮窗当前占的矩形告诉钩子, 让按在浮窗上的手势不被当成选词。"""
        watcher = getattr(self, "watcher", None)
        if watcher is not None:
            watcher.set_ignore_rect(self.popup.rect())

    def log(self, message):
        line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message)
        if self.log_path:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                pass

    # ------------------------------------------------------------------
    # 各线程统一往命令队列投递, 由主线程执行
    # ------------------------------------------------------------------

    def _on_selection(self, text, x, y):
        self.results.put((text, x, y))

    def _on_hotkey(self, name):
        self.commands.put(name)

    # ------------------------------------------------------------------

    def _toggle(self):
        self.enabled = not self.enabled
        self.settings.set("enabled", self.enabled)
        self.watcher.paused = not self.enabled
        self.tray.set_enabled(self.enabled)
        if not self.enabled:
            self.popup.hide()
            while True:
                try:
                    self.results.get_nowait()
                except queue.Empty:
                    break
        if self.settings_window:
            self.settings_window.refresh()
        self.log("取词 %s" % ("开启" if self.enabled else "关闭"))

    def _on_setting_changed(self, key, value):
        """设置面板里任何一项改动都会走到这里, 立即生效。"""
        if key == "enabled":
            if bool(value) != self.enabled:
                self._toggle()
            return
        if key == "drag_threshold":
            self.watcher.drag_threshold = value
        elif key == "hide_after":
            self.popup.apply_settings(hide_after=value)
        elif key in ("translate_enabled", "api_key", "model"):
            self._reload_translator()
        self.log("设置 %s = %s" % (key, value))

    def _apply_all_settings(self):
        self.watcher.drag_threshold = self.settings.get("drag_threshold")
        self.popup.apply_settings(hide_after=self.settings.get("hide_after"))
        want = bool(self.settings.get("enabled"))
        if want != self.enabled:
            self._toggle()
        self._reload_translator()
        self.log("已恢复默认设置")

    def _open_settings(self):
        self.settings_window.open()

    # ------------------------------------------------------------------

    def _pump(self):
        """主线程: 先处理命令, 再消费取词结果。"""
        try:
            while True:
                command = self.commands.get_nowait()
                if command == "quit":
                    self.quit()
                    return
                if command in ("toggle", "pause"):
                    self._toggle()
                elif command == "hide":
                    self.popup.hide()
                elif command == "settings":
                    self._open_settings()
        except queue.Empty:
            pass

        if not self.enabled:
            self.root.after(25, self._pump)
            return

        # 译文先到先处理, 免得被后到的选词顶掉
        try:
            while True:
                seq, result, translation = self.translate_results.get_nowait()
                if seq != self._translate_seq:
                    continue
                if translation:
                    self.popup.update_translation(result, translation=translation)
                else:
                    self.popup.update_translation(result, failed=True)
        except queue.Empty:
            pass

        try:
            while True:
                text, x, y = self.results.get_nowait()
                if len(text) > 4000:
                    text = text[:4000]
                started = time.perf_counter()
                result = self.dictionary.lookup(text)
                cost = (time.perf_counter() - started) * 1000
                self.log("查词 %.1fms  kind=%s  %r" % (cost, result.kind, text[:60]))

                self._translate_seq += 1
                seq = self._translate_seq
                cached = self.translator.cache_get(text) if self._translate_ready() else None
                if cached:
                    self.log("译文命中缓存")
                    self.popup.show(result, x, y, translation=cached)
                elif self._translate_ready() and self._looks_like_sentence(text):
                    self.popup.show(result, x, y, pending=True)
                    threading.Thread(target=self._do_translate,
                                     args=(seq, text, result), daemon=True).start()
                else:
                    self.popup.show(result, x, y)
        except queue.Empty:
            pass
        self.root.after(25, self._pump)

    def quit(self):
        try:
            self.watcher.stop()
        finally:
            self.tray.stop()
            self.translator.close()
            self.root.quit()

    def run(self):
        stats = self.dictionary.stats()
        self.log("启动, 词条 %s, 词形 %s, 设置 %s" % (
            format(stats["entries"], ","), format(stats["forms"], ","),
            self.settings_path or "(默认)"))
        if self._translate_ready():
            self.log("整句翻译已启用: %s / %s, 缓存 %d 条" % (
                self.translator.base_url, self.translator.model,
                self.translator.cache_count()))
        else:
            self.log("整句翻译未启用（未开启或密钥未填）")
        self.watcher.start()
        self.tray.start()
        self.root.after(25, self._pump)
        self.root.mainloop()
        self.dictionary.close()
        self.log("退出")
