# -*- coding: utf-8 -*-
"""调试用: 把浮窗和设置窗直接渲染出来, 方便看外观。

    python scripts/preview_popup.py            # 只显示浮窗
    python scripts/preview_popup.py --settings # 连设置窗一起显示

按 Ctrl+C 或关掉控制台结束。
"""
from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dictionary import Dictionary  # noqa: E402
from popup import Popup  # noqa: E402
from settings import Settings  # noqa: E402
from settings_ui import SettingsWindow  # noqa: E402

HEAD = "inflation"
LONG_SAMPLE = ("the aggregate demand curve shifts when any component of planned "
               "spending changes, including consumption, investment, government "
               "purchases and net exports")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", action="store_true", help="同时显示设置窗口")
    parser.add_argument("--word", default=HEAD, help="预览哪个词")
    parser.add_argument("--opacity", type=int, help="临时覆盖不透明度, 单位百分比")
    parser.add_argument("--radius", type=int, help="临时覆盖圆角半径, 单位像素")
    parser.add_argument("--width", type=int, help="临时覆盖宽度, 单位像素")
    parser.add_argument("--hover", type=int, help="把第几个单词块显示成悬停高亮(从 0 数)")
    parser.add_argument("--long", action="store_true", help="用一长段英文原文来预览")
    args = parser.parse_args()

    settings = Settings(ROOT / "settings.json")
    dictionary = Dictionary(ROOT / "data" / "ecdict.sqlite",
                            ROOT / "data" / "inflection.sqlite")

    root = tk.Tk()
    root.withdraw()
    overrides = {}
    if args.opacity is not None:
        overrides["opacity"] = args.opacity
    if args.radius is not None:
        overrides["radius"] = args.radius
    if args.width is not None:
        overrides["width"] = args.width
    popup = Popup(root, hide_after=settings.get("hide_after"), **overrides)
    result = dictionary.lookup(LONG_SAMPLE if args.long else args.word)
    popup.show(result, 420, 320)

    if args.hover is not None:
        found = []

        def walk(widget):
            if getattr(widget, "_is_block", False):
                found.append(widget)
            for child in widget.winfo_children():
                walk(child)

        walk(popup.card)
        if 0 <= args.hover < len(found):
            popup._block_enter(found[args.hover])
            root.update()
            print("已把第 %d 个单词块置为悬停高亮" % args.hover)

    if args.settings:
        window = SettingsWindow(root, settings, on_change=lambda key, value: None)
        window.open()

    print("浮窗已显示, 关闭窗口或按 Ctrl+C 结束")
    print("当前: 宽 %s px / 圆角 %s px / 不透明度 %s%% / 停留 %s 秒" % (
        popup.width, popup.radius, popup.opacity, popup.hide_after))
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
