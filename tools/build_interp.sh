#!/usr/bin/env bash
# Assemble the 68K interpreter (src/interp.pasm -> src/interp.bin) and build the
# full-ROM HiROM harness (build/interp.sfc). Run from the repo root.
set -euo pipefail
export DOTNET_ROOT=/home/chad/.dotnet10
export PATH="$DOTNET_ROOT:$PATH"
POPPY=/home/chad/poppy/src/Poppy.CLI/bin/Release/net10.0/poppy.dll
cd "$(dirname "$0")/.."
dotnet "$POPPY" -t snes -I . -o src/interp.bin src/interp.pasm
python3 tools/build_interp_rom.py
