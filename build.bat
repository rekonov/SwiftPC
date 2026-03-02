@echo off
setlocal

cd /d "%~dp0"

echo [SwiftPC] Setting up environment...
set PATH=C:\msys64\mingw64\bin;%PATH%

echo [SwiftPC] Checking PyInstaller...
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller not found. Run: pip install pyinstaller
    pause
    exit /b 1
)

echo [SwiftPC] Checking g++...
g++ --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] g++ not found. Install MSYS2 then run: pacman -S mingw-w64-x86_64-gcc
    pause
    exit /b 1
)

echo [SwiftPC] Compiling native helper...
g++ -O2 -o native\swiftpc_native.exe native\swiftpc_native.cpp -lwinmm -mwindows
if errorlevel 1 (
    echo [ERROR] C++ compilation failed.
    pause
    exit /b 1
)
echo [OK] Native helper built.

echo [SwiftPC] Building SwiftPC.exe...
python -m PyInstaller ^
    --onefile ^
    --name SwiftPC ^
    --uac-admin ^
    --collect-all rich ^
    --add-binary "native\swiftpc_native.exe;." ^
    --hidden-import ctypes ^
    --hidden-import ctypes.windll ^
    main.py

if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo.
echo [OK] Build complete: dist\SwiftPC.exe
pause
