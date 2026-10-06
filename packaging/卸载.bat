@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0选中即查\选中即查.exe" echo 找不到卸载程序。可以手动删除快捷方式, 用户数据不会丢。& pause & exit /b 1
start "" "%~dp0选中即查\选中即查.exe" --uninstall
