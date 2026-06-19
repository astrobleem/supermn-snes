#!/usr/bin/env python3
"""vgm_extract_adpcm — extract & decode YM2610 ADPCM-A percussion from a VGM.

Pipeline (see CONVERTSOUND.md steps 5-7):
  1. reconstruct the ADPCM-A sample ROM from the VGM's type-0x82 data blocks,
  2. find every distinct sample window from ADPCM-A start/end register writes
     (vgm_ym2610 already collects these),
  3. cut each window and decode YM2610 ADPCM-A (NOT generic IMA) to 16-bit mono WAV
     at the native ~18.5 kHz ADPCM-A rate.

The decoded WAVs are the drum-kit source material; trim/loop them and encode to BRR
for the TAD instruments named by vgm2mml (sm_drum_XXXXXX).

Usage:
  python3 tools/sound/vgm_extract_adpcm.py "soundwork/source/vgm_unpacked/03 Main BGM 1.vgm" \
      -o soundwork/samples
"""
from __future__ import annotations
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vgmlib
import vgm_ym2610 as ym

# YM2610 ADPCM-A nominal sample rate at the 8 MHz chip clock.
ADPCMA_RATE = 18518

# Yamaha ADPCM-A decode tables (shared with ADPCM-B / OKI-style 4-bit ADPCM).
_STEP_TABLE = [
    16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66,
    73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253,
    279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876,
    963, 1060, 1166, 1282, 1411, 1552,
]
_STEP_ADJUST = [-1, -1, -1, -1, 2, 5, 7, 9]


def decode_adpcm_a(data: bytes):
    """Decode Yamaha ADPCM-A nibbles -> list[int16]. High nibble first per byte."""
    out = []
    acc = 0
    step_idx = 0
    for byte in data:
        for nib in (byte >> 4, byte & 0x0F):
            step = _STEP_TABLE[step_idx]
            # Yamaha delta = step * (1/8 + bit2/4 + bit1/2 + bit0) with sign bit3
            delta = (step >> 3)
            if nib & 1:
                delta += step >> 2
            if nib & 2:
                delta += step >> 1
            if nib & 4:
                delta += step
            if nib & 8:
                acc -= delta
            else:
                acc += delta
            acc = max(-32768, min(32767, acc))
            out.append(acc)
            step_idx += _STEP_ADJUST[nib & 7]
            step_idx = max(0, min(48, step_idx))
    return out


def reconstruct_rom(path):
    """Reassemble the ADPCM-A sample ROM from type-0x82 data blocks."""
    data = vgmlib.read_vgm(path)
    h = vgmlib.parse_header(data)
    pieces = []
    rom_size = [0]

    def on_block(bt, payload):
        if bt == 0x82 and len(payload) >= 8:
            sz, start = struct.unpack_from("<II", payload, 0)
            rom_size[0] = max(rom_size[0], sz)
            pieces.append((start, payload[8:]))

    vgmlib.walk(data, h, lambda *_: None, lambda *_: None, on_block)
    rom = bytearray(rom_size[0])
    for start, chunk in pieces:
        rom[start:start + len(chunk)] = chunk
    return bytes(rom)


def write_wav(path: Path, samples, rate):
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = struct.pack("<%dh" % len(samples), *samples)
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, rate, rate * 2, 2, 16)
    data = struct.pack("<4sI", b"data", len(pcm)) + pcm
    riff = b"RIFF" + struct.pack("<I", 4 + len(fmt) + len(data)) + b"WAVE" + fmt + data
    path.write_bytes(riff)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vgm")
    ap.add_argument("-o", "--outdir", default="soundwork/samples")
    ap.add_argument("--rate", type=int, default=ADPCMA_RATE)
    args = ap.parse_args()

    rom = reconstruct_rom(args.vgm)
    tr = ym.decode(args.vgm)
    outdir = Path(args.outdir)
    stem = Path(args.vgm).stem

    # save the raw ROM for reference
    rom_path = outdir / "adpcma_rom" / f"{stem}.adpcma.rom.bin"
    rom_path.parent.mkdir(parents=True, exist_ok=True)
    rom_path.write_bytes(rom)
    print(f"ADPCM-A ROM: {len(rom)} bytes -> {rom_path}")

    if not tr.drum_samples:
        print("no ADPCM-A sample windows found")
        return

    print(f"{len(tr.drum_samples)} distinct sample windows:")
    for st in sorted(tr.drum_samples):
        s = tr.drum_samples[st]
        start, end = s["start"], min(s["end"], len(rom) - 1)
        window = rom[start:end + 1]
        pcm = decode_adpcm_a(window)
        # pad to a multiple of 16 samples (BRR-friendly)
        if len(pcm) % 16:
            pcm += [0] * (16 - len(pcm) % 16)
        wav = outdir / "decoded_wav" / f"{stem}_a_{start:06x}_{end:06x}.wav"
        write_wav(wav, pcm, args.rate)
        dur = len(pcm) / args.rate
        print(f"  0x{start:06X}-0x{end:06X}  {len(window):5d}B -> "
              f"{len(pcm):5d} samples ({dur*1000:.0f} ms) x{s['count']} hits -> {wav.name}")


if __name__ == "__main__":
    main()
