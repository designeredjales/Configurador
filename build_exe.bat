@echo off
REM Gera ConfiguradorExterno.exe (arquivo unico, sem console), como o executavel original
python -m pip install -r requirements-build.txt
python -m PyInstaller --onefile --windowed --name ConfiguradorExterno editor_promob.py
echo.
echo Executavel gerado em dist\ConfiguradorExterno.exe
