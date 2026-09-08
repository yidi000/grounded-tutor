"""Explicit, credential-safe entry point for the existing live integration suite."""

import os
import subprocess
import sys
from pathlib import Path

from grounded_tutor.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.getenv("RUN_LIVE_INTEGRATION") != "1":
        print("Live calls disabled. Opt in with RUN_LIVE_INTEGRATION=1 make test-live.")
        return 2
    try:
        settings = Settings()
    except ValueError:
        print("Invalid local configuration; validation details withheld.")
        return 2
    required = {
        "FASTGPT_BASE_URL": settings.fastgpt_base_url,
        "FASTGPT_API_KEY": settings.fastgpt_api_key.get_secret_value(),
        "LLM_BASE_URL": settings.llm_base_url,
        "LLM_API_KEY": settings.llm_api_key.get_secret_value(),
        "LLM_MODEL": settings.llm_model,
    }
    missing = [name for name, value in required.items() if not value.strip()]
    if missing:
        print("Required configuration is empty: " + ", ".join(missing))
        return 2
    # Do not allow inherited pytest flags to expose credential-bearing local variables.
    env = dict(os.environ, PYTEST_ADDOPTS="")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "apps/api/tests/live",
            "-q",
            "--tb=no",
            "-o",
            "addopts=",
        ],
        cwd=ROOT,
        env=env,
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
