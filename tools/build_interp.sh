#!/usr/bin/env bash
# Assemble the 68K interpreter (src/interp.pasm -> src/interp.bin) and build the
# full-ROM HiROM harness (build/interp.sfc). Run from the repo root.
set -euo pipefail
export DOTNET_ROOT=/home/chad/.dotnet10
export PATH="$DOTNET_ROOT:$PATH"
POPPY=${POPPY_DLL:-/home/chad/poppy-astrobleem-latest/src/Poppy.CLI/bin/Release/net10.0/poppy.dll}
[ -f "$POPPY" ] || { echo "Poppy DLL not found: $POPPY" >&2; exit 1; }
EXPECTED_POPPY_SHA256=715b14431478b62433498cc516c1cbbb8f418c1d7b39a8e71098ed98d9c9167e
POPPY_SHA256=$(sha256sum "$POPPY" | awk '{print $1}')
if [ "$POPPY_SHA256" != "$EXPECTED_POPPY_SHA256" ] && [ "${ALLOW_UNPINNED_POPPY:-0}" != 1 ]; then
  echo "Refusing unpinned Poppy DLL: $POPPY" >&2
  echo "observed: $POPPY_SHA256" >&2
  echo "expected: $EXPECTED_POPPY_SHA256" >&2
  echo "Set ALLOW_UNPINNED_POPPY=1 only for deliberate historical reproduction or compiler adoption." >&2
  exit 1
fi
echo "Poppy DLL: $POPPY"
echo "Poppy SHA-256: $POPPY_SHA256"
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
  python3 tools/gen_stage3_hot_bodies.py
  dotnet "$POPPY" -t snes -I . -o src/escbank2.bin -s src/escbank2.sym src/escbank2.pasm
fi
# FOURTH escape bank ($98:8000, file $2C0000) — the $023xxx trap#5-cluster family. Like escbank3:
# bank-$00 refs plus one fixed bank-$97 re-entry. Assemble it before bank $97
# so the latter can import every movable $01E7C0 continuation from fresh
# symbols instead of retaining stale numeric jumps after a generated repair.
if [ -f src/escbank4.pasm ]; then
  python3 tools/gen_escbank4_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank4.bin -s src/escbank4.sym src/escbank4.pasm
fi
# THIRD escape bank ($97:8000, file $2B8000) — hosts entry_25110 (collision), whose 8KB body
# overflowed its bank-$00 inline gap. It imports the freshly assembled bank-$98
# $01E7C0 continuations, and is itself assembled before escbank so
# gen_escbank_syms harvests a fresh escbank3.sym.
if [ -f src/escbank3.pasm ]; then
  python3 tools/gen_escbank3_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank3.bin -s src/escbank3.sym src/escbank3.pasm
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
# NINTH escape region ($9F:A100+, file $2FA100) -- Stage-3 selector bodies
# placed after the two derived renderer payloads.  It imports the fresh bank
# $92 indirect bridge and must assemble before bank $9D's pinned return
# trampolines are packed.
if [ -f src/escbank9.pasm ]; then
  python3 tools/gen_stage3_scroll_task.py
  python3 tools/gen_stage3_selector.py
  python3 tools/gen_stage3_1337e.py
  python3 tools/gen_stage3_79fe.py
  python3 tools/gen_stage3_27aea.py
  python3 tools/gen_stage3_278e8.py
  python3 tools/gen_stage3_13314.py
  python3 tools/gen_stage3_13282.py
  python3 tools/gen_stage3_2e676.py
  python3 tools/gen_stage3_player_hot.py
  python3 tools/gen_stage3_2f542.py
  python3 tools/gen_escbank9_syms.py
  dotnet "$POPPY" -t snes -I . -o src/escbank9.bin -s src/escbank9.sym src/escbank9.pasm
fi
# Isolated virtual-MC68000-cycle diagnostic banks.  Their `$025110`, `$02429C`,
# and six-player metadata come from freshly generated/assembled escape sources,
# so this must follow those banks.  The `$02429C` diagnostic copy is assembled
# separately for bank `$F3`; ordinary packing routes and packs none of it.
if [ -f src/vtime.pasm ]; then
  python3 tools/gen_vtime_esc3_charge_table.py --manifest build/gen-vtime-esc3-charge-table-build.json
  python3 tools/gen_vtime_esc5_charge_table.py --manifest build/gen-vtime-esc5-charge-table-build.json
  python3 tools/gen_vtime_esc9_charge_table.py --manifest build/gen-vtime-esc9-charge-table-build.json
  python3 tools/gen_vtime_esc5_root.py
  dotnet "$POPPY" -t snes -I . -o src/vtime_esc5_root.bin -s src/vtime_esc5_root.sym src/vtime_esc5_root.pasm
  vtime_source=src/vtime.pasm
  if [ "${VTIME:-0}" = "1" ]; then
    vtime_source=src/vtime_enabled.pasm
  fi
  dotnet "$POPPY" -t snes -I . -o src/vtime.bin -s src/vtime.sym "$vtime_source"
  python3 tools/test_gen_vtime_esc5_root.py
  python3 tools/test_vtime_long_state_writes.py
fi
# SEVENTH escape bank ($9D:8000, file $2E8000) -- the first full bank after
# the production TAD blob. It currently imports only fresh bank-$97 semantic
# continuations plus guarded late-combat table entries.
if [ -f src/escbank7.pasm ]; then
  python3 tools/gen_escbank7_bodies.py
  python3 tools/gen_stage3_draw_wrappers.py
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
python3 tools/test_vtime_build_mode_guard.py
python3 tools/test_vtime_esc5_root_pack.py
python3 tools/test_vtime_irq_entry_pack.py
python3 tools/test_vtime_input_staging_pack.py
if [ "${VTIME:-0}" = "1" ]; then
  # The opt-in cycle-clock image deliberately replaces the legacy five-byte
  # countdown seam.  The ordinary-pack assertion must stay enabled for every
  # production build, but it is inapplicable to this explicitly diagnostic
  # image.
  echo "VTIME diagnostic pack: disabled-pack assertion intentionally skipped"
else
  python3 tools/test_vtime_disabled_pack.py
fi
