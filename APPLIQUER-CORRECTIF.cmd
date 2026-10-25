@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Extraire le CONTENU de ce ZIP dans votre dossier AutoShort, a cote de LANCER.cmd.
 pause
 exit /b 1
)
.venv\Scripts\python.exe correctif-0.2.3\apply_patch.py --root "%CD%"
if errorlevel 1 (
 pause
 exit /b 1
)
echo Correctif applique. Relance du serveur. Cliquez sur Reprendre pour la production en pause.
call LANCER.cmd
