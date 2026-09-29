@echo off
setlocal
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --windowed --name STALZONE-overlay --hidden-import stalzone_agent --hidden-import stalzone_overlay --distpath dist --workpath build stalzone_gui.py
if errorlevel 1 exit /b 1
echo Built: dist\STALZONE-overlay.exe
echo Keep your local exbo.json next to the EXE. It is not bundled.
