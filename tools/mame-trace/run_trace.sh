#!/usr/bin/env bash
# Run the Superman C-Chip access trace headlessly in MAME.
# Produces cchip_trace.log in this directory.
#
# Needs a MAME binary with the Lua memory-tap API (>= ~0.236). Set $MAME to it,
# or have `mame` on PATH. See README.md for how to get one.
set -euo pipefail
cd "$(dirname "$0")"

MAME="${MAME:-mame}"
INJECT="${CCHIP_INJECT:-0}"             # 1 = inject coin+START to reach gameplay
# default frame budget: longer when injecting (needs to reach a level)
if [ -n "${CCHIP_FRAMES:-}" ]; then FRAMES="$CCHIP_FRAMES"
elif [ "$INJECT" = "1" ]; then FRAMES=9000
else FRAMES=1800; fi
SECS=$(( FRAMES / 60 + 5 ))             # hard safety cap above the Lua frame budget
LOG="${CCHIP_LOG:-$( [ "$INJECT" = "1" ] && echo cchip_gameplay.log || echo cchip_trace.log )}"

# Headless: even with -video none, SDL probes for a video device and aborts on a
# machine with no display. The dummy drivers make MAME truly headless.
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-dummy}"
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"

if ! command -v "$MAME" >/dev/null 2>&1; then
  echo "ERROR: MAME binary '$MAME' not found. Set \$MAME or install one (see README.md)." >&2
  exit 1
fi

echo "Tracing superman for $FRAMES frames (~$((FRAMES/60))s, inject=$INJECT); log -> $LOG"
CCHIP_FRAMES="$FRAMES" CCHIP_LOG="$LOG" CCHIP_INJECT="$INJECT" \
"$MAME" superman \
  -rompath "./roms" \
  -video none -sound none -nothrottle -skip_gameinfo \
  -seconds_to_run "$SECS" \
  -autoboot_script "trace_cchip.lua" -autoboot_delay 0 \
  -nvram_directory ./nvram -cfg_directory ./cfg \
  || true   # MAME may return nonzero on scripted exit; the log is what matters

echo
echo "=== verdict tail ==="
grep -E "VERDICT|OBSERVED|OK:|inject:" "$LOG" || echo "(no verdict — check the log / MAME version)"
