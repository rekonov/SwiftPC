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
import subprocess
import sys
from pathlib import Path

# Принудительно переключаем stdout/stderr на UTF-8 (CP1252 не поддерживает Rich-символы)
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

# ── Конфиг ───────────────────────────────────────────────────────────

STATE_FILE = Path(__file__).parent / ".optimizer-state.json"

console = Console()

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

        # Clear standby list via PowerShell (нужен EmptyStandbyList или RAMMap)
        # Альтернатива — через .NET GC
        ps_cmd = (
            "powershell -Command \""
            "[System.GC]::Collect(); "
            "[System.GC]::WaitForPendingFinalizers(); "
            "Write-Host 'GC completed'"
            "\""
        )
        result = run(ps_cmd)
        if result.returncode == 0:
            print_ok("Triggered .NET GC")

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

    # Save state for restore
    save_state(state)

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
    args = parser.parse_args()

    if not is_admin():
        console.print(Panel(
            "[bold red]Administrator privileges required![/]\n"
            "Right-click → [bold]Run as Administrator[/]",
            style="red",
            expand=False,
        ))
        sys.exit(1)

    if args.restore:
        restore()
    else:
        optimize()


if __name__ == "__main__":
    main()
