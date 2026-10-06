# -*- coding: utf-8 -*-
"""用户数据的落脚点: 全部集中在 %APPDATA%\\选中即查\\ 下面。

为什么不放在程序目录:
  打包后程序装在 C:\\Program Files\\..., 那个目录普通程序**没有写权限**。
  设置、生词本、日志、缓存如果写在程序目录里, 会静默失败 —— 用户改了设置没保存、
  生词本写不进去, 而且一点报错都看不见。

布局:

    %APPDATA%\\选中即查\\
        settings.json     设置（含 API 密钥）
        vocabulary\\       生词本
        logs\\             日志
        cache\\            翻译缓存 + 语音缓存
        data\\             词典（第一次运行时下载）

程序目录里只留代码, 只读。
词典是**只读**打开的(`mode=ro`), 所以"直接读程序目录里那份"完全没问题 ——
这样从源码跑起来的老用户不用为了用新版去复制 130 MB。查找顺序是先新家、再程序
目录, 见 `find_data_file`。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_FOLDER = "选中即查"

# 需要建好的子目录
SUBDIRS = ("logs", "cache", "data", "vocabulary")


def data_root():
    """用户数据根目录: %APPDATA%\\选中即查。"""
    base = os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_FOLDER


def ensure(root=None):
    """把该有的目录都建出来。返回根目录。"""
    root = Path(root) if root else data_root()
    for name in SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def find_data_file(project_root, name, root=None):
    """找词典这类只读、两处都可能有的文件: 先新家, 再程序目录。

    都没找到时返回"将来会下载到哪里"(新家的 data\\)。
    """
    root = Path(root) if root else data_root()
    for candidate in (root / "data" / name, Path(project_root) / "data" / name):
        if candidate.exists():
            return candidate
    return root / "data" / name


def _is_empty(path):
    if not path.exists():
        return True
    if path.is_dir():
        return not any(path.iterdir())
    return False


def migrate(project_root, root=None, log=None):
    """第一次跑新版时, 把老位置的数据**复制**到新家, 原文件留着当备份。

    搬: 设置、生词本、日志、翻译/语音缓存（缓存也搬是为了不重新花钱翻译、
    不重新联网合成语音）。
    不搬: 词典（只读, 直接就地用; 130 MB 复制一份没意义）。
    """
    root = Path(root) if root else data_root()
    project_root = Path(project_root)
    moved = []

    for rel in ("settings.json", "logs/app.log"):
        src = project_root / rel
        dst = root / rel
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            moved.append(rel)

    src = project_root / "vocabulary"
    dst = root / "vocabulary"
    if src.is_dir() and _is_empty(dst):
        shutil.copytree(src, dst, dirs_exist_ok=True)
        moved.append("vocabulary/")

    # 缓存的老位置在 程序目录\data\ 下, 新位置在 用户目录\cache\ 下
    for rel in ("translate_cache.sqlite", "voice_cache"):
        src = project_root / "data" / rel
        dst = root / "cache" / rel
        if not src.exists() or dst.exists():
            continue
        try:
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            moved.append("cache/" + rel)
        except OSError as exc:
            # 缓存搬不动不算事, 大不了重新生成
            if log:
                log("缓存 %s 没搬成（不影响使用）: %s" % (rel, exc))

    if moved and log:
        log("已把老位置的数据复制到 %s: %s（原文件保留当备份）"
            % (root, "、".join(moved)))
    return moved
