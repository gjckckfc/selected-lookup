# -*- coding: utf-8 -*-
"""打包成免安装的 exe, 并整理出一个能直接发出去的发布包。

    python scripts/build_exe.py

产出:
    dist\\选中即查\\                 ← PyInstaller 的产物（程序本体）
    dist\\选中即查-<版本>\\          ← 发布包：程序 + 安装.bat + 卸载.bat + 说明.txt
    dist\\选中即查-<版本>.zip        ← 上面那个文件夹的压缩包，直接当 Release 附件

为什么是"文件夹版"(onedir) 而不是单文件(onefile):
  这个工具常驻后台、开机自启。单文件版每次启动都要先把几十 MB 解压到临时目录,
  要等 2-5 秒; 文件夹版直接跑。日常体感差很多。

为什么能用 PyInstaller 而不违背"零第三方依赖":
  它是**构建期**工具, 只在开发机上打包时用。用户拿到的包里自带 Python 运行时,
  不需要装任何东西。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import appinfo  # noqa: E402
from shortcuts import make_ico  # noqa: E402  图标就一套画法, 别重复实现

BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
PACKAGING_DIR = ROOT / "packaging"

APP_NAME = appinfo.APP_NAME
VERSION = appinfo.VERSION


def version_tuple(text):
    """'1.0' -> (1, 0, 0, 0)。Windows 的版本号必须是四段。"""
    parts = [int(p) for p in str(text).split(".") if p.isdigit()][:4]
    parts += [0] * (4 - len(parts))
    return tuple(parts)


def write_version_file(path):
    """给 exe 写一份版本信息 —— 右键属性里就能看到版本号, 报 bug 时问得出口。

    这是 PyInstaller 规定的格式（`--version-file` 收的文件, 内容是可 eval 的
    Python 字面量）。语言 2052 = 中文(简体), 代码页 1200 = Unicode。
    """
    ver = version_tuple(VERSION)
    text = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver},
    prodvers={ver},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404B0', [
        StringStruct('CompanyName', '{company}'),
        StringStruct('FileDescription', '{desc}'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', '{name}'),
        StringStruct('LegalCopyright', 'Copyright (c) 2026 {company}'),
        StringStruct('OriginalFilename', '{name}.exe'),
        StringStruct('ProductName', '{name}'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""".format(ver=ver, version=VERSION, name=APP_NAME, desc=appinfo.DESCRIPTION,
           company="gjckckfc")
    path.write_text(text, encoding="utf-8")
    return path


def build_exe():
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    icon = BUILD_DIR / (APP_NAME + ".ico")
    make_ico(icon)
    print("图标: %s" % icon)
    version_file = write_version_file(BUILD_DIR / "version_info.txt")

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",                        # 不弹黑色控制台窗口
        "--name", APP_NAME,
        "--icon", str(icon),
        "--version-file", str(version_file),
        "--paths", str(ROOT / "src"),        # main.py 是按 src/ 组织的, 得告诉它去哪找
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR / "work"),
        "--specpath", str(BUILD_DIR),
        str(ROOT / "src" / "main.py"),
    ]
    print("打包中……（第一次要一两分钟）")
    result = subprocess.run(command)
    if result.returncode != 0:
        raise RuntimeError("PyInstaller 失败（代码 %d）" % result.returncode)
    exe = DIST_DIR / APP_NAME / (APP_NAME + ".exe")
    if not exe.exists():
        raise RuntimeError("打包命令说成功了, 但没找到 %s" % exe)
    return exe


def make_release():
    """把程序、安装脚本、说明凑成一个可以直接发给别人的文件夹。"""
    release = DIST_DIR / ("%s-%s" % (APP_NAME, VERSION))
    if release.exists():
        shutil.rmtree(release)
    release.mkdir(parents=True)
    shutil.copytree(DIST_DIR / APP_NAME, release / APP_NAME)

    for name in ("安装.bat", "卸载.bat"):
        source = PACKAGING_DIR / name
        if source.exists():
            shutil.copy2(source, release / name)
        else:
            print("  ! 少了 %s，发布包里会没有它" % source)

    # 许可声明必须随包分发（NOTICE.md 里自己写了这一条；MIT 和 CC BY-SA
    # 都要求把许可随副本一起给出去）
    for name in ("LICENSE", "NOTICE.md"):
        source = ROOT / name
        if source.exists():
            shutil.copy2(source, release / name)
        else:
            print("  ! 少了 %s，发布包里会没有它" % source)

    readme = release / "说明.txt"
    readme.write_text(
        "%s %s\n%s\n\n"
        "怎么用:\n"
        "  1. 双击「安装.bat」——它会建好桌面和开始菜单的快捷方式，\n"
        "     并设为开机自启（只动当前用户，不需要管理员权限）\n"
        "  2. 双击桌面上的「%s」就能用\n"
        "  3. 第一次运行会自动下载词典（约 52 MB，只下载一次，带进度条）\n\n"
        "不想用了:\n"
        "  双击「卸载.bat」——快捷方式和开机自启都会被清掉，\n"
        "  **你的生词本和设置都会留着**。\n\n"
        "你的数据在（想备份就复制这个文件夹）:\n"
        "  %%APPDATA%%\\%s\n"
        "\n"
        "关于第三方:\n"
        "  本程序只写了把各种能力串起来的那层逻辑, 里面用到的这些东西都不是本项目做的:\n"
        "    · 词典数据 —— 开源项目 ECDICT（MIT），另有 2 张词表来自\n"
        "      NGSL/NAWL/BSL/TOEIC（CC BY-SA 4.0）。程序第一次运行时联网下载, 不在安装包里。\n"
        "    · 神经网络语音 —— 微软的。让普通程序能用上它的是社区的\n"
        "      NaturalVoiceSAPIAdapter（MIT，作者 @gexgd0419），需要你自己安装,\n"
        "      本安装包不包含也不分发它。\n"
        "    · 整句翻译 —— 调用 DeepSeek 的在线服务, 用你自己申请的密钥,\n"
        "      跟本项目没有任何合作关系。\n"
        "  详细署名和许可全文见同目录的 NOTICE.md 和 LICENSE。\n"
        % (APP_NAME, VERSION, appinfo.TAGLINE, APP_NAME, APP_NAME),
        encoding="utf-8")

    zip_base = DIST_DIR / ("%s-%s" % (APP_NAME, VERSION))
    # make_archive 返回的是它真正写出来的文件名 —— 别自己拼（"1.0" 里的 .0
    # 会被 with_suffix 当成后缀吃掉，之前就踩过）
    zip_file = shutil.make_archive(str(zip_base), "zip", DIST_DIR, release.name)
    return release, Path(zip_file)


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("没装 PyInstaller。先跑:  python -m pip install pyinstaller")
        return 1

    try:
        exe = build_exe()
    except Exception as exc:          # noqa: BLE001 - 打包失败要说清原因
        print("打包失败: %s" % exc)
        return 1
    print("程序: %s" % exe)

    release, zip_path = make_release()
    size_mb = sum(f.stat().st_size for f in release.rglob("*") if f.is_file()) / 1048576
    print()
    print("发布包: %s（%.0f MB）" % (release, size_mb))
    print("压缩包: %s" % zip_path)
    print("这个包不需要用户装 Python；把压缩包当 Release 附件发出去即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
