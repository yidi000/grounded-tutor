"""Exercise the publication guard in disposable real Git repositories."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts/check_public_files.sh"


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    return tmp_path


def tracked(repo, path, content):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(repo, "add", "-f", "--", path)
    return target


def scan(repo):
    # Do not inherit the developer's real provider configuration in test repos.
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo,
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_tree_and_ignored_local_files_pass(repo):
    tracked(repo, "README.md", "Safe public material")
    tracked(repo, "evals/reports/.gitkeep", "")
    (repo / ".env").write_text("PRIVATE_LOCAL_ONLY=yes")
    assert scan(repo).returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "apps/api/.env",
        ".env.production",
        "evals/reports/local.json",
        "evals/reports/public-new.json",
    ],
)
def test_private_paths_rejected(repo, path):
    tracked(repo, path, "private content")
    result = scan(repo)
    assert result.returncode == 1
    assert "private content" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "credential", ["fastgpt" + "-" + "a1B2c3D4" * 4, "Bearer " + "a1B2c3D4" * 4]
)
def test_credentials_rejected_in_index_and_worktree_without_echo(repo, credential):
    target = tracked(repo, "notes.txt", credential)
    target.write_text("clean worktree, unsafe index")
    result = scan(repo)
    assert result.returncode == 1
    assert credential not in result.stdout + result.stderr
    git(repo, "add", "notes.txt")
    target.write_text(credential)
    assert scan(repo).returncode == 1


def test_local_private_ids_are_detected_without_echo(repo):
    private_id = "12ab" * 6
    env = repo / "apps/api/.env"
    env.parent.mkdir(parents=True)
    env.write_text(f'FASTGPT_APP_ID="{private_id}"\n')
    tracked(repo, "notes.txt", "appId=" + private_id)
    result = scan(repo)
    assert result.returncode == 1
    assert private_id not in result.stdout + result.stderr


@pytest.mark.parametrize("content", ["", "NOT_A_SECRET=true"])
def test_report_placeholder_must_be_empty(repo, content):
    tracked(repo, "evals/reports/.gitkeep", content)
    assert scan(repo).returncode == (1 if content else 0)


def test_summary_contains_only_numeric_allowlisted_fields(tmp_path):
    import json
    import sys

    script = SCRIPT.with_name("summarize_evaluation.py")
    source = tmp_path / "private.json"
    target = tmp_path / "public.json"
    source.write_text(
        json.dumps(
            {
                "total": 40,
                "executed": 40,
                "execution_errors": 0,
                "exit_code": 0,
                "metrics": {"journey_pass_rate": 1},
                "configuration": "private study material",
            }
        )
    )
    result = subprocess.run(
        [sys.executable, str(script), str(source), str(target)], capture_output=True, check=False
    )
    assert result.returncode == 0
    assert "private" not in target.read_text()
    data = json.loads(source.read_text())
    data["metrics"]["journey_pass_rate"] = "private study material"
    source.write_text(json.dumps(data))
    target.unlink()
    result = subprocess.run(
        [sys.executable, str(script), str(source), str(target)], capture_output=True, check=False
    )
    assert result.returncode != 0
    assert not target.exists()
    assert b"private study material" not in result.stdout + result.stderr


def test_combined_fastgpt_key_app_id_is_checked_separately(repo):
    app_id = "a1b2" * 6
    (repo / ".env").write_text("LLM_API_KEY=" + "fake_key" + "-" + app_id)
    tracked(repo, "notes.txt", app_id)
    assert scan(repo).returncode == 1


def test_environment_and_dotenv_values_are_both_checked(repo):
    active_id = "a1b2" * 6
    (repo / ".env").write_text("FASTGPT_APP_ID=" + "c3d4" * 6)
    tracked(repo, "notes.txt", active_id)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo,
        env={"PATH": os.environ["PATH"], "FASTGPT_APP_ID": active_id},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert active_id not in result.stdout + result.stderr
