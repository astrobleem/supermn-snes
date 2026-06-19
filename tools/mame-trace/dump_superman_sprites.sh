#!/usr/bin/env bash
# Dump Superman sprite data from MAME
set -euo pipefail
cd "$(dirname "$0")"

export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-dummy}"
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"

echo "Dumping Superman sprites from MAME (will take ~30s)..."
mame superman \
  -rompath "./roms" \
  -video none -sound none -nothrottle -skip_gameinfo \
  -seconds_to_run 35 \
  -autoboot_script "dump_superman_sprites.lua" -autoboot_delay 0 \
  -nvram_directory ./nvram -cfg_directory ./cfg \
  2>&1 || true

if [ -f superman_sprites.txt ]; then
    echo "Sprite data dumped: $(wc -l < superman_sprites.txt) lines"
else
    echo "ERROR: superman_sprites.txt not created"
fi
