@echo off
rem Runs the tests, then builds dist\Modocracy.exe (needs Python + PyInstaller).
setlocal
cd /d "%~dp0"

echo [1/2] Running tests...
python -m unittest discover -s tests -t . || goto :fail

echo [2/2] Building exe...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name Modocracy ^
  --icon "%~dp0assets\icon.ico" ^
  --version-file "%~dp0assets\version_info.txt" ^
  --add-data "%~dp0hd2mm\web;hd2mm\web" ^
  --distpath "%~dp0dist" --workpath "%~dp0build\pyinstaller" --specpath "%~dp0build" ^
  "%~dp0launcher.py" || goto :fail

echo.
echo Done: %~dp0dist\Modocracy.exe
exit /b 0

:fail
echo.
echo BUILD FAILED
exit /b 1
