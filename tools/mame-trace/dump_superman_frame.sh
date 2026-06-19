#!/usr/bin/env bash
# Dump Superman frame data from MAME
set -euo pipefail
cd "$(dirname "$0")"

export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-dummy}"
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"

echo "Dumping Superman frame from MAME (will take ~10s)..."
mame superman \
  -rompath "./roms" \
  -video none -sound none -nothrottle -skip_gameinfo \
  -seconds_to_run 15 \
  -autoboot_script "dump_superman_frame.lua" -autoboot_delay 0 \
  -nvram_directory ./nvram -cfg_directory ./cfg \
  2>&1 || true

echo "Done."
ls -la superman_frame.* sprite_ram.bin sprite_y.bin sprite_ctrl.bin sprite_entries.txt 2>/dev/null
