@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Executer INSTALLER.cmd en premier.
 pause
 exit /b 1
)
.venv\Scripts\python.exe -m autoshort.cli doctor
pause
