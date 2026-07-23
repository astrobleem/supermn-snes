#!/usr/bin/env bash
# Assemble the 68K interpreter (src/interp.pasm -> src/interp.bin) and build the
# full-ROM HiROM harness (build/interp.sfc). Run from the repo root.
set -euo pipefail
export DOTNET_ROOT=/home/chad/.dotnet10
export PATH="$DOTNET_ROOT:$PATH"
POPPY=/home/chad/poppy/src/Poppy.CLI/bin/Release/net10.0/poppy.dll
cd "$(dirname "$0")/.."
dotnet "$POPPY" -t snes -I . -o src/interp.bin -s src/interp.sym src/interp.pasm
# video subsystem + TAD sound module. Poppy has no .include, so concatenate: video.pasm (supervisor)
# + tad_glue.pasm (LoadAudioData + blob symbols + `.org $9000`) + tad_audio.pasm (byte-verified port of
# TAD's ca65 host API; regen with soundwork/tad/port/regen.sh). The TAD code occupies the bank-$E9 tail
# past all pinned resume PCs; internal jsl calls are pre-forced to bank $E9.
mkdir -p build
if [ -f soundwork/tad/port/tad_audio.pasm ]; then
  # ensure the TAD audio-data blob + its generated symbol equates exist (both gitignored; regen
  # from the vendored tad-compiler + the consolidated project). build_interp_rom.py .incbin's the
  # blob at $ED:002B (segment offset 43 — see tad_glue.pasm).
  [ -f soundwork/tad/build/audio-data.bin ] && [ -f soundwork/tad/build/tad_blob_syms.pasm ] || soundwork/tad/build_blob.sh
  cat src/video.pasm soundwork/tad/build/tad_blob_syms.pasm soundwork/tad/port/tad_glue.pasm soundwork/tad/port/tad_audio.pasm > build/video_full.pasm
  dotnet "$POPPY" -t snes -I . -o src/video.bin -s src/video.sym build/video_full.pasm
else
  dotnet "$POPPY" -t snes -I . -o src/video.bin -s src/video.sym src/video.pasm
fi
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
# Escape bank (native escapes too big for bank-$00 gaps; runs at SA-1 $92:8000, file $290000).
# Refresh its bank-$00 symbol constants from interp.sym (+ escbank2/3 and the two FIXED bank-$99
# callable addresses) first, then assemble.  It must precede bank $99 now because the round-start
# roots there import a fresh ibridge/entry_ce58 address from this bank.
if [ -f src/escbank.pasm ]; then
  python3 tools/gen_escbank_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank.bin -s src/escbank.sym src/escbank.pasm
fi
# FIFTH escape bank ($99:8000, file $2C8000) — the $023-25xxx trap#5-cluster SHELL segments.
# Assembled after escbank3/escbank4 AND bank $92: it imports their entry_X addresses plus the
# callable bridge/continuation used by the production round-start initial coroutine roots.
if [ -f src/escbank5.pasm ]; then
  python3 tools/gen_escbank5_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank5.bin -s src/escbank5.sym src/escbank5.pasm
fi
# SIXTH escape bank ($95:8000, file $2A8000) — round-start overflow bank.  It
# imports bank-$92 ibridge, so assemble it after escbank and before xlat data.
if [ -f src/escbank6.pasm ]; then
  python3 tools/gen_escbank6_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank6.bin -s src/escbank6.sym src/escbank6.pasm
fi
# SEVENTH escape bank ($9D:8000, file $2E8000) -- the first full bank after
# the production TAD blob. It currently imports only fresh bank-$97 semantic
# continuations plus guarded late-combat table entries.
if [ -f src/escbank7.pasm ]; then
  python3 tools/gen_escbank7_bodies.py
  python3 tools/gen_escbank7_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank7.bin -s src/escbank7.sym src/escbank7.pasm
fi
# EIGHTH escape bank ($9E:8000, file $2F0000) -- bounded object-spawn spike
# paths. It imports the freshly assembled bank-$99 loop continuation and the
# bank-$00 helper addresses, then contributes two sparse xlat targets.
if [ -f src/escbank8.pasm ]; then
  python3 tools/gen_escbank8_bodies.py
  python3 tools/gen_escbank8_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank8.bin -s src/escbank8.sym src/escbank8.pasm
fi
# AOT address-translation table (68K PC -> native escape entry); needs all escape-bank .sym files.
if [ -f src/escbank.sym ]; then
  python3 tools/gen_xlat_table.py
fi
python3 tools/build_interp_rom.py
