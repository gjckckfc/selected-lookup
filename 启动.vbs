' 后台启动查词浮窗, 不显示控制台窗口
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = here
shell.Run "pythonw """ & here & "\src\main.py""", 0, False
