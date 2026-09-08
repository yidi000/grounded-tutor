#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
release_git_dir=$(git rev-parse --path-format=absolute --git-common-dir)
scan() {
    if command -v gitleaks >/dev/null 2>&1; then
        gitleaks "$@" --redact=100 --no-banner
    else
        docker run --rm -v "$PWD:$PWD:ro" -v "$release_scan_dir:$release_scan_dir:ro" \
            -v "$release_git_dir:$release_git_dir:ro" \
            -w "$PWD" -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory \
            -e GIT_CONFIG_VALUE_0="$PWD" ghcr.io/gitleaks/gitleaks:v8.30.1 \
            "$@" --redact=100 --no-banner
    fi
}
release_scan_dir=$(mktemp -d)
trap 'rm -rf "$release_scan_dir"' EXIT
# Full history plus both staged and working tracked snapshots. Never export ignored files.
scan git . --log-opts=--all
mkdir "$release_scan_dir/index" "$release_scan_dir/worktree"
git archive "$(git write-tree)" | tar -xf - -C "$release_scan_dir/index"
git ls-files -z | tar --null -T - -cf - | tar -xf - -C "$release_scan_dir/worktree"
scan dir "$release_scan_dir/index"
scan dir "$release_scan_dir/worktree"
