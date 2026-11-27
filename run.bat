@echo off
setlocal
cd /d "%~dp0"

uv run python umabotQT.py
if errorlevel 1 pause
