# -*- coding: utf-8 -*-
"""入口。

    python src/main.py

热键:
    Ctrl+Alt+Q   退出
    Ctrl+Alt+P   开启 / 关闭取词

可调项都在托盘图标的右键菜单 -> 设置 里, 存在 settings.json。

同一时间只允许跑一个: 再启动一次不会开出第二个进程, 而是把已经那个的设置窗口
叫到前面来（见 single_instance.py）。

用户数据（设置 / 生词本 / 日志 / 缓存）都放在 %APPDATA%\选中即查 下, 不写在
程序目录里 —— 打包后程序目录是只读的（见 paths.py）。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app import App  # noqa: E402
import paths  # noqa: E402
import single_instance  # noqa: E402
from tray import CALLBACK_MESSAGE, SHOW_SETTINGS_MESSAGE, WINDOW_CLASS  # noqa: E402


def _log_line(path, message):
    """给"第二个实例"用的一行日志: 它没有 App, 所以自己写。"""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except OSError:
        pass


def main(argv=None):
    data_dir = paths.data_root()

    parser = argparse.ArgumentParser(description="选中即查 · 英汉词典浮窗")
    # 词典是只读的, 所以先看新家、没有就用程序目录里那份: 从源码跑的老用户
    # 不用为了升级把 130 MB 复制一遍。
    parser.add_argument("--db", default=str(
        paths.find_data_file(ROOT, "ecdict.sqlite", data_dir)))
    parser.add_argument("--index", default=str(
        paths.find_data_file(ROOT, "inflection.sqlite", data_dir)))
    parser.add_argument("--cache", default=str(data_dir / "cache"),
                        help="翻译 / 语音缓存目录")
    parser.add_argument("--settings", default=str(data_dir / "settings.json"),
                        help="设置文件路径")
    parser.add_argument("--log", default=str(data_dir / "logs" / "app.log"))
    parser.add_argument("--notebook", default=str(data_dir / "vocabulary"),
                        help="生词本目录")
    args = parser.parse_args(argv)

    if not single_instance.acquire():
        told = single_instance.notify_existing(
            WINDOW_CLASS, CALLBACK_MESSAGE, SHOW_SETTINGS_MESSAGE)
        _log_line(args.log, "又启动了一次: 已有实例在跑, %s" % (
            "已把它的设置窗口叫到前面" if told else "但没找到它的窗口"))
        return 0

    # 该建的目录建出来, 顺便把老位置的数据复制过来（只做一次）
    paths.ensure(data_dir)
    paths.migrate(ROOT, data_dir, log=lambda m: _log_line(args.log, m))

    index = args.index
    if not Path(index).exists():
        print("提示: 没找到词形索引 %s, 将只能精确匹配。" % index)
        print("      运行 python scripts/build_index.py 可以生成。")
        index = None

    app = App(
        db_path=args.db,
        index_path=index,
        settings=args.settings,
        log_path=args.log,
        notebook_dir=args.notebook,
        cache_dir=args.cache,
    )
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
