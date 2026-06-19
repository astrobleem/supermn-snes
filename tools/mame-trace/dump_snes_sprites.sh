#!/usr/bin/env bash
# Dump SNES-formatted sprite data from MAME
set -euo pipefail
cd "$(dirname "$0")"

export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-dummy}"
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"

echo "Dumping SNES sprite data from MAME (will take ~10s)..."
mame superman \
  -rompath "./roms" \
  -video none -sound none -nothrottle -skip_gameinfo \
  -seconds_to_run 15 \
  -autoboot_script "dump_snes_sprites.lua" -autoboot_delay 0 \
  -nvram_directory ./nvram -cfg_directory ./cfg \
  2>&1 || true

echo "Done."
ls -la snes_oam.bin snes_oam.txt 2>/dev/null
