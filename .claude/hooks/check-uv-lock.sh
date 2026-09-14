#!/usr/bin/env bash
# Keep uv.lock in step with pyproject.toml.
#
# When pyproject.toml is part of a commit, block it if
#   - uv.lock is out of date with pyproject.toml (`uv lock --check` fails), or
#   - uv.lock has changes that are not part of the commit.
# CI runs with --locked, so either case would fail there anyway.
#
# Two modes, same check:
#   check-uv-lock.sh                   Claude Code PreToolUse hook. Reads the tool call JSON on
#                                      stdin, only acts on `git commit`, blocks with exit 2.
#   check-uv-lock.sh --git-pre-commit  git pre-commit hook (.git/hooks/pre-commit). Checks the
#                                      final staged index, blocks with exit 1.
set -u

# $1: files the commit includes, one per line. Returns 1 (message on stderr) to block.
check_commit() {
  local included="$1"

  # Nothing to enforce unless pyproject.toml is part of the commit.
  printf '%s\n' "$included" | grep -qx 'pyproject.toml' || return 0

  if ! command -v uv >/dev/null 2>&1; then
    echo "uv.lock check skipped: uv is not installed." >&2
    return 0
  fi

  if ! uv lock --check >/dev/null 2>&1; then
    cat >&2 <<'MSG'
Blocked: pyproject.toml is in this commit, but uv.lock is out of date.
Run `uv lock`, then `git add uv.lock` and commit both files together.
(CI runs with --locked and would fail on this commit.)
MSG
    return 1
  fi

  local lock_included=0 lock_unstaged lock_untracked
  printf '%s\n' "$included" | grep -qx 'uv.lock' && lock_included=1
  lock_unstaged="$(git diff --name-only -- uv.lock)"
  lock_untracked="$(git ls-files --others --exclude-standard -- uv.lock)"

  if [ "$lock_included" -eq 0 ] && { [ -n "$lock_unstaged" ] || [ -n "$lock_untracked" ]; }; then
    cat >&2 <<'MSG'
Blocked: pyproject.toml is in this commit, but the updated uv.lock is not.
Run `git add uv.lock` so both files go into the same commit.
MSG
    return 1
  fi

  return 0
}

if [ "${1:-}" = "--git-pre-commit" ]; then
  # git has already staged everything (including -a), so the index is the commit.
  top="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
  cd "$top" || exit 0
  [ -f pyproject.toml ] || exit 0
  check_commit "$(git diff --cached --name-only)" || exit 1
  exit 0
fi

input="$(cat)"
command="$(printf '%s' "$input" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))' 2>/dev/null)" || exit 0

# Only act on git commit commands (also `git -C <dir> commit`).
printf '%s' "$command" | grep -Eq '(^|[;&|(]|[[:space:]])git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit([[:space:]]|$)' || exit 0

cd "${CLAUDE_PROJECT_DIR:-$PWD}" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
[ -f pyproject.toml ] || exit 0

# Files this commit will contain: staged files, plus modified tracked files with -a / --all.
included="$(git diff --cached --name-only)"
if printf '%s' "$command" | grep -Eq '[[:space:]](-[a-zA-Z]*a[a-zA-Z]*|--all)([[:space:]]|$)'; then
  included="$(printf '%s\n%s' "$included" "$(git diff --name-only)")"
fi

check_commit "$included" || exit 2
exit 0
