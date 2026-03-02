# SwiftPC v1.2.0

Windows PC optimizer for gaming. Kills background bloat, stops unnecessary services, and tweaks system settings — then restores everything when you're done.

## Requirements

- Windows 10/11
- Python 3.10+
- Administrator privileges (auto-elevated by `SwiftPC.exe`)

```
pip install -r requirements.txt
```

## Usage

**Standard usage** (double-click):

Double-click `SwiftPC.exe` — it requests elevation automatically, so no need to right-click "Run as administrator".

```
SwiftPC.exe → optimizes → shows "Gaming mode ACTIVE" → press Enter → restores
```

**Scripting / automation** (optimize and exit immediately):
```
python main.py --no-wait
```

**Restore manually** (if terminal was closed):
```
python main.py --restore
```

**Check current status:**
```
python main.py --status
```

**Preview without changes:**
```
python main.py --dry-run
```

## What it does

| Step | Action |
|------|--------|
| 1 | Kills background processes (OneDrive, Teams, Spotify, Discord, etc.) |
| 2 | Stops non-essential services (Superfetch, Telemetry, Windows Search, Windows Update, etc.) |
| 3 | Switches power plan to High Performance |
| 4 | Flushes DNS cache and flushes RAM standby list (native C++) |
| 5 | Disables Nagle's algorithm and network throttling for lower latency |
| 6 | Sets GPU priority to 8 and enables Game Mode |
| 7 | Sets visual effects to Best Performance mode |
| 8 | Sets timer resolution to 1ms via native C++ helper (active while app runs) |
| 9 | Cleans up TEMP and Windows\Temp directories |
| 10 | Disables CPU core parking (all cores stay active) |
| 11 | Prints a summary table of all applied optimizations |

All changes are reversible — closing the app (or pressing Enter) restores everything automatically.

State is saved to `.optimizer-state.json` so `--restore` can undo everything even if the app was closed unexpectedly.

## Native C++ helper

SwiftPC bundles `swiftpc_native.exe`, a small C++ helper that handles operations requiring direct Win32 APIs — specifically `timeBeginPeriod(1)` for real 1ms timer resolution and `NtSetSystemInformation` for standby RAM flush. These can't be done persistently from Python alone.

## Build

Requires PyInstaller and MinGW `g++` in PATH. `build.bat` compiles the C++ helper first, then packages the Python app:

```
build.bat
```

Output: `dist\SwiftPC.exe`
