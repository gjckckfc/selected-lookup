# -*- coding: utf-8 -*-
"""撤销 scripts/install_shortcuts.py 做的那三件事。

删掉: 桌面快捷方式、开始菜单快捷方式、开机自启。
**不动用户数据** —— 生词本、设置、缓存、词典一律保留（要删自己去
%APPDATA%\\选中即查 下删）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import paths  # noqa: E402

APP_NAME = "选中即查"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

CREATE_NO_WINDOW = 0x08000000


def _vbs(text):
    return '"%s"' % str(text).replace('"', '""')


def _run_vbs(script, report):
    """同 install_shortcuts: 用 cscript(//B) 且把结果写文件读回来。"""
    tmp = Path(tempfile.gettempdir()) / ("lookup_remove_%d.vbs" % os.getpid())
    tmp.write_text(script, encoding="utf-16")
    try:
        proc = subprocess.run(["cscript", "//nologo", "//B", str(tmp)],
                              capture_output=True, timeout=30,
                              creationflags=CREATE_NO_WINDOW)
        if not report.exists():
            return []
        return [line for line in report.read_text(encoding="utf-16").splitlines() if line.strip()]
    finally:
        for path in (tmp, report):
            try:
                path.unlink()
            except OSError:
                pass


def remove_shortcuts(report):
    """删桌面和开始菜单里的快捷方式。不存在的就跳过。"""
    script = "\n".join([
        'Set shell = CreateObject("WScript.Shell")',
        'Set fso = CreateObject("Scripting.FileSystemObject")',
        'Set out = fso.CreateTextFile(%s, True, True)' % _vbs(report),
        'For Each folder In Array(shell.SpecialFolders("Desktop"), '
        'shell.SpecialFolders("Programs"))',
        '  path = folder & "\\%s.lnk"' % APP_NAME,
        '  If fso.FileExists(path) Then',
        '    fso.DeleteFile path, True',
        '    If fso.FileExists(path) Then',
        '      out.WriteLine "NO " & path',
        '    Else',
        '      out.WriteLine "OK " & path',
        '    End If',
        '  Else',
        '    out.WriteLine "SKIP " & path',
        '  End If',
        'Next',
        'out.Close',
        '',
    ])
    return _run_vbs(script, report)


def clear_autostart():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def main(argv=None):
    report = Path(tempfile.gettempdir()) / ("lookup_remove_%d.txt" % os.getpid())
    for line in remove_shortcuts(report):
        flag, _, path = line.partition(" ")
        word = {"OK": "已删除", "SKIP": "本来就没有", "NO": "**删不掉**"}.get(flag, flag)
        print("快捷方式 : %s %s" % (word, path))
    if clear_autostart():
        print("开机自启 : 已移除")
    else:
        print("开机自启 : 本来就没有")
    icon = paths.data_root() / (APP_NAME + ".ico")
    if icon.exists():
        try:
            icon.unlink()
            print("图标     : 已删除 %s" % icon)
        except OSError as exc:
            print("图标     : 删不掉(%s), 不影响使用" % exc)
    print()
    print("用户数据保留在: %s" % paths.data_root())
    return 0


if __name__ == "__main__":
    sys.exit(main())
