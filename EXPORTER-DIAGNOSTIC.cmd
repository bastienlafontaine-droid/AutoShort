@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe correctif-0.2.1\export_diagnostic.py
pause
