@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0选中即查\选中即查.exe" echo 找不到程序文件, 请确认压缩包解压完整。& pause & exit /b 1
start "" "%~dp0选中即查\选中即查.exe" --install
