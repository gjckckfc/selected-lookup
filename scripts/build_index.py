# -*- coding: utf-8 -*-
"""构建词形还原索引（命令行版）。

    python scripts/build_index.py

ECDICT 只在每个词条上记录"它自己的各种变形"，没有反向索引。
这里把它翻转成 变形 -> 原形 的表，用于 ran -> run、studies -> study 这类查询。

索引写在**词典旁边**（先找用户数据目录，再找程序目录）。
实现同样在 `src/dictpack.py`，图形向导建索引走的是同一套。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import dictpack  # noqa: E402


def main() -> int:
    source_db = dictpack.find_existing_db(ROOT)
    if source_db is None:
        print("找不到词库。先运行: python scripts/fetch_dict.py")
        return 1

    started = time.time()
    print("读取词库: %s" % source_db)
    try:
        index_db, count = dictpack.build_index(source_db)
    except Exception as exc:
        print("失败: %s" % exc)
        return 1
    size_mb = index_db.stat().st_size / 1048576
    print("  唯一变形 %s 个" % format(count, ","))
    print("完成: %s  (%.1f MB)" % (index_db, size_mb))
    print("总用时 %.1fs" % (time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
