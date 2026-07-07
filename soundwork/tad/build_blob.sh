#!/usr/bin/env bash
# build_blob.sh — regenerate the TAD combined audio-data blob for the P1 placeholder song.
#
# Output blob layout (self-contained, from `tad-compiler ca65-export --output-bin`):
#   [ loader.bin (116) ][ audio-driver.bin (3218) ][ Tad_DataTable (8) @ off 3334 ][ common + song data ]
# The Poppy port + build_interp_rom.py .incbin THIS single file (no separate driver blobs needed).
#
# Reproducibility pins (see vendor/VERSION.md): TAD @ 822164b, tad-compiler 0.3.0, cc65 V2.18.
set -euo pipefail
cd "$(dirname "$0")"                       # soundwork/tad

TC="${TAD_COMPILER:-/home/chad/terrific-audio-driver/target/release/tad-compiler}"
PROJECT="${TAD_PROJECT:-mml_drafts/02_coin.terrificaudio}"   # P1 placeholder (8 sine voices, 1 song)
OUT=build
mkdir -p "$OUT"

echo "[build_blob] project=$PROJECT"
"$TC" check "$PROJECT"
# HIROM to match build/interp.sfc. Segment name is irrelevant to the .bin (only labels the .s wrapper).
"$TC" ca65-export --hirom --segment RODATA2 \
    --output-asm "$OUT/audio-data.s" \
    --output-bin "$OUT/audio-data.bin" \
    "$PROJECT"
"$TC" ca65-enums -o "$OUT/audio.inc" "$PROJECT"

echo "[build_blob] wrote:"
ls -l "$OUT/audio-data.bin" "$OUT/audio-data.s" "$OUT/audio.inc"
echo "[build_blob] blob size = $(wc -c < "$OUT/audio-data.bin") bytes"
