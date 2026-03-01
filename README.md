# SwiftPC

Windows PC optimizer for gaming. Kills background bloat, stops unnecessary services, and tweaks system settings — then restores everything when you're done.

## Requirements

- Windows 10/11
- Python 3.10+
- Administrator privileges

```
pip install -r requirements.txt
```

## Usage

**Optimize** (run before gaming):
```
python main.py
```

**Restore** (run after gaming):
```
python main.py --restore
```

Both commands must be run as Administrator.

## What it does

| Step | Action |
|------|--------|
| 1 | Kills background processes (OneDrive, Teams, Spotify, Discord, etc.) |
| 2 | Stops non-essential services (Superfetch, Telemetry, Windows Search, Windows Update, etc.) |
| 3 | Switches power plan to High Performance |
| 4 | Flushes DNS cache and triggers .NET GC |
| 5 | Disables Nagle's algorithm and network throttling for lower latency |
| 6 | Sets GPU priority to 8 and enables Game Mode |

State is saved to `.optimizer-state.json` so `--restore` can undo everything.

## Build .exe

Install PyInstaller, then run:
```
build.bat
```

Output: `dist\SwiftPC.exe`
