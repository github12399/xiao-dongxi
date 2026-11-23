@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting Xiao-Dong-Xi ...
python xiao_dongxi.py
if not errorlevel 1 goto :eof
py xiao_dongxi.py
if not errorlevel 1 goto :eof
pause
