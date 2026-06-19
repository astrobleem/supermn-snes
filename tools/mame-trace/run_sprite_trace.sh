#!/usr/bin/env bash
# Run the Superman sprite register trace headlessly in MAME.
# Produces sprite_trace.log in this directory.
set -euo pipefail
cd "$(dirname "$0")"

MAME="${MAME:-mame}"
FRAMES="${SPRITE_FRAMES:-9000}"
# Give MAME enough wall-clock seconds to run all frames
SECS=$(( FRAMES / 60 + 30 ))
LOG="sprite_trace.log"

export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-dummy}"
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"

if ! command -v "$MAME" >/dev/null 2>&1; then
  echo "ERROR: MAME binary '$MAME' not found." >&2
  exit 1
fi

echo "Tracing superman sprites for $FRAMES frames (~$((FRAMES/60))s); log -> $LOG"

# Use -seconds_to_run as a hard cap but let the Lua script control the actual frame count
"$MAME" superman \
  -rompath "./roms" \
  -video none -sound none -nothrottle -skip_gameinfo \
  -seconds_to_run "$SECS" \
  -autoboot_script "trace_sprites.lua" -autoboot_delay 1 \
  -nvram_directory ./nvram -cfg_directory ./cfg \
  2>&1 || true

echo
echo "=== log output ==="
cat "$LOG"
