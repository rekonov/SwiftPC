"""
Тесты для SwiftPC/main.py.

Все системные вызовы замоканы — тесты работают без прав
администратора и без реального Windows-окружения.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

# Добавляем корень проекта в sys.path, чтобы импорт работал
# независимо от того, откуда запущен pytest.
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main  # noqa: E402  (импорт после манипуляций с path)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    """Быстрый конструктор CompletedProcess для использования в mock-ах."""
    return subprocess.CompletedProcess(
        args="<mocked>",
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ─────────────────────────────────────────────────────────────────────
# Fixture: изолируем STATE_FILE через tmp_path
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture()
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Перенаправляет main.STATE_FILE в tmp_path, возвращает новый путь."""
    state_path = tmp_path / ".optimizer-state.json"
    monkeypatch.setattr(main, "STATE_FILE", state_path)
    return state_path


# ─────────────────────────────────────────────────────────────────────
# 1. State management
# ─────────────────────────────────────────────────────────────────────

class TestSaveState:
    def test_creates_file(self, isolated_state: Path) -> None:
        main.save_state({"key": "value"})
        assert isolated_state.exists()

    def test_content_is_valid_json(self, isolated_state: Path) -> None:
        data = {"killed": ["OneDrive.exe"], "stopped_services": ["WSearch"]}
        main.save_state(data)
        loaded = json.loads(isolated_state.read_text(encoding="utf-8"))
        assert loaded == data

    def test_overwrites_existing(self, isolated_state: Path) -> None:
        main.save_state({"v": 1})
        main.save_state({"v": 2})
        loaded = json.loads(isolated_state.read_text(encoding="utf-8"))
        assert loaded["v"] == 2

    def test_empty_dict(self, isolated_state: Path) -> None:
        main.save_state({})
        loaded = json.loads(isolated_state.read_text(encoding="utf-8"))
        assert loaded == {}


class TestLoadState:
    def test_returns_none_when_file_missing(self, isolated_state: Path) -> None:
        assert not isolated_state.exists()
        assert main.load_state() is None

    def test_returns_dict_when_file_exists(self, isolated_state: Path) -> None:
        data = {"stopped_services": ["SysMain"], "network_tweaked": True}
        isolated_state.write_text(json.dumps(data), encoding="utf-8")
        result = main.load_state()
        assert result == data

    def test_returns_none_on_corrupt_json(self, isolated_state: Path) -> None:
        isolated_state.write_text("{ not valid json !!!", encoding="utf-8")
        assert main.load_state() is None

    def test_round_trip(self, isolated_state: Path) -> None:
        original = {"killed": ["Teams.exe"], "original_power_plan": "abc-guid"}
        main.save_state(original)
        assert main.load_state() == original


class TestClearState:
    def test_removes_existing_file(self, isolated_state: Path) -> None:
        isolated_state.write_text("{}", encoding="utf-8")
        assert isolated_state.exists()
        main.clear_state()
        assert not isolated_state.exists()

    def test_no_error_when_file_missing(self, isolated_state: Path) -> None:
        assert not isolated_state.exists()
        # Не должен бросить исключение
        main.clear_state()

    def test_state_gone_after_clear(self, isolated_state: Path) -> None:
        main.save_state({"x": 1})
        main.clear_state()
        assert main.load_state() is None


# ─────────────────────────────────────────────────────────────────────
# 2. restore() без state-файла
# ─────────────────────────────────────────────────────────────────────

class TestRestoreWithoutState:
    def test_no_exception_when_no_state(self, isolated_state: Path) -> None:
        """restore() при отсутствии state-файла должен завершиться без исключения."""
        assert not isolated_state.exists()
        # Не должен бросить никаких исключений
        main.restore()

    def test_does_not_call_run_when_no_state(self, isolated_state: Path) -> None:
        """При отсутствии state-файла run() вызываться не должен."""
        with patch.object(main, "run") as mock_run:
            main.restore()
        mock_run.assert_not_called()

    def test_no_state_does_not_call_restore_services(self, isolated_state: Path) -> None:
        with patch.object(main, "restore_services") as mock_rs:
            main.restore()
        mock_rs.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# 3. is_admin() возвращает bool
# ─────────────────────────────────────────────────────────────────────

class TestIsAdmin:
    def test_returns_true_when_admin(self) -> None:
        with patch("ctypes.windll.shell32.IsUserAnAdmin", return_value=1):
            result = main.is_admin()
        assert result is True
        assert isinstance(result, bool)

    def test_returns_false_when_not_admin(self) -> None:
        with patch("ctypes.windll.shell32.IsUserAnAdmin", return_value=0):
            result = main.is_admin()
        assert result is False
        assert isinstance(result, bool)

    def test_returns_false_on_exception(self) -> None:
        """Если ctypes бросает исключение — is_admin() должен вернуть False."""
        with patch("ctypes.windll.shell32.IsUserAnAdmin", side_effect=OSError("no windll")):
            result = main.is_admin()
        assert result is False
        assert isinstance(result, bool)

    def test_nonzero_nonone_is_true(self) -> None:
        """Любое ненулевое значение → True."""
        with patch("ctypes.windll.shell32.IsUserAnAdmin", return_value=42):
            result = main.is_admin()
        assert result is True

    def test_return_type_is_always_bool(self) -> None:
        for retval in (0, 1, 2, -1):
            with patch("ctypes.windll.shell32.IsUserAnAdmin", return_value=retval):
                assert isinstance(main.is_admin(), bool)


# ─────────────────────────────────────────────────────────────────────
# 4. run() возвращает CompletedProcess
# ─────────────────────────────────────────────────────────────────────

class TestRun:
    def test_returns_completed_process(self) -> None:
        fake = _completed(returncode=0, stdout="ok")
        with patch("subprocess.run", return_value=fake) as mock_sp:
            result = main.run("echo test")
        assert isinstance(result, subprocess.CompletedProcess)
        assert result.returncode == 0
        assert result.stdout == "ok"

    def test_passes_shell_true(self) -> None:
        fake = _completed()
        with patch("subprocess.run", return_value=fake) as mock_sp:
            main.run("some cmd")
        _, kwargs = mock_sp.call_args
        assert kwargs.get("shell") is True

    def test_captures_output(self) -> None:
        fake = _completed()
        with patch("subprocess.run", return_value=fake) as mock_sp:
            main.run("some cmd")
        _, kwargs = mock_sp.call_args
        assert kwargs.get("capture_output") is True

    def test_text_mode(self) -> None:
        fake = _completed()
        with patch("subprocess.run", return_value=fake) as mock_sp:
            main.run("some cmd")
        _, kwargs = mock_sp.call_args
        assert kwargs.get("text") is True

    def test_check_false_by_default(self) -> None:
        fake = _completed(returncode=1)
        with patch("subprocess.run", return_value=fake) as mock_sp:
            result = main.run("bad cmd")
        _, kwargs = mock_sp.call_args
        assert kwargs.get("check") is False

    def test_check_true_when_passed(self) -> None:
        fake = _completed(returncode=0)
        with patch("subprocess.run", return_value=fake) as mock_sp:
            main.run("cmd", check=True)
        _, kwargs = mock_sp.call_args
        assert kwargs.get("check") is True

    def test_nonzero_returncode_propagated(self) -> None:
        fake = _completed(returncode=2, stderr="error text")
        with patch("subprocess.run", return_value=fake):
            result = main.run("bad cmd")
        assert result.returncode == 2
        assert result.stderr == "error text"


# ─────────────────────────────────────────────────────────────────────
# 5. kill_bloatware() — список убитых процессов
# ─────────────────────────────────────────────────────────────────────

class TestKillBloatware:
    def _make_side_effect(self, targets: set[str]) -> MagicMock:
        """
        Возвращает side_effect для mock run():
        returncode=0 если имя процесса присутствует в targets, иначе 1.
        """
        def side_effect(cmd: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            for name in targets:
                if name in cmd:
                    return _completed(returncode=0)
            return _completed(returncode=1)
        return side_effect

    def test_returns_list(self) -> None:
        with patch.object(main, "run", return_value=_completed(returncode=1)):
            result = main.kill_bloatware()
        assert isinstance(result, list)

    def test_killed_processes_in_result(self) -> None:
        targets = {"OneDrive.exe", "Spotify.exe"}
        with patch.object(main, "run", side_effect=self._make_side_effect(targets)):
            result = main.kill_bloatware()
        assert set(result) == targets

    def test_empty_list_when_nothing_running(self) -> None:
        with patch.object(main, "run", return_value=_completed(returncode=1)):
            result = main.kill_bloatware()
        assert result == []

    def test_all_killed_when_all_running(self) -> None:
        with patch.object(main, "run", return_value=_completed(returncode=0)):
            result = main.kill_bloatware()
        assert set(result) == set(main.BLOATWARE_PROCESSES)

    def test_run_called_for_each_process(self) -> None:
        with patch.object(main, "run", return_value=_completed(returncode=1)) as mock_run:
            main.kill_bloatware()
        assert mock_run.call_count == len(main.BLOATWARE_PROCESSES)

    def test_taskkill_command_format(self) -> None:
        """Команда должна содержать taskkill /IM <proc> /F."""
        with patch.object(main, "run", return_value=_completed(returncode=1)) as mock_run:
            main.kill_bloatware()
        first_call_cmd: str = mock_run.call_args_list[0][0][0]
        assert "taskkill" in first_call_cmd
        assert "/IM" in first_call_cmd
        assert "/F" in first_call_cmd

    def test_partial_kill(self) -> None:
        """Только часть процессов запущена."""
        targets = {"Discord.exe", "Teams.exe", "msedge.exe"}
        with patch.object(main, "run", side_effect=self._make_side_effect(targets)):
            result = main.kill_bloatware()
        assert set(result) == targets
        assert len(result) == 3


# ─────────────────────────────────────────────────────────────────────
# 6. stop_services() — логика RUNNING / already stopped
# ─────────────────────────────────────────────────────────────────────

class TestStopServices:
    def _run_factory(self, running_services: set[str]) -> MagicMock:
        """
        Имитирует поведение run():
        - sc query → stdout содержит RUNNING только если сервис в running_services
        - net stop → всегда returncode=0
        """
        def side_effect(cmd: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if cmd.startswith("sc query"):
                # Определяем имя сервиса из команды: sc query "SvcName"
                svc_name = cmd.split('"')[1] if '"' in cmd else ""
                stdout = "STATE : 4  RUNNING" if svc_name in running_services else "STATE : 1  STOPPED"
                return _completed(returncode=0, stdout=stdout)
            # net stop
            return _completed(returncode=0)
        return side_effect

    def test_returns_list(self) -> None:
        with patch.object(main, "run", side_effect=self._run_factory(set())):
            result = main.stop_services()
        assert isinstance(result, list)

    def test_running_service_is_stopped(self) -> None:
        running = {"WSearch", "SysMain"}
        with patch.object(main, "run", side_effect=self._run_factory(running)):
            result = main.stop_services()
        assert set(result) == running

    def test_stopped_service_is_skipped(self) -> None:
        """Сервисы не в RUNNING не должны попасть в список stopped."""
        with patch.object(main, "run", side_effect=self._run_factory(set())):
            result = main.stop_services()
        assert result == []

    def test_all_services_stopped_when_all_running(self) -> None:
        all_svcs = set(main.STOPPABLE_SERVICES)
        with patch.object(main, "run", side_effect=self._run_factory(all_svcs)):
            result = main.stop_services()
        assert set(result) == all_svcs

    def test_sc_query_called_for_each_service(self) -> None:
        """sc query вызывается ровно один раз для каждого сервиса."""
        calls_log: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls_log.append(cmd)
            return _completed(returncode=0, stdout="STOPPED")

        with patch.object(main, "run", side_effect=track):
            main.stop_services()

        sc_query_calls = [c for c in calls_log if c.startswith("sc query")]
        assert len(sc_query_calls) == len(main.STOPPABLE_SERVICES)

    def test_net_stop_not_called_for_already_stopped(self) -> None:
        """net stop не вызывается для сервисов, которые уже остановлены."""
        net_stop_calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            if cmd.startswith("net stop"):
                net_stop_calls.append(cmd)
            return _completed(returncode=0, stdout="STOPPED")

        with patch.object(main, "run", side_effect=track):
            main.stop_services()

        assert net_stop_calls == []

    def test_net_stop_called_only_for_running(self) -> None:
        running = {"DiagTrack"}
        net_stop_calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            if cmd.startswith("net stop"):
                net_stop_calls.append(cmd)
                return _completed(returncode=0)
            svc_name = cmd.split('"')[1] if '"' in cmd else ""
            stdout = "RUNNING" if svc_name in running else "STOPPED"
            return _completed(returncode=0, stdout=stdout)

        with patch.object(main, "run", side_effect=track):
            result = main.stop_services()

        assert len(net_stop_calls) == 1
        assert "DiagTrack" in net_stop_calls[0]
        assert result == ["DiagTrack"]

    def test_failed_net_stop_not_in_result(self) -> None:
        """Если net stop вернул ошибку — сервис НЕ попадает в список stopped."""
        running = {"wuauserv"}

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            if cmd.startswith("sc query"):
                svc_name = cmd.split('"')[1] if '"' in cmd else ""
                stdout = "RUNNING" if svc_name in running else "STOPPED"
                return _completed(returncode=0, stdout=stdout)
            # net stop — имитируем отказ
            return _completed(returncode=2, stderr="Access denied")

        with patch.object(main, "run", side_effect=track):
            result = main.stop_services()

        assert result == []
