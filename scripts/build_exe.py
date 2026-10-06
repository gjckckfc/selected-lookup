# -*- coding: utf-8 -*-
"""打包成免安装的 exe（PyInstaller）。

    python scripts/build_exe.py

产出:  dist\\选中即查\\选中即查.exe      （整个文件夹一起拿走/分发）

为什么是"文件夹版"(onedir) 而不是单文件(onefile):
  这个工具是常驻后台、开机自启的。单文件版每次启动都要把几十 MB 先解压到临时
  目录, 要等 2-5 秒; 文件夹版直接跑。日常体感差很多。

为什么能用 PyInstaller 而不违背"零第三方依赖":
  它是**构建期**工具 —— 只在开发机上打包时用。用户拿到的包里自带 Python 运行时,
  不需要装任何东西, 所以"运行时零第三方依赖"这个承诺不受影响。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from install_shortcuts import make_ico  # noqa: E402  图标就一套画法, 别重复实现

APP_NAME = "选中即查"
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("没装 PyInstaller。先跑:  python -m pip install pyinstaller")
        return 1

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    icon = BUILD_DIR / (APP_NAME + ".ico")
    make_ico(icon)
    print("图标: %s" % icon)

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",                       # 不弹黑色控制台窗口
        "--name", APP_NAME,
        "--icon", str(icon),
        "--paths", str(ROOT / "src"),       # main.py 是按 src/ 组织的, 得告诉它去哪找
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR / "work"),
        "--specpath", str(BUILD_DIR),
        str(ROOT / "src" / "main.py"),
    ]
    print("打包中……（第一次要一两分钟）")
    result = subprocess.run(command)
    if result.returncode != 0:
        print("打包失败。")
        return result.returncode

    exe = DIST_DIR / APP_NAME / (APP_NAME + ".exe")
    if not exe.exists():
        print("打包命令说成功了, 但没找到 %s" % exe)
        return 1
    total = sum(f.stat().st_size for f in (DIST_DIR / APP_NAME).rglob("*") if f.is_file())
    print()
    print("好了: %s" % exe)
    print("整个文件夹一起分发: %s（%.0f MB）" % (DIST_DIR / APP_NAME, total / 1048576))
    print("这个包不需要用户装 Python。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
