"""
Тесты для SwiftPC/main.py.

Все системные вызовы замоканы — тесты работают без прав
администратора и без реального Windows-окружения.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    """
    ctypes.windll существует только на Windows.
    На Linux (CI) патчим через patch.object с create=True.
    """

    @staticmethod
    def _mock_windll(retval: int) -> MagicMock:
        mock = MagicMock()
        mock.shell32.IsUserAnAdmin.return_value = retval
        return mock

    def test_returns_true_when_admin(self) -> None:
        with patch.object(ctypes, "windll", self._mock_windll(1), create=True):
            result = main.is_admin()
        assert result is True
        assert isinstance(result, bool)

    def test_returns_false_when_not_admin(self) -> None:
        with patch.object(ctypes, "windll", self._mock_windll(0), create=True):
            result = main.is_admin()
        assert result is False
        assert isinstance(result, bool)

    def test_returns_false_on_exception(self) -> None:
        """Если ctypes бросает исключение — is_admin() должен вернуть False."""
        mock = MagicMock()
        mock.shell32.IsUserAnAdmin.side_effect = OSError("no windll")
        with patch.object(ctypes, "windll", mock, create=True):
            result = main.is_admin()
        assert result is False
        assert isinstance(result, bool)

    def test_nonzero_nonone_is_true(self) -> None:
        """Любое ненулевое значение → True."""
        with patch.object(ctypes, "windll", self._mock_windll(42), create=True):
            result = main.is_admin()
        assert result is True

    def test_return_type_is_always_bool(self) -> None:
        for retval in (0, 1, 2, -1):
            with patch.object(ctypes, "windll", self._mock_windll(retval), create=True):
                assert isinstance(main.is_admin(), bool)


# ─────────────────────────────────────────────────────────────────────
# 4. run() возвращает CompletedProcess
# ─────────────────────────────────────────────────────────────────────

class TestRun:
    @pytest.fixture(autouse=True)
    def reset_dry_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Гарантируем DRY_RUN=False для всех тестов этого класса."""
        monkeypatch.setattr(main, "DRY_RUN", False)

    def test_returns_completed_process(self) -> None:
        fake = _completed(returncode=0, stdout="ok")
        with patch("subprocess.run", return_value=fake):
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
            main.run("bad cmd")
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


# ─────────────────────────────────────────────────────────────────────
# 7. VERSION
# ─────────────────────────────────────────────────────────────────────

class TestVersion:
    def test_version_exists(self) -> None:
        assert hasattr(main, "VERSION")

    def test_version_is_string(self) -> None:
        assert isinstance(main.VERSION, str)

    def test_version_format(self) -> None:
        """VERSION должен быть в формате X.Y.Z где X, Y, Z — целые числа."""
        parts = main.VERSION.split(".")
        assert len(parts) == 3, f"Ожидается X.Y.Z, получено: {main.VERSION!r}"
        for part in parts:
            assert part.isdigit(), f"Компонент {part!r} не является числом"

    def test_version_value(self) -> None:
        assert main.VERSION == "1.2.0"


# ─────────────────────────────────────────────────────────────────────
# 8. DRY_RUN — run() не вызывает subprocess
# ─────────────────────────────────────────────────────────────────────

class TestDryRun:
    def test_dry_run_returns_returncode_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(main, "DRY_RUN", True)
        with patch("subprocess.run") as mock_sp:
            result = main.run("some command")
        mock_sp.assert_not_called()
        assert result.returncode == 0

    def test_dry_run_does_not_call_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(main, "DRY_RUN", True)
        with patch("subprocess.run") as mock_sp:
            main.run("reg add HKLM\\\\test")
        mock_sp.assert_not_called()

    def test_dry_run_returns_completed_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(main, "DRY_RUN", True)
        with patch("subprocess.run"):
            result = main.run("any cmd")
        assert isinstance(result, subprocess.CompletedProcess)

    def test_dry_run_stdout_is_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(main, "DRY_RUN", True)
        with patch("subprocess.run"):
            result = main.run("cmd")
        assert result.stdout == ""

    def test_dry_run_stderr_is_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(main, "DRY_RUN", True)
        with patch("subprocess.run"):
            result = main.run("cmd")
        assert result.stderr == ""

    def test_normal_mode_calls_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """При DRY_RUN=False subprocess.run вызывается как обычно."""
        monkeypatch.setattr(main, "DRY_RUN", False)
        fake = _completed(returncode=0, stdout="ok")
        with patch("subprocess.run", return_value=fake) as mock_sp:
            main.run("echo hello")
        mock_sp.assert_called_once()


# ─────────────────────────────────────────────────────────────────────
# 9. disable_visual_effects() / restore_visual_effects()
# ─────────────────────────────────────────────────────────────────────

class TestDisableVisualEffects:
    @pytest.fixture(autouse=True)
    def _mock_windll(self) -> None:
        """Мокаем ctypes.windll.user32.SystemParametersInfoW глобально для класса."""
        mock_user32 = MagicMock()
        mock_windll = MagicMock()
        mock_windll.user32 = mock_user32
        with patch.object(ctypes, "windll", mock_windll, create=True):
            yield

    def test_returns_true_on_success(self) -> None:
        with patch.object(main, "run", return_value=_completed(returncode=0)):
            result = main.disable_visual_effects()
        assert result is True

    def test_returns_false_on_failure(self) -> None:
        with patch.object(main, "run", return_value=_completed(returncode=1)):
            result = main.disable_visual_effects()
        assert result is False

    def test_calls_reg_add(self) -> None:
        calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return _completed(returncode=0)

        with patch.object(main, "run", side_effect=track):
            main.disable_visual_effects()

        assert any("reg add" in c for c in calls)

    def test_reg_sets_visualfxsetting_2(self) -> None:
        """Реестровая запись должна устанавливать VisualFXSetting = 2."""
        calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return _completed(returncode=0)

        with patch.object(main, "run", side_effect=track):
            main.disable_visual_effects()

        assert any("VisualFXSetting" in c and "/d 2" in c for c in calls)

    def test_restore_calls_reg_add_with_zero(self) -> None:
        """restore_visual_effects() должен выставить VisualFXSetting = 0."""
        calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return _completed(returncode=0)

        with patch.object(main, "run", side_effect=track):
            main.restore_visual_effects()

        assert any("VisualFXSetting" in c and "/d 0" in c for c in calls)


# ─────────────────────────────────────────────────────────────────────
# 10. cleanup_temp()
# ─────────────────────────────────────────────────────────────────────

class TestCleanupTemp:
    def test_removes_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Файлы во временной директории должны быть удалены."""
        fake_temp = tmp_path / "temp"
        fake_temp.mkdir()
        (fake_temp / "file1.tmp").write_text("x")
        (fake_temp / "file2.log").write_text("y")

        # Подменяем оба пути: TEMP env var и C:/Windows/Temp
        monkeypatch.setenv("TEMP", str(fake_temp))
        # Второй путь — несуществующий, чтобы не трогать реальную систему
        with patch.object(main.Path, "__new__", side_effect=lambda cls, *a, **kw: object.__new__(cls)):
            pass  # не используем этот патч — вместо этого мокаем os.environ

        # Проще: патчим temp_dirs внутри функции через monkeypatch env и несуществующий Windows/Temp
        monkeypatch.setenv("TEMP", str(fake_temp))
        # C:/Windows/Temp не существует в tmp_path — функция пропустит его

        removed = main.cleanup_temp()
        assert removed >= 2
        assert not (fake_temp / "file1.tmp").exists()
        assert not (fake_temp / "file2.log").exists()

    def test_removes_subdirectories(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Поддиректории тоже должны удаляться."""
        fake_temp = tmp_path / "temp"
        fake_temp.mkdir()
        subdir = fake_temp / "subdir"
        subdir.mkdir()
        (subdir / "nested.tmp").write_text("z")

        monkeypatch.setenv("TEMP", str(fake_temp))

        removed = main.cleanup_temp()
        assert removed >= 1
        assert not subdir.exists()

    def test_returns_integer(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_temp = tmp_path / "temp_empty"
        fake_temp.mkdir()
        monkeypatch.setenv("TEMP", str(fake_temp))

        result = main.cleanup_temp()
        assert isinstance(result, int)

    def test_empty_dir_returns_zero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_temp = tmp_path / "temp_empty"
        fake_temp.mkdir()
        monkeypatch.setenv("TEMP", str(fake_temp))

        result = main.cleanup_temp()
        assert result == 0

    def test_skips_locked_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Заблокированные файлы не должны прерывать выполнение."""
        fake_temp = tmp_path / "temp"
        fake_temp.mkdir()
        good_file = fake_temp / "good.tmp"
        good_file.write_text("ok")
        bad_file = fake_temp / "locked.tmp"
        bad_file.write_text("locked")

        call_count = 0

        def unlink_side_effect(self_path: Path, missing_ok: bool = False) -> None:
            nonlocal call_count
            call_count += 1
            if self_path.name == "locked.tmp":
                raise PermissionError("locked")
            # Реальное удаление для остальных
            _original_unlink(self_path)

        _original_unlink = Path.unlink

        monkeypatch.setenv("TEMP", str(fake_temp))

        with patch.object(Path, "unlink", unlink_side_effect):
            # Не должен бросить исключение
            result = main.cleanup_temp()

        assert isinstance(result, int)


# ─────────────────────────────────────────────────────────────────────
# 11. show_status()
# ─────────────────────────────────────────────────────────────────────

class TestShowStatus:
    def test_no_state_prints_not_optimized(
        self, isolated_state: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Без state-файла show_status() должен сообщить, что ПК не оптимизирован."""
        assert not isolated_state.exists()

        with patch.object(main, "get_active_power_plan", return_value=None), \
             patch.object(main, "run", return_value=_completed(returncode=0, stdout="")):
            main.show_status()

        # Rich пишет в свой Console — перехватываем через patch на console.print
        # Используем другой подход: патчим console.print и собираем вывод
        printed: list[str] = []
        with patch.object(main.console, "print", side_effect=lambda *a, **kw: printed.append(str(a[0]) if a else "")):
            with patch.object(main, "get_active_power_plan", return_value=None), \
                 patch.object(main, "run", return_value=_completed(returncode=0, stdout="")):
                main.show_status()

        combined = " ".join(printed)
        assert "not currently optimized" in combined or "No state file" in combined

    def test_with_state_prints_optimized(
        self, isolated_state: Path
    ) -> None:
        """При наличии state-файла show_status() сообщает, что ПК оптимизирован."""
        state_data = {
            "killed": ["OneDrive.exe"],
            "stopped_services": ["WSearch"],
        }
        isolated_state.write_text(json.dumps(state_data), encoding="utf-8")

        printed: list[str] = []
        with patch.object(main.console, "print", side_effect=lambda *a, **kw: printed.append(str(a[0]) if a else "")), \
             patch.object(main, "get_active_power_plan", return_value=None), \
             patch.object(main, "run", return_value=_completed(returncode=0, stdout="")):
            main.show_status()

        combined = " ".join(printed)
        # Должно присутствовать либо сообщение об оптимизации, либо список процессов/сервисов
        assert (
            "optimized" in combined
            or "OneDrive.exe" in combined
            or "WSearch" in combined
        )

    def test_shows_running_bloatware(self, isolated_state: Path) -> None:
        """show_status() должен показывать запущенные bloatware-процессы."""
        printed: list[str] = []

        def fake_run(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            # Имитируем что OneDrive.exe запущен
            if "onedrive.exe" in cmd.lower():
                return _completed(returncode=0, stdout="OneDrive.exe 1234 Console")
            return _completed(returncode=0, stdout="")

        with patch.object(main.console, "print", side_effect=lambda *a, **kw: printed.append(str(a[0]) if a else "")), \
             patch.object(main, "get_active_power_plan", return_value=None), \
             patch.object(main, "run", side_effect=fake_run):
            main.show_status()

        combined = " ".join(printed)
        assert "OneDrive.exe" in combined

    def test_no_bloatware_running(self, isolated_state: Path) -> None:
        """Если bloatware не запущен — show_status() сообщает об этом."""
        printed: list[str] = []

        with patch.object(main.console, "print", side_effect=lambda *a, **kw: printed.append(str(a[0]) if a else "")), \
             patch.object(main, "get_active_power_plan", return_value=None), \
             patch.object(main, "run", return_value=_completed(returncode=0, stdout="")):
            main.show_status()

        combined = " ".join(printed)
        assert "No bloatware running" in combined


# ─────────────────────────────────────────────────────────────────────
# 12. find_native_helper()
# ─────────────────────────────────────────────────────────────────────

class TestFindNativeHelper:
    def test_returns_none_when_exe_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Если swiftpc_native.exe отсутствует — возвращается None."""
        # Убеждаемся, что нет _MEIPASS (не PyInstaller-среда)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        # Указываем __file__ на tmp_path, где нет папки native/
        monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))
        result = main.find_native_helper()
        assert result is None

    def test_returns_path_when_exe_exists_in_native(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если swiftpc_native.exe лежит в native/ — возвращается Path к нему."""
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        native_dir = tmp_path / "native"
        native_dir.mkdir()
        exe = native_dir / "swiftpc_native.exe"
        exe.write_bytes(b"fake")
        monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))
        result = main.find_native_helper()
        assert result is not None
        assert result == exe

    def test_returns_path_instance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Возвращаемый объект должен быть экземпляром Path."""
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        native_dir = tmp_path / "native"
        native_dir.mkdir()
        exe = native_dir / "swiftpc_native.exe"
        exe.write_bytes(b"fake")
        monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))
        result = main.find_native_helper()
        assert isinstance(result, Path)

    def test_meipass_lookup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При наличии sys._MEIPASS поиск ведётся в этой директории."""
        meipass_dir = tmp_path / "meipass"
        meipass_dir.mkdir()
        exe = meipass_dir / "swiftpc_native.exe"
        exe.write_bytes(b"fake")
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
        result = main.find_native_helper()
        assert result is not None
        assert result == exe

    def test_meipass_returns_none_when_exe_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При _MEIPASS без exe — тоже None."""
        meipass_dir = tmp_path / "meipass_empty"
        meipass_dir.mkdir()
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
        result = main.find_native_helper()
        assert result is None


# ─────────────────────────────────────────────────────────────────────
# 13. disable_core_parking()
# ─────────────────────────────────────────────────────────────────────

class TestDisableCoreParking:
    def test_returns_true_on_success(self) -> None:
        """powercfg возвращает 0 — функция возвращает True."""
        with patch.object(main, "run", return_value=_completed(returncode=0)):
            result = main.disable_core_parking()
        assert result is True

    def test_returns_false_on_failure(self) -> None:
        """powercfg возвращает 1 — функция возвращает False."""
        with patch.object(main, "run", return_value=_completed(returncode=1)):
            result = main.disable_core_parking()
        assert result is False

    def test_calls_powercfg_with_proc_subgroup_guid(self) -> None:
        """Команда должна содержать GUID подгруппы процессора."""
        calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return _completed(returncode=0)

        with patch.object(main, "run", side_effect=track):
            main.disable_core_parking()

        assert any(main._PROC_SUBGROUP in c for c in calls)

    def test_calls_powercfg_with_core_park_guid(self) -> None:
        """Команда должна содержать GUID параметра core parking."""
        calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return _completed(returncode=0)

        with patch.object(main, "run", side_effect=track):
            main.disable_core_parking()

        assert any(main._CORE_PARK_GUID in c for c in calls)

    def test_calls_powercfg_with_value_100(self) -> None:
        """Команда должна содержать значение 100 (все ядра активны)."""
        calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return _completed(returncode=0)

        with patch.object(main, "run", side_effect=track):
            main.disable_core_parking()

        assert any("100" in c and "powercfg" in c for c in calls)

    def test_setactive_called_after_setacvalueindex(self) -> None:
        """После setacvalueindex должен вызываться powercfg /setactive SCHEME_CURRENT."""
        calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return _completed(returncode=0)

        with patch.object(main, "run", side_effect=track):
            main.disable_core_parking()

        assert any("setactive" in c and "SCHEME_CURRENT" in c for c in calls)


# ─────────────────────────────────────────────────────────────────────
# 14. restore_core_parking()
# ─────────────────────────────────────────────────────────────────────

class TestRestoreCoreParking:
    def test_calls_powercfg_with_value_0(self) -> None:
        """restore_core_parking() должен вызывать powercfg со значением 0."""
        calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return _completed(returncode=0)

        with patch.object(main, "run", side_effect=track):
            main.restore_core_parking()

        assert any(
            "powercfg" in c and main._CORE_PARK_GUID in c and c.rstrip().endswith("0")
            for c in calls
        )

    def test_does_not_raise(self) -> None:
        """restore_core_parking() не должен бросать исключения."""
        with patch.object(main, "run", return_value=_completed(returncode=0)):
            main.restore_core_parking()  # просто не упасть

    def test_does_not_raise_on_run_failure(self) -> None:
        """Даже при ошибке powercfg — исключение не пробрасывается."""
        with patch.object(main, "run", return_value=_completed(returncode=1)):
            main.restore_core_parking()  # просто не упасть

    def test_calls_setactive_scheme_current(self) -> None:
        """После изменения значения должен вызываться /setactive SCHEME_CURRENT."""
        calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return _completed(returncode=0)

        with patch.object(main, "run", side_effect=track):
            main.restore_core_parking()

        assert any("setactive" in c and "SCHEME_CURRENT" in c for c in calls)


# ─────────────────────────────────────────────────────────────────────
# 15. set_timer_resolution() — fallback-путь (нет native-хелпера)
# ─────────────────────────────────────────────────────────────────────

class TestSetTimerResolution:
    def test_calls_reg_add_system_responsiveness(self) -> None:
        """Когда native-хелпер недоступен — вызывается reg add с SystemResponsiveness."""
        calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return _completed(returncode=0)

        with patch.object(main, "find_native_helper", return_value=None), \
             patch.object(main, "run", side_effect=track):
            main.set_timer_resolution()

        assert any("SystemResponsiveness" in c for c in calls)

    def test_sets_system_responsiveness_to_zero(self) -> None:
        """Значение SystemResponsiveness должно быть установлено в 0."""
        calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return _completed(returncode=0)

        with patch.object(main, "find_native_helper", return_value=None), \
             patch.object(main, "run", side_effect=track):
            main.set_timer_resolution()

        assert any("SystemResponsiveness" in c and "/d 0" in c for c in calls)

    def test_calls_reg_add(self) -> None:
        """Fallback должен использовать reg add."""
        calls: list[str] = []

        def track(cmd: str, **_kw: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return _completed(returncode=0)

        with patch.object(main, "find_native_helper", return_value=None), \
             patch.object(main, "run", side_effect=track):
            main.set_timer_resolution()

        assert any("reg add" in c for c in calls)

    def test_does_not_spawn_popen_when_no_helper(self) -> None:
        """Без native-хелпера subprocess.Popen не должен вызываться."""
        with patch.object(main, "find_native_helper", return_value=None), \
             patch.object(main, "run", return_value=_completed(returncode=0)), \
             patch("subprocess.Popen") as mock_popen:
            main.set_timer_resolution()

        mock_popen.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# 16. optimize() — все 11 шагов выполняются
# ─────────────────────────────────────────────────────────────────────

class TestInteractiveMode:
    """
    optimize() запускает все 11 шагов оптимизации.
    Каждая под-функция замокана — реальных системных вызовов нет.
    """

    @pytest.fixture()
    def _mock_all_steps(self, isolated_state: Path) -> None:
        """
        Мокаем все функции-шаги optimize() так, чтобы они не делали
        реальных вызовов и возвращали разумные значения.
        """
        self.mock_kill          = MagicMock(return_value=["OneDrive.exe"])
        self.mock_stop          = MagicMock(return_value=["WSearch"])
        self.mock_power         = MagicMock(return_value="balanced-guid")
        self.mock_ram           = MagicMock(return_value=None)
        self.mock_network       = MagicMock(return_value=True)
        self.mock_gpu           = MagicMock(return_value=None)
        self.mock_visual        = MagicMock(return_value=True)
        self.mock_timer         = MagicMock(return_value=None)
        self.mock_temp          = MagicMock(return_value=5)
        self.mock_core_parking  = MagicMock(return_value=True)
        self.mock_summary       = MagicMock(return_value=None)

    def test_all_steps_called(self, _mock_all_steps: None, isolated_state: Path) -> None:
        """optimize() должен вызвать все 11 функций-шагов."""
        with patch.object(main, "kill_bloatware",          self.mock_kill), \
             patch.object(main, "stop_services",           self.mock_stop), \
             patch.object(main, "switch_to_high_performance", self.mock_power), \
             patch.object(main, "cleanup_ram",             self.mock_ram), \
             patch.object(main, "optimize_network",        self.mock_network), \
             patch.object(main, "set_gpu_priority",        self.mock_gpu), \
             patch.object(main, "disable_visual_effects",  self.mock_visual), \
             patch.object(main, "set_timer_resolution",    self.mock_timer), \
             patch.object(main, "cleanup_temp",            self.mock_temp), \
             patch.object(main, "disable_core_parking",    self.mock_core_parking), \
             patch.object(main, "print_summary",           self.mock_summary):
            main.optimize()

        self.mock_kill.assert_called_once()
        self.mock_stop.assert_called_once()
        self.mock_power.assert_called_once()
        self.mock_ram.assert_called_once()
        self.mock_network.assert_called_once()
        self.mock_gpu.assert_called_once()
        self.mock_visual.assert_called_once()
        self.mock_timer.assert_called_once()
        self.mock_temp.assert_called_once()
        self.mock_core_parking.assert_called_once()
        self.mock_summary.assert_called_once()

    def test_state_saved_after_optimize(self, _mock_all_steps: None, isolated_state: Path) -> None:
        """optimize() должен сохранить state-файл после завершения."""
        with patch.object(main, "kill_bloatware",          self.mock_kill), \
             patch.object(main, "stop_services",           self.mock_stop), \
             patch.object(main, "switch_to_high_performance", self.mock_power), \
             patch.object(main, "cleanup_ram",             self.mock_ram), \
             patch.object(main, "optimize_network",        self.mock_network), \
             patch.object(main, "set_gpu_priority",        self.mock_gpu), \
             patch.object(main, "disable_visual_effects",  self.mock_visual), \
             patch.object(main, "set_timer_resolution",    self.mock_timer), \
             patch.object(main, "cleanup_temp",            self.mock_temp), \
             patch.object(main, "disable_core_parking",    self.mock_core_parking), \
             patch.object(main, "print_summary",           self.mock_summary):
            main.optimize()

        assert isolated_state.exists()
        state = json.loads(isolated_state.read_text(encoding="utf-8"))
        assert "killed" in state
        assert "stopped_services" in state

    def test_optimize_does_not_call_input(self, _mock_all_steps: None, isolated_state: Path) -> None:
        """optimize() сам по себе не вызывает input() — это делает main()."""
        with patch.object(main, "kill_bloatware",          self.mock_kill), \
             patch.object(main, "stop_services",           self.mock_stop), \
             patch.object(main, "switch_to_high_performance", self.mock_power), \
             patch.object(main, "cleanup_ram",             self.mock_ram), \
             patch.object(main, "optimize_network",        self.mock_network), \
             patch.object(main, "set_gpu_priority",        self.mock_gpu), \
             patch.object(main, "disable_visual_effects",  self.mock_visual), \
             patch.object(main, "set_timer_resolution",    self.mock_timer), \
             patch.object(main, "cleanup_temp",            self.mock_temp), \
             patch.object(main, "disable_core_parking",    self.mock_core_parking), \
             patch.object(main, "print_summary",           self.mock_summary), \
             patch("builtins.input") as mock_input:
            main.optimize()

        mock_input.assert_not_called()

    def test_core_parking_result_stored_in_state(
        self, _mock_all_steps: None, isolated_state: Path
    ) -> None:
        """Если disable_core_parking() вернул True — state содержит core_parking_disabled=True."""
        self.mock_core_parking.return_value = True

        with patch.object(main, "kill_bloatware",          self.mock_kill), \
             patch.object(main, "stop_services",           self.mock_stop), \
             patch.object(main, "switch_to_high_performance", self.mock_power), \
             patch.object(main, "cleanup_ram",             self.mock_ram), \
             patch.object(main, "optimize_network",        self.mock_network), \
             patch.object(main, "set_gpu_priority",        self.mock_gpu), \
             patch.object(main, "disable_visual_effects",  self.mock_visual), \
             patch.object(main, "set_timer_resolution",    self.mock_timer), \
             patch.object(main, "cleanup_temp",            self.mock_temp), \
             patch.object(main, "disable_core_parking",    self.mock_core_parking), \
             patch.object(main, "print_summary",           self.mock_summary):
            main.optimize()

        state = main.load_state()
        assert state is not None
        assert state.get("core_parking_disabled") is True
