@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting Xiao-Dong-Xi ...

rem Prefer the local Python 3.11 (has Pillow, stable tkinter)
set "XDPY=C:\Users\25549\AppData\Local\Programs\Python\Python311\python.exe"
if exist "%XDPY%" goto :run

rem Fall back to the Windows py launcher
set "XDPY="
where py >nul 2>nul
if not errorlevel 1 set "XDPY=py"
if defined XDPY goto :run

rem Last resort: python.exe on PATH
set "XDPY="
where python.exe >nul 2>nul
if not errorlevel 1 set "XDPY=python.exe"
if defined XDPY goto :run

echo Python not found. Install Python 3.8+ and tick "Add to PATH".
pause
goto :eof

:run
"%XDPY%" xiao_dongxi.py
if not errorlevel 1 goto :eof
echo.
echo Program exited with an error. Check messages above.
pause
