/**
 * swiftpc_native.cpp — Low-level Win32 helper for SwiftPC.
 *
 * Commands:
 *   flush-ram    — Flush the RAM standby list via NtSetSystemInformation
 *   keep-timer   — Set 1ms timer resolution; hold until signalled via stop-timer
 *   stop-timer   — Signal keep-timer to release the timer and exit
 *
 * Build (MinGW):
 *   windres swiftpc_native.rc -O coff -o swiftpc_native.res
 *   g++ -O2 -o swiftpc_native.exe swiftpc_native.cpp swiftpc_native.res -lwinmm -mwindows
 */

#include <windows.h>
#include <mmsystem.h>
#include <string>
#include <cstdio>

// ── NTAPI types (not in MinGW headers) ───────────────────────────────

typedef LONG NTSTATUS;

typedef NTSTATUS (NTAPI *PNtSetSystemInformation)(
    ULONG  SystemInformationClass,
    PVOID  SystemInformation,
    ULONG  SystemInformationLength
);

#define SystemMemoryListInformation 80u
#define MemoryPurgeStandbyList      4u

// ── Named event used to signal keep-timer ────────────────────────────

static const wchar_t* TIMER_EVENT = L"Global\\SwiftPC_TimerStop";

// ── Privilege helper ─────────────────────────────────────────────────

static bool enable_privilege(LPCWSTR name) {
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(),
                          TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                          &token)) {
        return false;
    }

    LUID luid{};
    bool ok = false;
    if (LookupPrivilegeValueW(nullptr, name, &luid)) {
        TOKEN_PRIVILEGES tp{};
        tp.PrivilegeCount           = 1;
        tp.Privileges[0].Luid       = luid;
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;
        ok = AdjustTokenPrivileges(token, FALSE, &tp, sizeof(tp),
                                   nullptr, nullptr) != 0
             && GetLastError() == ERROR_SUCCESS;
    }
    CloseHandle(token);
    return ok;
}

// ── Command: flush-ram ───────────────────────────────────────────────

static int cmd_flush_ram() {
    // SeProfileSingleProcessPrivilege is required for standby-list purge
    enable_privilege(L"SeProfileSingleProcessPrivilege");

    HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
    if (!ntdll) return 1;

    auto NtSetSysInfo = reinterpret_cast<PNtSetSystemInformation>(
        GetProcAddress(ntdll, "NtSetSystemInformation"));
    if (!NtSetSysInfo) return 1;

    ULONG cmd = MemoryPurgeStandbyList;
    NTSTATUS st = NtSetSysInfo(SystemMemoryListInformation, &cmd, sizeof(cmd));
    return (st == 0) ? 0 : 1;
}

// ── Command: keep-timer ──────────────────────────────────────────────

static int cmd_keep_timer() {
    TIMECAPS tc{};
    if (timeGetDevCaps(&tc, sizeof(tc)) != MMSYSERR_NOERROR) return 1;

    UINT period = tc.wPeriodMin;   // typically 1 ms
    if (timeBeginPeriod(period) != TIMERR_NOERROR) return 1;

    // Create the named event; wait until stop-timer signals it
    HANDLE hEvent = CreateEventW(nullptr, /*manual-reset=*/TRUE,
                                 /*initial-state=*/FALSE, TIMER_EVENT);
    if (hEvent) {
        WaitForSingleObject(hEvent, INFINITE);
        CloseHandle(hEvent);
    } else {
        // Fallback: wait forever (process will be killed on restore)
        Sleep(INFINITE);
    }

    timeEndPeriod(period);
    return 0;
}

// ── Command: stop-timer ──────────────────────────────────────────────

static int cmd_stop_timer() {
    HANDLE hEvent = OpenEventW(EVENT_MODIFY_STATE, FALSE, TIMER_EVENT);
    if (!hEvent) return 1;
    SetEvent(hEvent);
    CloseHandle(hEvent);
    return 0;
}

// ── Entry point ──────────────────────────────────────────────────────

int main(int argc, char* argv[]) {
    if (argc < 2) {
        fprintf(stderr, "usage: swiftpc_native.exe <flush-ram|keep-timer|stop-timer>\n");
        return 1;
    }

    std::string cmd = argv[1];

    if (cmd == "flush-ram")  return cmd_flush_ram();
    if (cmd == "keep-timer") return cmd_keep_timer();
    if (cmd == "stop-timer") return cmd_stop_timer();

    fprintf(stderr, "unknown command: %s\n", argv[1]);
    return 1;
}
