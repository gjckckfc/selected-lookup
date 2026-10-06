# -*- coding: utf-8 -*-
"""撤销 scripts/install_shortcuts.py 做的那几件事。

    python scripts/remove_shortcuts.py

删掉: 桌面快捷方式、开始菜单快捷方式、开机自启、以及
%LOCALAPPDATA%\\Programs\\选中即查 下的程序文件（如果装过的话）。

**不动用户数据** —— 生词本、设置、缓存、词典都留在 %APPDATA%\\选中即查 下。
实现同样在 `src/shortcuts.py`, 和 exe 的 `--uninstall` 共用。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import shortcuts  # noqa: E402


def main() -> int:
    for line in shortcuts.uninstall():
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
