# -*- coding: utf-8 -*-
"""建快捷方式和开机自启（只动当前用户, 不需要管理员）。

做三件事:
  1. 生成图标 `%APPDATA%\\选中即查\\选中即查.ico`（绿色圆点, 复用托盘那套画法）
  2. 建两个快捷方式: 桌面 + 开始菜单
  3. 写开机自启: 注册表 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
     —— 放在这里, 任务管理器的"启动"页就能看到它、也能单独关掉

撤销: python scripts/remove_shortcuts.py

为什么用 WScript.Shell 而不是自己拼 .lnk 的二进制: 桌面和开始菜单的真实位置
可能被 OneDrive 之类重定向, 问 Windows 自己("SpecialFolders")最保险; 自己拼
二进制格式等于重新实现一遍微软的私有格式, 没必要。
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import paths  # noqa: E402
from tray import STATE_COLORS, make_icon_data  # noqa: E402

APP_NAME = "选中即查"
DESCRIPTION = "选中即查 · 英汉词典浮窗"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

CREATE_NO_WINDOW = 0x08000000


def find_pythonw():
    """找 pythonw.exe: 用它启动才不弹黑色控制台窗口。"""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def make_ico(path, sizes=(16, 32, 48), rgb=None):
    """生成 .ico。每个尺寸的图画法和托盘图标完全一样, 不重复实现。"""
    rgb = rgb or STATE_COLORS["on"]
    images = [(size, make_icon_data(rgb, size)) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for size, data in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0,
                               1, 32, len(data), offset)
        offset += len(data)
    path.write_bytes(header + entries + b"".join(data for _, data in images))


def _vbs(text):
    """把一段文字变成 VBS 里的字符串字面量。"""
    return '"%s"' % str(text).replace('"', '""')


def _run_vbs(script, report):
    """跑一段临时 VBS, 返回它写进 report 文件的行。

    两个坑都踩过:
      - 必须用 cscript 而不是 wscript: wscript 下 WScript.Echo 会弹一个**模态
        对话框**, 没人点它就一直卡着。`//B` 是批处理模式, 出错也不弹框。
      - 也不能靠 Echo 读结果: 加了 CREATE_NO_WINDOW 之后它没有控制台可写,
        输出会凭空消失。所以让 VBS 把结果写进一个临时文件, 我们读那个文件。
    VBS 源文件写成 UTF-16, WSH 才认里面的中文。
    """
    tmp = Path(tempfile.gettempdir()) / ("lookup_setup_%d.vbs" % os.getpid())
    tmp.write_text(script, encoding="utf-16")
    try:
        proc = subprocess.run(["cscript", "//nologo", "//B", str(tmp)],
                              capture_output=True, timeout=30,
                              creationflags=CREATE_NO_WINDOW)
        if proc.returncode != 0:
            detail = proc.stderr.decode("mbcs", "replace").strip()
            raise RuntimeError("VBS 失败（代码 %d）: %s" % (proc.returncode, detail))
        if not report.exists():
            return []
        return [line for line in report.read_text(encoding="utf-16").splitlines() if line.strip()]
    finally:
        for path in (tmp, report):
            try:
                path.unlink()
            except OSError:
                pass


def create_shortcuts(target, arguments, workdir, icon, report):
    """桌面 + 开始菜单各建一个快捷方式。放哪儿交给 Windows 自己说。"""
    script = "\n".join([
        'Set shell = CreateObject("WScript.Shell")',
        'Set fso = CreateObject("Scripting.FileSystemObject")',
        'Set out = fso.CreateTextFile(%s, True, True)' % _vbs(report),
        'For Each folder In Array(shell.SpecialFolders("Desktop"), '
        'shell.SpecialFolders("Programs"))',
        '  path = folder & "\\%s.lnk"' % APP_NAME,
        '  Set lnk = shell.CreateShortcut(path)',
        '  lnk.TargetPath = %s' % _vbs(target),
        '  lnk.Arguments = %s' % _vbs(arguments),
        '  lnk.WorkingDirectory = %s' % _vbs(workdir),
        '  lnk.IconLocation = %s' % _vbs(icon),
        '  lnk.Description = %s' % _vbs(DESCRIPTION),
        '  lnk.Save',
        '  If fso.FileExists(path) Then',
        '    out.WriteLine "OK " & path',
        '  Else',
        '    out.WriteLine "NO " & path',
        '  End If',
        'Next',
        'out.Close',
        '',
    ])
    return _run_vbs(script, report)


def set_autostart(command):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    want_autostart = "--no-autostart" not in argv

    data_dir = paths.ensure()
    script = ROOT / "src" / "main.py"
    pythonw = find_pythonw()
    icon = data_dir / (APP_NAME + ".ico")

    if not script.exists():
        print("找不到 %s, 这个脚本得放在项目里的 scripts\\ 下跑。" % script)
        return 1

    make_ico(icon)
    print("图标     : %s" % icon)

    report = Path(tempfile.gettempdir()) / ("lookup_shortcuts_%d.txt" % os.getpid())
    created = create_shortcuts(
        target=pythonw,
        arguments='"%s"' % script,
        workdir=ROOT,
        icon="%s,0" % icon,
        report=report,
    )
    ok = 0
    for line in created:
        flag, _, path = line.partition(" ")
        ok += flag == "OK"
        print("快捷方式 : %s %s" % ("已建立" if flag == "OK" else "**失败**", path))
    if ok != 2:
        print("警告: 只成功了 %d 个, 应该 2 个（桌面 + 开始菜单）" % ok)

    if want_autostart:
        set_autostart('"%s" "%s"' % (pythonw, script))
        print("开机自启 : 已写入 HKCU\\...\\Run 的「%s」" % APP_NAME)
        print("           （任务管理器 → 启动 里能看到，也能单独关掉）")
    else:
        print("开机自启 : 按参数要求跳过")

    print()
    print("完成。以后开机它自己就起来了；要撤销跑:")
    print("    python scripts/remove_shortcuts.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
