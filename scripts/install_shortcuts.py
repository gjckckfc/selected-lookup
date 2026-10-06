# -*- coding: utf-8 -*-
"""建快捷方式和开机自启（命令行版，给从源码跑的开发机用）。

    python scripts/install_shortcuts.py [--no-autostart]

做三件事, 全部只动当前用户、**不需要管理员**:
  1. 生成绿色圆点图标
  2. 桌面 + 开始菜单各建一个快捷方式
  3. 写开机自启（HKCU 的 Run 键, 任务管理器→启动 里能看到）

撤销: python scripts/remove_shortcuts.py

实现在 `src/shortcuts.py` —— 打包后的 exe 用 `选中即查.exe --install` 调的是
同一套代码, 所以两条路不会各写一份、慢慢跑偏。源码版不复制自己（源码本来就在
固定位置上）; 打包版会复制到 %LOCALAPPDATA%\\Programs\\选中即查\\。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import shortcuts  # noqa: E402


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        lines = shortcuts.install(autostart="--no-autostart" not in argv,
                                  copy_self=False)
    except Exception as exc:          # noqa: BLE001 - 出错要让用户看见原因
        print("失败: %s" % exc)
        return 1
    for line in lines:
        print(line)
    print()
    print("撤销: python scripts/remove_shortcuts.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
