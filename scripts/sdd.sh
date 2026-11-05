#!/usr/bin/env bash
# specsteward launcher: finds a Python 3.11+ (never the Windows Store stub) and runs the CLI.
# Override with SDD_PYTHON=/path/to/python.
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

works() {
  "$@" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

# The command goes into an array, so a path with spaces (C:\Users\First Last\...) stays one
# word while `py -3` stays two.
PYTHON=()
pick_python() {
  if [ -n "${SDD_PYTHON:-}" ]; then
    PYTHON=("$SDD_PYTHON")
    return
  fi
  local candidate
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && works "$candidate"; then
      PYTHON=("$candidate")
      return
    fi
  done
  if command -v py >/dev/null 2>&1 && works py -3; then
    PYTHON=(py -3)
    return
  fi
  # No Python 3.11+, but uv can provide one (it downloads a managed Python once).
  if command -v uv >/dev/null 2>&1 && works uv run --no-project --quiet --python ">=3.11" python; then
    PYTHON=(uv run --no-project --quiet --python ">=3.11" python)
    return
  fi
  {
    echo "specsteward: Python 3.11+ not found."
    echo "  Install it from https://www.python.org/downloads/ , or install uv"
    echo "  (https://docs.astral.sh/uv/) and specsteward will use a uv-managed Python."
    echo "  Or point SDD_PYTHON at a Python 3.11+ executable."
  } >&2
  exit 127
}

# Hooks fire in every project. Without an sdd.toml at or above the project directory they
# have nothing to do, so leave before starting Python (saves ~100 ms per edit and session).
CONFIG_DIR=""
has_config() {
  local dir="${CLAUDE_PROJECT_DIR:-$PWD}"
  while :; do
    [ -f "$dir/sdd.toml" ] && CONFIG_DIR="$dir" && return 0
    local parent
    parent="$(dirname "$dir")"
    [ "$parent" = "$dir" ] && return 1
    dir="$parent"
  done
}

case "${1:-}" in
  # Runs after every Bash call: only commands that start, resume or claim a run matter, so
  # read the input here and leave without starting Python for everything else.
  hook-bind)
    has_config || exit 0
    SDD_HOOK_PAYLOAD="$(cat)"
    case "$SDD_HOOK_PAYLOAD" in *".sdd/bin/sdd"*) export SDD_HOOK_PAYLOAD ;; *) exit 0 ;; esac
    ;;
  # Runs before every Bash call: Python starts only for commands that could touch a gate,
  # run state, the trust store or the bot token.
  hook-shell-guard)
    has_config || exit 0
    SDD_HOOK_PAYLOAD="$(cat)"
    case "$SDD_HOOK_PAYLOAD" in
      *sdd*|*specsteward*|*.claude*|*TOKEN*) export SDD_HOOK_PAYLOAD ;;
      *env*|*set*|*declare*|*compgen*)
        [ -n "${SDD_PHONE_SESSION:-}" ] || exit 0  # set by claude-phone
        export SDD_HOOK_PAYLOAD ;;
      *) exit 0 ;;
    esac
    ;;
  hook-*) has_config || exit 0 ;;
  # The status line refreshes often; with no run there is nothing to show.
  statusline) { has_config && [ -f "$CONFIG_DIR/.sdd/state.json" ]; } || exit 0 ;;
esac

pick_python
exec "${PYTHON[@]}" "$PLUGIN_ROOT/scripts/sdd_entry.py" "$@"
