#!/usr/bin/env bash
set -euo pipefail
# stdlib only; never source .env or print matched values, lines, or filenames.
python3 - <<'PY'
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def main():
    os.chdir(os.fsdecode(git("rev-parse", "--show-toplevel").strip()))
    config = list(os.environ.items())
    for path in (Path(".env"), Path("apps/api/.env")):
        if path.is_file():
            for line in path.read_text().splitlines():
                match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=(.*)", line)
                if match:
                    values = shlex.split(match[2], comments=True)
                    config.append((match[1], " ".join(values)))
    private_values = [value.encode() for key, value in config if value and (
        re.search(r"(?:DATASET|APP)_?ID", key, re.I)
        or key in {"FASTGPT_API_KEY", "LLM_API_KEY"}
    )]
    # FastGPT application credentials use key-appId; protect each component too.
    for key, value in config:
        if key in {"FASTGPT_API_KEY", "LLM_API_KEY"}:
            match = re.fullmatch(r"(.+)-([a-fA-F0-9]{24})", value)
            if match:
                private_values.extend(part.encode() for part in match.groups())
    # Literal fixture tokens such as "Bearer secret" are not credentials. Real local
    # values are checked regardless of length; full-history Gitleaks complements this guard.
    credential = re.compile(rb"fastgpt-[A-Za-z0-9_-]{16,}|\bBearer\s+[A-Za-z0-9._~+/-]{20,}=*", re.I)
    violations = 0
    for entry in git("ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, object_id, stage = metadata.split()
        path = Path(os.fsdecode(raw_path))
        # Only reviewed public report filenames are allowed; content scanning still applies.
        forbidden = any(part == ".env" or part.startswith(".env.") for part in path.parts)
        if path.as_posix() in {".env.example", "apps/api/.env.example"}:
            forbidden = False  # Exact public templates still undergo credential scanning.
        forbidden |= "evals/reports" in path.as_posix() and path.as_posix() not in {
            "evals/reports/.gitkeep", "evals/reports/public-p0.json", "evals/reports/public-p0.md"
        }
        if mode not in {b"100644", b"100755"} or stage != b"0":
            violations += 1
            continue
        contents = [git("cat-file", "blob", object_id.decode())]
        if path.is_symlink():
            violations += 1
            continue
        if path.exists():
            contents.append(path.read_bytes())
        forbidden |= path.as_posix() == "evals/reports/.gitkeep" and any(contents)
        violations += bool(forbidden or any(
            credential.search(content) or any(value in content for value in private_values)
            for content in contents
        ))
    print(f"Public-file check: {violations} blocked entries.")
    return int(bool(violations))


try:
    sys.exit(main())
except (OSError, ValueError, subprocess.CalledProcessError):
    print("Public-file check could not complete.", file=sys.stderr)
    sys.exit(2)
PY
