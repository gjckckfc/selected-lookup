# -*- coding: utf-8 -*-
"""下载并校验 ECDICT 词典包（命令行版）。

    python scripts/fetch_dict.py

已存在且校验通过时不会重复下载（新旧位置都会找）。
真正的实现在 `src/dictpack.py` —— 第一次运行时的图形向导用的是同一套,
别在这儿再写一遍。索引单独用 scripts/build_index.py 建。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import dictpack  # noqa: E402


def progress(stage, done, total):
    if stage == "download" and total:
        print("\r  下载中 %3d%%  %6.1f / %.1f MB"
              % (done * 100 // total, done / 1048576, total / 1048576), end="")
        if done >= total:
            print()
    elif stage == "verify" and total and done >= total:
        print("  下载包 SHA-256 校验通过")


def main() -> int:
    print("目标目录: %s" % dictpack.data_dir())
    try:
        db_path, note = dictpack.ensure_dictionary(ROOT, on_progress=progress)
    except Exception as exc:
        print("\n失败: %s" % exc)
        return 1
    print("词典已就绪: %s" % db_path)
    print("  %s" % note)
    print("下一步: python scripts/build_index.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
