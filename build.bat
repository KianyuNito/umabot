@echo off
setlocal
cd /d "%~dp0"

echo ==== UmaBot build ====

uv sync || goto :fail

uv run --with pyinstaller python -m PyInstaller --noconfirm --onefile --windowed --name umabot --add-data "fonts;fonts" umabotQT.py || goto :fail

if exist dist\templates rmdir /s /q dist\templates
xcopy /e /i /y templates dist\templates >nul || goto :fail

copy /y skills.db dist\skills.db >nul || goto :fail

del /q umabot.spec 2>nul

echo.
echo Done! Your exe is at dist\umabot.exe
explorer dist
pause
exit /b 0

:fail
echo.
echo Build failed. Scroll up to see the error.
pause
exit /b 1
