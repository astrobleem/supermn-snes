#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: bash tools/run_optest_filter.sh FILTER [MAX_STEP_FRAMES]" >&2
  echo "Runs tools/optest.py with a bounded OPTEST_FILTER." >&2
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage
  exit 2
fi

filter=$1
max_step_frames=${2:-120}

if [[ -z "$filter" ]]; then
  echo "run_optest_filter: FILTER must not be empty" >&2
  exit 2
fi

if [[ ! "$max_step_frames" =~ ^[0-9]+$ ]]; then
  echo "run_optest_filter: MAX_STEP_FRAMES must be an integer" >&2
  exit 2
fi

case "$filter" in
  *$'\n'*|*$'\r'*)
    echo "run_optest_filter: FILTER must be a single line" >&2
    exit 2
    ;;
esac

export OPTEST_FILTER="$filter"
export OPTEST_MAX_STEP_FRAMES="$max_step_frames"

exec python3 tools/optest.py
