<div align="center">

# SwiftPC

![Version](https://img.shields.io/badge/version-1.2.0-blue?style=flat-square)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4?style=flat-square&logo=windows)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![C++](https://img.shields.io/badge/C%2B%2B-native%20helper-00599C?style=flat-square&logo=cplusplus)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

**Windows PC optimizer for gaming.** Kills background bloat, stops unnecessary services, and tweaks system settings — then restores everything when you're done.

</div>

---

## What it does

One command puts your PC into gaming mode. Another brings everything back.

| Step | Action |
|------|--------|
| 1 | Kills background processes — OneDrive, Teams, Spotify, Discord, etc. |
| 2 | Stops non-essential services — Superfetch, Telemetry, Windows Search, Windows Update, etc. |
| 3 | Switches power plan to High Performance |
| 4 | Flushes DNS cache and standby RAM list (native C++) |
| 5 | Disables Nagle's algorithm and network throttling for lower latency |
| 6 | Sets GPU priority to 8 and enables Game Mode |
| 7 | Sets visual effects to Best Performance mode |
| 8 | Sets timer resolution to 1ms via native C++ helper (held while app runs) |
| 9 | Cleans up TEMP and Windows\Temp directories |
| 10 | Disables CPU core parking — all cores stay active |
| 11 | Prints a summary table of all applied optimizations |

All changes are **fully reversible** — pressing Enter or closing the app restores the original state. State is saved to `.optimizer-state.json` so `--restore` works even if the app was closed unexpectedly.

---

## Requirements

- Windows 10 or 11
- Python 3.10+
- Administrator privileges (auto-elevated by `SwiftPC.exe` — no need to right-click)

---

## Installation

```bash
pip install -r requirements.txt
```

---

## Usage

**Standard — double-click:**

```
SwiftPC.exe
```

Requests elevation automatically, optimizes, shows "Gaming mode ACTIVE", waits for Enter, then restores.

**Scripting / automation (optimize and exit immediately):**

```bash
python main.py --no-wait
```

**Restore manually (if terminal was closed):**

```bash
python main.py --restore
```

**Check current status:**

```bash
python main.py --status
```

**Preview without making changes:**

```bash
python main.py --dry-run
```

---

## Native C++ helper

SwiftPC bundles `swiftpc_native.exe`, a small C++ helper for operations that require direct Win32 APIs:

- `timeBeginPeriod(1)` — real 1ms timer resolution, held for the duration of the session
- `NtSetSystemInformation` — standby RAM flush

These cannot be done persistently from Python alone.

**Commands:**

```
swiftpc_native.exe flush-ram
swiftpc_native.exe keep-timer
swiftpc_native.exe stop-timer
```

---

## Build

Requires PyInstaller and MinGW `g++` in PATH.

```bash
build.bat
```

`build.bat` compiles the C++ helper first, then packages the Python app with PyInstaller.

Output: `dist\SwiftPC.exe`

**Compile C++ helper manually:**

```bash
PATH=/c/msys64/mingw64/bin:$PATH g++ -o native/swiftpc_native.exe native/swiftpc_native.cpp
```

---

## Tech stack

| Component | Technology |
|-----------|-----------|
| Main app | Python 3.10 |
| Terminal UI | Rich |
| Packaging | PyInstaller |
| Native helper | C++ (MinGW g++) |
| Win32 APIs | `timeBeginPeriod`, `NtSetSystemInformation` |

---

## Tests

```bash
python -m pytest tests/test_swiftpc.py
```

88 tests.
