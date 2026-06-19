#!/usr/bin/env bash
# Dump palette data (detailed scan mode)
set -euo pipefail
cd "$(dirname "$0")"

export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-dummy}"
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"

echo "Scanning for palette data (detailed, ~20s)..."
mame superman \
  -rompath "./roms" \
  -video none -sound none -nothrottle -skip_gameinfo \
  -seconds_to_run 25 \
  -autoboot_script "dump_palette.lua" -autoboot_delay 0 \
  -nvram_directory ./nvram -cfg_directory ./cfg \
  2>&1 || true

echo "Done."
