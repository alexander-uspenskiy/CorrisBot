@echo off
set PATH=%PATH%;%APPDATA%\npm
cd /d "C:\CorrisBot\Gateways\Telegram"
py tg_codex_gateway.py
pause
