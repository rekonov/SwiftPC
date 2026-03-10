# Changelog

All notable changes to the SwiftPC project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.2.0] - 2026-03-09

### Added

- Native C++ helper module (`swiftpc_native.exe`) for Win32 API operations:
  - `flush-ram`: purge standby memory list via `NtSetSystemInformation`.
  - `keep-timer`: hold 1ms timer resolution via `timeBeginPeriod`.
  - `stop-timer`: signal named event to release timer.
- `.gitattributes` for LF line ending normalization.
- Cache directories added to `.gitignore` (`.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`).

### Fixed

- UTF-8 stdout encoding on Windows to fix CP1252 crash.
- Test compatibility: patched `ctypes.windll` with `create=True` for Linux CI.
- Removed unused imports and variables from test suite.

### Changed

- Removed empty screenshots placeholder from README.

## [1.0.0] - 2026-02-14

### Added

- Initial release: Rich CLI with 11 reversible Windows optimizations.
- Process killer for 16 background bloatware processes.
- Service stopper for 10 non-essential Windows services.
- High Performance power plan switching with original plan restore.
- DNS cache flush and standby RAM cleanup.
- Network optimization: Nagle's algorithm and throttling disabled.
- GPU priority and Game Mode activation.
- Visual effects set to Best Performance.
- TEMP and Windows\Temp cleanup.
- CPU core parking disabled.
- State persistence to `.optimizer-state.json` with crash recovery.
- `--restore`, `--status`, `--dry-run`, `--no-wait` CLI flags.
- 88 pytest tests with full mocking.
- GitLab CI pipeline (lint, test).
- PyInstaller build with UAC admin auto-elevation.
