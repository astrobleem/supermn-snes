#!/usr/bin/env bash
# Assemble the 68K interpreter (src/interp.pasm -> src/interp.bin) and build the
# full-ROM HiROM harness (build/interp.sfc). Run from the repo root.
set -euo pipefail
export DOTNET_ROOT=/home/chad/.dotnet10
export PATH="$DOTNET_ROOT:$PATH"
POPPY=/home/chad/poppy/src/Poppy.CLI/bin/Release/net10.0/poppy.dll
cd "$(dirname "$0")/.."
dotnet "$POPPY" -t snes -I . -o src/interp.bin -s src/interp.sym src/interp.pasm
dotnet "$POPPY" -t snes -I . -o src/video.bin src/video.pasm
# SECOND escape bank ($94:8000, file $2A0000) — assembled FIRST so its entry_X addresses can be fed
# into escbank.pasm below for cross-bank `jml entry_X` dispatch (escbank2 references only bank-$00
# targets -> no circular dependency). Skipped if src/escbank2.pasm is absent.
if [ -f src/escbank2.pasm ]; then
  python3 tools/gen_escbank2_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank2.bin -s src/escbank2.sym src/escbank2.pasm
fi
# Escape bank (native escapes too big for bank-$00 gaps; runs at SA-1 $92:8000, file $290000).
# Refresh its bank-$00 symbol constants from interp.sym (+ escbank2 entry_X) first (addresses shift
# when interp.pasm changes), then assemble. Skipped if src/escbank.pasm is absent.
if [ -f src/escbank.pasm ]; then
  python3 tools/gen_escbank_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank.bin -s src/escbank.sym src/escbank.pasm
fi
# AOT address-translation table (68K PC -> native escape entry); needs both escbank .sym files.
if [ -f src/escbank.sym ]; then
  python3 tools/gen_xlat_table.py
fi
python3 tools/build_interp_rom.py
