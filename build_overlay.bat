@echo off
setlocal
cd /d "%~dp0"
python -m pip install pyinstaller pywebview httpx
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --onefile --windowed --name STALZONE-map-overlay --hidden-import stalzone_agent --hidden-import stalzone_overlay --hidden-import httpx --hidden-import httpcore --collect-all webview --distpath dist --workpath build stalzone_gui.py
if errorlevel 1 exit /b 1
echo Built: dist\STALZONE-map-overlay.exe
echo Keep your local exbo.json next to the EXE. It is not bundled.
