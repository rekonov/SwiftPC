@echo off
pyinstaller --onefile --name SwiftPC main.py
echo Build complete: dist\SwiftPC.exe
pause
