# -*- coding: utf-8 -*-
"""入口。

    python src/main.py

热键:
    Ctrl+Alt+Q   退出
    Ctrl+Alt+P   暂停 / 恢复取词
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app import App  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="选中即查 · 英汉词典浮窗")
    parser.add_argument("--db", default=str(ROOT / "data" / "ecdict.sqlite"))
    parser.add_argument("--index", default=str(ROOT / "data" / "inflection.sqlite"))
    parser.add_argument("--drag", type=int, default=6, help="判定为拖选的像素阈值")
    parser.add_argument("--hide-after", type=float, default=9.0, help="浮窗停留秒数")
    parser.add_argument("--log", default=str(ROOT / "logs" / "app.log"))
    args = parser.parse_args(argv)

    index = args.index
    if not Path(index).exists():
        print("提示: 没找到词形索引 %s, 将只能精确匹配。" % index)
        print("      运行 python scripts/build_index.py 可以生成。")
        index = None

    app = App(
        db_path=args.db,
        index_path=index,
        drag_threshold=args.drag,
        hide_after=args.hide_after,
        log_path=args.log,
    )
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
