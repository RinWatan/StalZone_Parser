@echo off
if not "%~1"=="stay" (
  cmd /k "%~f0" stay
  exit /b
)
cd /d "%~dp0"
echo.
echo === Сборка STALZONE ===
echo Нужен Python с галочкой Add python.exe to PATH.
echo Собирать на Windows. Готовые exe можно кидать друзьям, Python им не нужен.
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo Python не найден. Поставь с python.org и отметь Add python.exe to PATH.
  echo Потом закрой это окно и открой новое.
  pause
  exit /b 1
)

python -m pip install --upgrade pip pyinstaller httpx pywebview
if errorlevel 1 (
  echo Не удалось поставить PyInstaller
  pause
  exit /b 1
)

echo.
echo --- Окно ---
python -m PyInstaller --noconfirm --onefile --windowed --name STALZONE --hidden-import stalzone_agent --hidden-import httpx --hidden-import httpcore --collect-all webview --distpath dist --workpath build stalzone_gui.py
if errorlevel 1 (
  echo Сборка окна сломалась
  pause
  exit /b 1
)

echo.
echo --- Агент без окна, для командной строки ---
python -m PyInstaller --noconfirm --onefile --console --name stalzone_agent --hidden-import httpx --hidden-import httpcore --distpath dist --workpath build stalzone_agent.py
if errorlevel 1 (
  echo Сборка агента сломалась
  pause
  exit /b 1
)

copy /Y "dist\STALZONE.exe" "STALZONE.exe" >nul
copy /Y "dist\stalzone_agent.exe" "stalzone_agent.exe" >nul
if not exist "для_друзей" mkdir "для_друзей"
copy /Y "STALZONE.exe" "для_друзей\STALZONE.exe" >nul
copy /Y "exbo.json" "для_друзей\exbo.json" >nul

echo.
echo Готово.
echo   STALZONE.exe            окно у тебя
echo   для_друзей\STALZONE.exe и для_друзей\exbo.json
echo Друзьям кидай папку для_друзей: exe и ключ. Базу предметов программа скачает сама.
echo Если антивирус ругнётся, это обычная ложная тревога на PyInstaller.
echo.
pause
