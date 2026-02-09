@echo off
set PATH=%PATH%;%APPDATA%\npm
cd /d "C:\CorrisBot"
py tg_codex_gateway.py
pause
