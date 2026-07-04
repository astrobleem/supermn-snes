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
# THIRD escape bank ($97:8000, file $2B8000) — hosts entry_25110 (collision), whose 8KB body
# overflowed its bank-$00 inline gap. References only bank-$00 targets (like escbank2). Assembled BEFORE escbank
# so gen_escbank_syms harvests a FRESH escbank3.sym (escbank jah2 arms jml into $97).
if [ -f src/escbank3.pasm ]; then
  python3 tools/gen_escbank3_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank3.bin -s src/escbank3.sym src/escbank3.pasm
fi
# FOURTH escape bank ($98:8000, file $2C0000) — the $023xxx trap#5-cluster family. Like escbank3:
# bank-$00 refs only; assembled BEFORE escbank.
if [ -f src/escbank4.pasm ]; then
  python3 tools/gen_escbank4_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank4.bin -s src/escbank4.sym src/escbank4.pasm
fi
# FIFTH escape bank ($99:8000, file $2C8000) — the $023-25xxx trap#5-cluster SHELL segments.
# Assembled AFTER escbank3/escbank4 (imports their entry_X addresses for cross-bank jml.l links).
if [ -f src/escbank5.pasm ]; then
  python3 tools/gen_escbank5_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank5.bin -s src/escbank5.sym src/escbank5.pasm
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
