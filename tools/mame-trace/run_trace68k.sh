#!/usr/bin/env bash
# Headless 68K execution trace of superman. Produces $T68K_OUT (default
# trace68k.log) with PC+disasm per instruction over a frame window.
# Requires a MAME with the Lua debugger (0.236+); uses -debug -debugger none.
set -euo pipefail
cd "$(dirname "$0")"

MAME="${MAME:-/snap/bin/mame}"
OUT="${T68K_OUT:-trace68k.log}"
FRAMES="${T68K_FRAMES:-600}"
SECS=$(( FRAMES / 60 + 30 ))

export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-dummy}"
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-dummy}"
export T68K_OUT="$OUT" T68K_FRAMES="$FRAMES"

rm -f "$OUT"
echo "Tracing superman 68K for $FRAMES frames -> $OUT"
"$MAME" superman -rompath ./roms -video none -sound none -nothrottle -skip_gameinfo \
  -seconds_to_run "$SECS" -autoboot_script trace68k.lua -autoboot_delay 0 \
  -debug -debugger none -nvram_directory ./nvram -cfg_directory ./cfg \
  2>&1 | grep -E "T68K" || true
echo "lines: $(wc -l < "$OUT")"
