"""The unified live command requires explicit opt-in before loading credentials."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def command(monkeypatch):
    spec = importlib.util.spec_from_file_location("live_command", ROOT / "scripts/test_live.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0)))
    return module


def test_no_opt_in_loads_no_settings_and_calls_no_service(command, monkeypatch, capsys):
    monkeypatch.delenv("RUN_LIVE_INTEGRATION", raising=False)
    settings = Mock(side_effect=AssertionError("must not load secrets"))
    monkeypatch.setattr(command, "Settings", settings)
    assert command.main() == 2
    settings.assert_not_called()
    command.subprocess.run.assert_not_called()
    assert "RUN_LIVE_INTEGRATION=1" in capsys.readouterr().out


def test_missing_configuration_fails_without_echo(command, monkeypatch, capsys):
    from grounded_tutor.config import Settings

    monkeypatch.setenv("RUN_LIVE_INTEGRATION", "1")
    settings = Settings(_env_file=None, fastgpt_api_key="private-marker", llm_api_key="")
    monkeypatch.setattr(command, "Settings", lambda: settings)
    assert command.main() == 2
    command.subprocess.run.assert_not_called()
    output = capsys.readouterr().out
    assert "LLM_API_KEY" in output and "private-marker" not in output


def test_valid_configuration_runs_only_live_suite_and_preserves_exit(command, monkeypatch):
    from grounded_tutor.config import Settings

    monkeypatch.setenv("RUN_LIVE_INTEGRATION", "1")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--showlocals")
    settings = Settings(_env_file=None, fastgpt_api_key="synthetic", llm_api_key="synthetic")
    monkeypatch.setattr(command, "Settings", lambda: settings)
    command.subprocess.run.return_value.returncode = 1
    assert command.main() == 1
    args, kwargs = command.subprocess.run.call_args
    assert "apps/api/tests/live" in args[0] and "--tb=no" in args[0]
    assert kwargs["env"]["PYTEST_ADDOPTS"] == ""
    assert kwargs["cwd"] == ROOT


def test_invalid_settings_have_no_validation_details(command, monkeypatch, capsys):
    monkeypatch.setenv("RUN_LIVE_INTEGRATION", "1")
    monkeypatch.setattr(command, "Settings", Mock(side_effect=ValueError("private-marker")))
    assert command.main() == 2
    assert "private-marker" not in capsys.readouterr().out
    command.subprocess.run.assert_not_called()
