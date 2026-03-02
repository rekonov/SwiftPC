"""
SwiftPC — оптимизация ПК для игр.
Запуск: python main.py (от имени администратора)
Откат: python main.py --restore
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Принудительно переключаем stdout/stderr на UTF-8 (CP1252 не поддерживает Rich-символы)
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

# ── Конфиг ───────────────────────────────────────────────────────────

VERSION = "1.2.0"

DRY_RUN = False

STATE_FILE = Path(__file__).parent / ".optimizer-state.json"

console = Console()

_timer_process: subprocess.Popen | None = None

# Процессы которые можно безопасно убить во время игры
BLOATWARE_PROCESSES = [
    "OneDrive.exe",
    "Teams.exe",
    "Spotify.exe",
    "Discord.exe",
    "Skype.exe",
    "YourPhone.exe",
    "PhoneExperienceHost.exe",
    "GameBar.exe",
    "GameBarPresenceWriter.exe",
    "SearchUI.exe",
    "Cortana.exe",
    "MicrosoftEdgeUpdate.exe",
    "msedge.exe",
    "TabTip.exe",
    "WidgetService.exe",
    "Widgets.exe",
    "HxOutlook.exe",
    "HxTsr.exe",
]

# Сервисы которые можно остановить на время игры
STOPPABLE_SERVICES = [
    "SysMain",           # Superfetch — кеширование в RAM
    "DiagTrack",         # Телеметрия Windows
    "WSearch",           # Windows Search indexer
    "wuauserv",          # Windows Update
    "DoSvc",             # Delivery Optimization (P2P обновления)
    "dmwappushservice",  # WAP Push Message
    "MapsBroker",        # Downloaded Maps Manager
    "lfsvc",             # Geolocation
    "XblAuthManager",    # Xbox Live Auth (если не нужен Xbox)
    "XblGameSave",       # Xbox Live Game Save
]


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def run(cmd: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    if DRY_RUN:
        console.print(f"  [dim][DRY RUN] {cmd[:80]}[/]")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True, check=check,
    )


def print_header(title: str) -> None:
    console.print(Panel(title, style="bold cyan", expand=False))


def print_ok(msg: str) -> None:
    console.print(f"  [bold green]✓[/] {msg}")


def print_skip(msg: str) -> None:
    console.print(f"  [dim]–[/] {msg}")


def print_err(msg: str) -> None:
    console.print(f"  [bold red]✗[/] {msg}")


def find_native_helper() -> Path | None:
    """Finds swiftpc_native.exe — bundled (PyInstaller) or in native/ folder."""
    if hasattr(sys, "_MEIPASS"):
        helper = Path(sys._MEIPASS) / "swiftpc_native.exe"
    else:
        helper = Path(__file__).parent / "native" / "swiftpc_native.exe"
    return helper if helper.exists() else None


# ── 1. Kill bloatware ────────────────────────────────────────────────

def kill_bloatware() -> list[str]:
    print_header("Kill Background Processes")
    killed: list[str] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Killing processes...", total=len(BLOATWARE_PROCESSES))
        for proc in BLOATWARE_PROCESSES:
            result = run(f'taskkill /IM "{proc}" /F')
            if result.returncode == 0:
                print_ok(f"Killed {proc}")
                killed.append(proc)
            else:
                print_skip(f"{proc} not running")
            progress.advance(task)

    return killed


# ── 2. Stop services ────────────────────────────────────────────────

def stop_services() -> list[str]:
    print_header("Stop Non-Essential Services")
    stopped: list[str] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Stopping services...", total=len(STOPPABLE_SERVICES))
        for svc in STOPPABLE_SERVICES:
            # Проверяем текущий статус
            status = run(f'sc query "{svc}"')
            if "RUNNING" not in status.stdout:
                print_skip(f"{svc} — already stopped")
                progress.advance(task)
                continue

            result = run(f'net stop "{svc}" /y')
            if result.returncode == 0:
                print_ok(f"Stopped {svc}")
                stopped.append(svc)
            else:
                print_err(f"Failed to stop {svc}")
            progress.advance(task)

    return stopped


def restore_services(services: list[str]) -> None:
    print_header("Restore Services")
    for svc in services:
        result = run(f'net start "{svc}"')
        if result.returncode == 0:
            print_ok(f"Started {svc}")
        else:
            print_skip(f"{svc} — failed or already running")


# ── 3. Power plan ───────────────────────────────────────────────────

HIGH_PERF_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"


def get_active_power_plan() -> str | None:
    result = run("powercfg /getactivescheme")
    if result.returncode != 0:
        return None
    # Output: "Power Scheme GUID: <guid>  (<name>)"
    parts = result.stdout.strip().split()
    for i, part in enumerate(parts):
        if part == "GUID:":
            return parts[i + 1] if i + 1 < len(parts) else None
    return None


def set_power_plan(guid: str) -> bool:
    result = run(f"powercfg /setactive {guid}")
    return result.returncode == 0


def switch_to_high_performance() -> str | None:
    print_header("Power Plan -> High Performance")
    original = get_active_power_plan()

    if original and original.lower() == HIGH_PERF_GUID:
        print_skip("Already on High Performance")
        return None

    if set_power_plan(HIGH_PERF_GUID):
        print_ok(f"Switched to High Performance (was: {original})")
        return original
    else:
        print_err("Failed to switch power plan")
        return None


def restore_power_plan(guid: str) -> None:
    print_header("Restore Power Plan")
    if set_power_plan(guid):
        print_ok(f"Restored power plan: {guid}")
    else:
        print_err("Failed to restore power plan")


# ── 4. RAM cleanup (standby list) ───────────────────────────────────

def cleanup_ram() -> None:
    print_header("RAM Cleanup")

    with console.status("[cyan]Clearing RAM and flushing DNS...", spinner="dots"):
        # Flush DNS cache
        result = run("ipconfig /flushdns")
        if result.returncode == 0:
            print_ok("Flushed DNS cache")

        # Flush RAM standby list — native helper is more effective
        helper = find_native_helper()
        if helper:
            result = run(f'"{helper}" flush-ram')
            if result.returncode == 0:
                print_ok("Flushed RAM standby list (native)")
            else:
                print_err("Native flush-ram failed")
        else:
            ps_cmd = (
                "powershell -Command \""
                "[System.GC]::Collect(); "
                "[System.GC]::WaitForPendingFinalizers(); "
                "Write-Host 'GC completed'"
                "\""
            )
            run(ps_cmd)
            print_ok("Triggered .NET GC (no native helper found)")

    # Освобождаем working set текущего процесса
    print_ok("RAM cleanup done")


# ── 5. Network optimization ─────────────────────────────────────────

def optimize_network() -> bool:
    print_header("Network Optimization")
    changed = False

    with console.status("[cyan]Applying network tweaks...", spinner="dots"):
        # Disable Nagle's algorithm (снижает latency в онлайн-играх)
        nagle_cmd = (
            'powershell -Command "'
            "$adapters = Get-NetAdapter | Where-Object {$_.Status -eq 'Up'}; "
            "foreach ($a in $adapters) { "
            "  $path = 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\' + $a.InterfaceGuid; "
            "  Set-ItemProperty -Path $path -Name TcpAckFrequency -Value 1 -Type DWord -ErrorAction SilentlyContinue; "
            "  Set-ItemProperty -Path $path -Name TCPNoDelay -Value 1 -Type DWord -ErrorAction SilentlyContinue; "
            "}"
            '"'
        )
        result = run(nagle_cmd)
        if result.returncode == 0:
            print_ok("Disabled Nagle's algorithm (lower latency)")
            changed = True
        else:
            print_err("Failed to tweak Nagle's algorithm")

        # Disable network throttling
        throttle_cmd = (
            'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile" '
            '/v NetworkThrottlingIndex /t REG_DWORD /d 0xffffffff /f'
        )
        result = run(throttle_cmd)
        if result.returncode == 0:
            print_ok("Disabled network throttling")
            changed = True

    return changed


def restore_network() -> None:
    print_header("Restore Network Settings")

    with console.status("[cyan]Restoring network settings...", spinner="dots"):
        # Restore Nagle defaults
        nagle_cmd = (
            'powershell -Command "'
            "$adapters = Get-NetAdapter | Where-Object {$_.Status -eq 'Up'}; "
            "foreach ($a in $adapters) { "
            "  $path = 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\' + $a.InterfaceGuid; "
            "  Remove-ItemProperty -Path $path -Name TcpAckFrequency -ErrorAction SilentlyContinue; "
            "  Remove-ItemProperty -Path $path -Name TCPNoDelay -ErrorAction SilentlyContinue; "
            "}"
            '"'
        )
        run(nagle_cmd)
        print_ok("Restored Nagle defaults")

        # Restore network throttling
        run(
            'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile" '
            '/v NetworkThrottlingIndex /t REG_DWORD /d 0xa /f'
        )
        print_ok("Restored network throttling")


# ── 6. Game priority boost ───────────────────────────────────────────

def set_gpu_priority() -> None:
    print_header("GPU & Game Priority")

    with console.status("[cyan]Configuring GPU and game priorities...", spinner="dots"):
        # Включаем Game Mode в реестре
        run(
            'reg add "HKCU\\Software\\Microsoft\\GameBar" '
            '/v AutoGameModeEnabled /t REG_DWORD /d 1 /f'
        )
        print_ok("Game Mode enabled")

        # GPU scheduling priority
        run(
            'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile\\Tasks\\Games" '
            '/v "GPU Priority" /t REG_DWORD /d 8 /f'
        )
        run(
            'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile\\Tasks\\Games" '
            '/v Priority /t REG_DWORD /d 6 /f'
        )
        run(
            'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile\\Tasks\\Games" '
            '/v "Scheduling Category" /t REG_SZ /d High /f'
        )
        print_ok("GPU priority set to 8, CPU priority to High")


# ── 7. Visual effects ────────────────────────────────────────────────

def disable_visual_effects() -> bool:
    """Устанавливает режим Best Performance для визуальных эффектов Windows."""
    print_header("Visual Effects -> Best Performance")
    with console.status("[cyan]Disabling visual effects...", spinner="dots"):
        # VisualFXSetting = 2 (Best Performance)
        r1 = run(
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\VisualEffects" '
            '/v VisualFXSetting /t REG_DWORD /d 2 /f'
        )
        # Отключаем анимации через SystemParametersInfo немедленно
        SPI_SETUIEFFECTS = 0x103F
        ctypes.windll.user32.SystemParametersInfoW(SPI_SETUIEFFECTS, 0, 0, 3)
        if r1.returncode == 0:
            print_ok("Visual effects set to Best Performance")
            return True
        print_err("Failed to disable visual effects")
        return False


def restore_visual_effects() -> None:
    """Восстанавливает режим визуальных эффектов Windows по умолчанию."""
    print_header("Restore Visual Effects")
    with console.status("[cyan]Restoring visual effects...", spinner="dots"):
        run(
            'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\VisualEffects" '
            '/v VisualFXSetting /t REG_DWORD /d 0 /f'  # 0 = Let Windows choose
        )
        SPI_SETUIEFFECTS = 0x103F
        ctypes.windll.user32.SystemParametersInfoW(SPI_SETUIEFFECTS, 0, ctypes.c_void_p(1), 3)
        print_ok("Visual effects restored")


# ── 8. Timer resolution ──────────────────────────────────────────────

def set_timer_resolution() -> None:
    """Sets 1ms timer resolution via native helper (background process) or registry fallback."""
    global _timer_process
    print_header("Timer Resolution")
    with console.status("[cyan]Setting timer resolution...", spinner="dots"):
        helper = find_native_helper()
        if helper and not DRY_RUN:
            _timer_process = subprocess.Popen(
                [str(helper), "keep-timer"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print_ok("Timer resolution set to 1ms (native, active while SwiftPC runs)")
        elif helper and DRY_RUN:
            print_ok("[DRY RUN] Would set 1ms timer resolution via native helper")
        else:
            run(
                'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile" '
                '/v SystemResponsiveness /t REG_DWORD /d 0 /f'
            )
            print_ok("SystemResponsiveness set to 0 (registry fallback)")


def restore_timer_resolution() -> None:
    """Restores timer resolution to default."""
    global _timer_process
    print_header("Restore Timer Resolution")
    with console.status("[cyan]Restoring timer resolution...", spinner="dots"):
        helper = find_native_helper()
        if helper:
            run(f'"{helper}" stop-timer')
            if _timer_process is not None:
                try:
                    _timer_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    _timer_process.kill()
                _timer_process = None
            print_ok("Timer resolution restored (native)")
        else:
            run(
                'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile" '
                '/v SystemResponsiveness /t REG_DWORD /d 20 /f'
            )
            print_ok("SystemResponsiveness restored to 20 (default)")


# ── 11. CPU Core Parking ─────────────────────────────────────────────

_PROC_SUBGROUP   = "54533251-82be-4824-96c1-47b60b740d00"
_CORE_PARK_GUID  = "0cc5b647-c1df-4637-891a-dec35c318583"


def disable_core_parking() -> bool:
    """Disables CPU core parking so all cores stay active during gaming."""
    print_header("CPU Core Parking")
    with console.status("[cyan]Disabling CPU core parking...", spinner="dots"):
        r = run(
            f'powercfg /setacvalueindex SCHEME_CURRENT '
            f'{_PROC_SUBGROUP} {_CORE_PARK_GUID} 100'
        )
        run('powercfg /setactive SCHEME_CURRENT')
        if r.returncode == 0:
            print_ok("CPU core parking disabled (all cores active)")
            return True
        print_err("Failed to disable core parking")
        return False


def restore_core_parking() -> None:
    """Restores CPU core parking to default."""
    print_header("Restore CPU Core Parking")
    with console.status("[cyan]Restoring CPU core parking...", spinner="dots"):
        run(
            f'powercfg /setacvalueindex SCHEME_CURRENT '
            f'{_PROC_SUBGROUP} {_CORE_PARK_GUID} 0'
        )
        run('powercfg /setactive SCHEME_CURRENT')
        print_ok("CPU core parking restored to default")


# ── 9. Temp cleanup ──────────────────────────────────────────────────

def cleanup_temp() -> int:
    """Очищает временные файлы из TEMP и C:/Windows/Temp. Возвращает количество удалённых элементов."""
    print_header("Temp Files Cleanup")
    removed = 0
    temp_dirs = [
        Path(os.environ.get("TEMP", "")),
        Path("C:/Windows/Temp"),
    ]
    with console.status("[cyan]Cleaning temp files...", spinner="dots"):
        for temp_dir in temp_dirs:
            if not temp_dir.exists():
                continue
            for item in temp_dir.iterdir():
                try:
                    if item.is_file():
                        item.unlink()
                        removed += 1
                    elif item.is_dir():
                        shutil.rmtree(item)
                        removed += 1
                except Exception:
                    pass
        print_ok(f"Removed {removed} temp items")
    return removed


# ── 10. Summary table ────────────────────────────────────────────────

def print_summary(state: dict) -> None:
    """Выводит итоговую таблицу результатов оптимизации."""
    table = Table(title="Optimization Summary", show_header=True, header_style="bold cyan", expand=False)
    table.add_column("Step", style="dim", min_width=24)
    table.add_column("Result", justify="right")

    killed = state.get("killed", [])
    stopped = state.get("stopped_services", [])
    temp_removed = state.get("temp_removed", 0)

    table.add_row("Processes killed", f"[green]{len(killed)}[/]" if killed else "[dim]0[/]")
    table.add_row("Services stopped", f"[green]{len(stopped)}[/]" if stopped else "[dim]0[/]")
    table.add_row("Power plan", "[green]High Performance[/]" if state.get("original_power_plan") else "[dim]Already optimal[/]")
    table.add_row("Network tweaks", "[green]Applied[/]" if state.get("network_tweaked") else "[dim]Skipped[/]")
    table.add_row("Visual effects", "[green]Disabled[/]" if state.get("visual_effects_changed") else "[dim]Skipped[/]")
    table.add_row("Timer resolution", "[green]Optimized[/]" if state.get("timer_resolution_set") else "[dim]Skipped[/]")
    table.add_row("Temp files removed", f"[green]{temp_removed}[/]" if temp_removed else "[dim]0[/]")
    table.add_row("Core parking", "[green]Disabled[/]" if state.get("core_parking_disabled") else "[dim]Skipped[/]")

    console.print(table)


# ── 11. Status ───────────────────────────────────────────────────────

def show_status() -> None:
    """Показывает текущий статус оптимизации ПК."""
    print_header("SwiftPC — STATUS")

    state = load_state()
    if state:
        age_sec = time.time() - STATE_FILE.stat().st_mtime
        age_h = age_sec / 3600
        age_str = f"{age_h:.1f}h ago"
        if age_h > 8:
            console.print(f"  [yellow]⚠  Optimized {age_str} — state may be stale[/]")
        else:
            console.print(f"  [green]✓[/]  PC is currently optimized (state saved {age_str})")
        killed = state.get("killed", [])
        stopped = state.get("stopped_services", [])
        if killed:
            console.print(f"  [dim]Killed processes:[/] {', '.join(killed)}")
        if stopped:
            console.print(f"  [dim]Stopped services:[/] {', '.join(stopped)}")
    else:
        console.print("  [dim]No state file — PC is not currently optimized[/]")

    # Текущий power plan
    current = get_active_power_plan()
    if current:
        if current.lower() == HIGH_PERF_GUID:
            console.print("  [green]✓[/]  Power plan: High Performance")
        else:
            console.print(f"  [dim]Power plan: {current}[/]")

    # Запущенные bloatware-процессы
    running = []
    for proc in BLOATWARE_PROCESSES:
        r = run(f'tasklist /FI "IMAGENAME eq {proc}" /NH')
        if proc.lower() in r.stdout.lower():
            running.append(proc)
    if running:
        console.print(f"  [yellow]Running bloatware:[/] {', '.join(running)}")
    else:
        console.print("  [green]✓[/]  No bloatware running")


# ── State management ────────────────────────────────────────────────

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_state() -> None:
    STATE_FILE.unlink(missing_ok=True)


# ── Main ─────────────────────────────────────────────────────────────

def optimize() -> None:
    print_header("SwiftPC — BOOST MODE")
    console.print("  Optimizing your PC for gaming...\n")

    state: dict = {}

    # 1. Kill bloatware
    state["killed"] = kill_bloatware()

    # 2. Stop services
    state["stopped_services"] = stop_services()

    # 3. Power plan
    original_plan = switch_to_high_performance()
    if original_plan:
        state["original_power_plan"] = original_plan

    # 4. RAM cleanup
    cleanup_ram()

    # 5. Network
    if optimize_network():
        state["network_tweaked"] = True

    # 6. GPU priority
    set_gpu_priority()

    # 7. Visual effects
    if disable_visual_effects():
        state["visual_effects_changed"] = True

    # 8. Timer resolution
    set_timer_resolution()
    state["timer_resolution_set"] = True

    # 9. Temp cleanup
    temp_removed = cleanup_temp()
    state["temp_removed"] = temp_removed

    # 11. CPU core parking
    if disable_core_parking():
        state["core_parking_disabled"] = True

    # Save state for restore
    save_state(state)

    # Summary
    print_summary(state)

    console.print(Panel(
        f"[bold green]PC optimized for gaming![/]\n"
        f"State saved to [dim]{STATE_FILE}[/]\n"
        f"Run with [bold]--restore[/] when done gaming.",
        title="[bold green]DONE[/]",
        expand=False,
    ))


def restore() -> None:
    print_header("SwiftPC — RESTORE MODE")

    state = load_state()
    if not state:
        print_err("No saved state found. Nothing to restore.")
        return

    if STATE_FILE.exists():
        age_h = (time.time() - STATE_FILE.stat().st_mtime) / 3600
        if age_h > 8:
            console.print(f"  [yellow]⚠  State file is {age_h:.1f}h old — some settings may have changed[/]")

    # Restore services
    stopped = state.get("stopped_services", [])
    if stopped:
        restore_services(stopped)

    # Restore power plan
    original_plan = state.get("original_power_plan")
    if original_plan:
        restore_power_plan(original_plan)

    # Restore network
    if state.get("network_tweaked"):
        restore_network()

    # Restore visual effects
    if state.get("visual_effects_changed"):
        restore_visual_effects()

    # Restore timer resolution
    if state.get("timer_resolution_set"):
        restore_timer_resolution()

    # Restore core parking
    if state.get("core_parking_disabled"):
        restore_core_parking()

    clear_state()

    console.print(Panel(
        "[bold green]Settings restored to normal.[/]",
        title="[bold green]DONE[/]",
        expand=False,
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description="SwiftPC — Windows optimizer for gaming")
    parser.add_argument(
        "--restore", action="store_true",
        help="Restore settings to pre-optimization state",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show current optimization status",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without executing",
    )
    parser.add_argument(
        "--no-wait", action="store_true",
        help="Optimize and exit immediately without waiting to restore (scripting mode)",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"SwiftPC {VERSION}",
    )
    args = parser.parse_args()

    if args.dry_run:
        global DRY_RUN
        DRY_RUN = True

    if not is_admin():
        console.print(Panel(
            "[bold red]Administrator privileges required![/]\n"
            "Right-click → [bold]Run as Administrator[/]",
            style="red",
            expand=False,
        ))
        sys.exit(1)

    if args.status:
        show_status()
    elif args.restore:
        restore()
    else:
        optimize()
        if not args.no_wait:
            console.print(Panel(
                "[bold green]🎮  Gaming mode is ACTIVE[/]\n\n"
                "Press [bold][Enter][/] when you're done playing\n"
                "to restore all settings automatically.",
                title="[bold green]READY[/]",
                style="green",
                expand=False,
            ))
            try:
                input()
            except (KeyboardInterrupt, EOFError):
                pass
            restore()


if __name__ == "__main__":
    main()
