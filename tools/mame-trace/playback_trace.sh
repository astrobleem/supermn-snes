#!/usr/bin/env bash
# Play back a recorded MAME input movie (.inp) while tracing the 68K, so a human
# (or longplay) playthrough that reaches deep states (boss/ending/late levels)
# becomes a confirmed-code trace. The .inp must be recorded against THIS ROM and
# MAME version (0.287).
#
#   INP=longplay.inp T68K_START=0 T68K_END=120000 ./playback_trace.sh
set -euo pipefail
cd "$(dirname "$0")"
MAME="${MAME:-/snap/bin/mame}"
INP="${INP:?set INP=path/to/movie.inp}"
OUT="${T68K_OUT:-trace_playback.log}"
START="${T68K_START:-0}"; END="${T68K_END:-7200}"
SECS=$(( END/60 + 30 ))
export SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy
export T68K_OUT="$OUT" T68K_START="$START" T68K_END="$END"
rm -f "$OUT"
echo "Playing back $INP, tracing frames $START-$END -> $OUT"
"$MAME" superman -rompath ./roms -playback "$INP" -video none -sound none -nothrottle \
  -skip_gameinfo -seconds_to_run "$SECS" -autoboot_script trace68k.lua -autoboot_delay 0 \
  -debug -debugger none -nvram_directory ./nvram -cfg_directory ./cfg 2>&1 | grep -E "T68K" || true
echo "lines: $(wc -l < "$OUT" 2>/dev/null || echo 0)"
