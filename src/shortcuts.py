# -*- coding: utf-8 -*-
"""快捷方式、开机自启、安装 / 卸载 —— 一处实现。

入口:
  - `scripts/install_shortcuts.py` / `remove_shortcuts.py`: 开发机上用（源码版）
  - 打包后的 exe 自己: `选中即查.exe --install` / `--uninstall`

安装做四件事, 全部只动当前用户、**不需要管理员**:
  1. 把程序复制到 %LOCALAPPDATA%\\Programs\\选中即查\\（只有打包版才需要;
     源码版跳过, 因为源码本来就在固定位置上）
  2. 生成绿色圆点图标
  3. 桌面 + 开始菜单各建一个快捷方式
  4. 写开机自启（HKCU 的 Run 键, 任务管理器→启动 里看得见、能单独关）

为什么要复制到固定位置: 用户可能把下载的文件夹解压到任意地方, 之后挪了、删了、
忘了 —— 快捷方式就全断了。装到固定位置之后那条路径是稳的。

**数据不在这里**: 生词本、设置、词典都在 %APPDATA%\\选中即查\\ 下（见 paths.py）,
所以卸载/重装/升级都不会碰到它们。

两个踩过的坑（改这段代码前先看一眼）:
  - 别用 wscript 跑 VBS: 它下面 `WScript.Echo` 会弹模态框把人卡死。用
    `cscript //nologo //B`。
  - 加了 CREATE_NO_WINDOW 之后 cscript 没有控制台可写, Echo 输出会消失;
    所以让 VBS 把结果写进临时文件, Python 再读回来。
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import appinfo
import paths
from tray import STATE_COLORS, make_icon_data

APP_NAME = appinfo.APP_NAME
DESCRIPTION = appinfo.DESCRIPTION
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
CREATE_NO_WINDOW = 0x08000000


def install_dir():
    """打包版的固定安装位置（源码版用不到）。"""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / APP_NAME


def program_root():
    """程序所在目录: 打包后是 exe 那个文件夹, 源码版是项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def launch_target():
    """返回 (要启动的可执行文件, 参数)。快捷方式和自启都指向它。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable), ""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    return exe, '"%s"' % (program_root() / "src" / "main.py")


def make_ico(path, sizes=(16, 32, 48), rgb=None):
    """生成 .ico。图画法和托盘图标完全一样, 不重复实现。"""
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


# ----------------------------------------------------------------------
# 跑一段临时 VBS（建/删快捷方式）

def _vbs(text):
    return '"%s"' % str(text).replace('"', '""')


def _run_vbs(script, report):
    tmp = Path(tempfile.gettempdir()) / ("lookup_shell_%d.vbs" % os.getpid())
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
        text = report.read_text(encoding="utf-16")
        return [line for line in text.splitlines() if line.strip()]
    finally:
        for path in (tmp, report):
            try:
                path.unlink()
            except OSError:
                pass


def create_shortcuts(target, arguments, workdir, icon, report):
    """桌面 + 开始菜单各建一个。放哪儿交给 Windows 自己说。"""
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


def remove_shortcut_files(report):
    """删桌面和开始菜单里的快捷方式。不存在的跳过。"""
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


# ----------------------------------------------------------------------

def set_autostart(command):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)


def clear_autostart():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
        return True
    except OSError:
        return False


def _report_path(tag):
    return Path(tempfile.gettempdir()) / ("lookup_%s_%d.txt" % (tag, os.getpid()))


# ----------------------------------------------------------------------
# 安装 / 卸载

def _autostart_command(exe, arguments):
    command = '"%s"' % exe
    if arguments:
        command += " " + arguments
    return command


def install(autostart=True, copy_self=None, log=None):
    """建快捷方式 + 开机自启。返回给人看的说明（每行一条）。

    copy_self: 要不要把自己复制到固定安装位置。
               默认规则——打包版复制（用户可能把下载的文件夹删了），源码版不复制。
    """
    log = log or (lambda message: None)
    root = program_root()
    data_dir = paths.ensure()
    icon = data_dir / (APP_NAME + ".ico")
    make_ico(icon)
    notes = []

    if copy_self is None:
        copy_self = bool(getattr(sys, "frozen", False))

    if copy_self:
        target_dir = install_dir()
        if root.resolve() != target_dir.resolve():
            if target_dir.exists():
                shutil.rmtree(target_dir)      # 旧的先清掉, 免得留下过期文件
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(root, target_dir)
            log("安装: 程序复制到 %s" % target_dir)
        exe = target_dir / (APP_NAME + ".exe")
        arguments = ""
        workdir = target_dir
        notes.append("程序已安装到 %s" % target_dir)
    else:
        exe, arguments = launch_target()
        workdir = root
        notes.append("程序就在 %s（源码版，不复制）" % root)

    report = _report_path("install")
    for line in create_shortcuts(exe, arguments, workdir, "%s,0" % icon, report):
        flag, _, path = line.partition(" ")
        notes.append("%s %s" % ("快捷方式:" if flag == "OK" else "快捷方式失败:", path))
        log("安装: 快捷方式 %s %s" % (flag, path))

    if autostart:
        set_autostart(_autostart_command(exe, arguments))
        notes.append("已设为开机自启（任务管理器 → 启动 里能看到，也能关掉）")
        log("安装: 写入开机自启")
    else:
        notes.append("按要求跳过了开机自启")
    return notes


def _schedule_self_delete(folder):
    """卸载时如果正跑在安装目录里, 自己是删不掉自己的 —— 让 PowerShell 等本进程退出再删。

    删之前严格核对路径: 必须是 %LOCALAPPDATA%\\Programs\\选中即查 本身,
    多一层少一层都不动手。

    要**等本进程退出**再删: 卸载完会弹个"已卸载"的框, 框还开着的时候 exe 是被
    锁住的, 直接删只会留下半个文件夹。
    """
    target = Path(folder).resolve()
    expected = install_dir().resolve()
    if target != expected or target.name != APP_NAME:
        return False
    quoted = str(target).replace("'", "''")
    script = ("Wait-Process -Id %d -ErrorAction SilentlyContinue; "
              "Start-Sleep -Seconds 1; "
              "Remove-Item -LiteralPath '%s' -Recurse -Force -ErrorAction SilentlyContinue"
              % (os.getpid(), quoted))
    subprocess.Popen(["powershell", "-NoProfile", "-Command", script],
                     creationflags=CREATE_NO_WINDOW)
    return True


def uninstall(remove_program=True, log=None):
    """撤销安装。**不动用户数据**。返回给人看的说明（每行一条）。"""
    log = log or (lambda message: None)
    notes = []

    report = _report_path("uninstall")
    for line in remove_shortcut_files(report):
        flag, _, path = line.partition(" ")
        word = {"OK": "已删除", "SKIP": "本来就没有", "NO": "删不掉"}.get(flag, flag)
        notes.append("快捷方式 %s: %s" % (word, path))
        log("卸载: 快捷方式 %s %s" % (flag, path))

    if clear_autostart():
        notes.append("已取消开机自启")
        log("卸载: 取消开机自启")
    else:
        notes.append("开机自启本来就没有")

    icon = paths.data_root() / (APP_NAME + ".ico")
    if icon.exists():
        try:
            icon.unlink()
        except OSError:
            pass

    if remove_program:
        target_dir = install_dir()
        if target_dir.exists():
            running_here = program_root().resolve() == target_dir.resolve()
            if running_here:
                if _schedule_self_delete(target_dir):
                    notes.append("程序文件将在本窗口关闭后自动删除")
                else:
                    notes.append("程序文件夹需要你自己删: %s" % target_dir)
            else:
                try:
                    shutil.rmtree(target_dir)
                    notes.append("程序文件已删除: %s" % target_dir)
                    log("卸载: 删除 %s" % target_dir)
                except OSError as exc:
                    notes.append("程序文件夹删不掉（可能还在运行）: %s" % exc)

    notes.append("生词本、设置、词典都保留在: %s" % paths.data_root())
    return notes
