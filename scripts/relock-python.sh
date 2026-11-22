#!/usr/bin/env bash
# Relock every uv project in the repo, or with --check, verify that every
# uv.lock still matches its pyproject.toml.
#
# Every Python install (Docker images and CI) uses `--locked`, so a lock that
# disagrees with its manifest fails them. The backend and worker locks record
# core_shared's requirements, so editing core_shared/pyproject.toml leaves all
# five of them stale. Running this after any manifest edit fixes every one.
#
# Locks are found with `git ls-files`, so a new project is covered as soon as
# its uv.lock is committed. `uv lock` runs without an upgrade flag, so each
# lock only changes as far as the new metadata forces. A project that can't be
# resolved
# (e.g. a core_shared floor above a worker's `==` pin) is reported, the rest
# are still relocked, and the script exits non-zero.
#
# Used by the uv-lock-python pre-commit hook, the python-locks CI job (--check)
# and .github/workflows/relock-dependents.yml.
set -euo pipefail

mode=lock
case "${1:-}" in
    "") ;;
    --check) mode=check ;;
    *)
        echo "usage: $0 [--check]" >&2
        exit 2
        ;;
esac

cd "$(git rev-parse --show-toplevel)"

projects=()
while IFS= read -r lock; do
    projects+=("$(dirname "$lock")")
done < <(git ls-files '*uv.lock')

if [[ "${#projects[@]}" -eq 0 ]]; then
    echo "error: no committed uv.lock files found" >&2
    exit 1
fi

failed=()
for project in "${projects[@]}"; do
    if [[ "$mode" = check ]]; then
        if ! uv lock --check --quiet --directory "$project"; then
            failed+=("$project")
        fi
    elif ! uv lock --quiet --directory "$project"; then
        failed+=("$project")
    fi
done

if [[ "${#failed[@]}" -eq 0 ]]; then
    echo "All ${#projects[@]} uv projects are locked: ${projects[*]}"
    exit 0
fi

for project in "${failed[@]}"; do
    if [[ "$mode" = check ]]; then
        message="$project/uv.lock is stale; run scripts/relock-python.sh"
    else
        message="$project could not be relocked; see uv's error above"
    fi
    if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
        echo "::error file=$project/uv.lock::$message"
    else
        echo "error: $message" >&2
    fi
done
exit 1
