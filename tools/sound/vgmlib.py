#!/usr/bin/env python3
"""vgmlib — shared VGM (Video Game Music log) parsing primitives.

A .vgm/.vgz file is a timed log of sound-chip register writes plus wait commands
on a 44100 Hz timeline. This module provides the low-level reader, header parsing,
and a command walker that the Superman (YM2610) conversion tools build on.

It is chip-agnostic at this layer: it understands the VGM container/command grammar
and hands each command to a callback. The YM2610-specific interpretation (FM/SSG/
ADPCM register meaning) lives in vgm_ym2610.py.

References:
  VGM spec: https://vgmrips.net/wiki/VGM_Specification
"""
from __future__ import annotations
import gzip
import struct
from dataclasses import dataclass, field
from pathlib import Path

VGM_RATE = 44100  # all VGM wait values are expressed in samples at 44100 Hz


def read_vgm(path) -> bytes:
    """Read a .vgm or .vgz file, transparently gunzipping .vgz (gzip magic)."""
    data = Path(path).read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    if data[:4] != b"Vgm ":
        raise ValueError(f"not a VGM file: {path}")
    return data


def _u32(data: bytes, off: int) -> int:
    if off + 4 > len(data):
        return 0
    return struct.unpack_from("<I", data, off)[0]


@dataclass
class VgmHeader:
    version: int
    data_start: int
    total_samples: int
    loop_offset: int          # absolute byte offset of loop point, or 0
    loop_samples: int
    ym2610_clock: int
    ym2610b: bool
    rate: int                 # nominal frame rate field (50/60), informational
    gd3: dict = field(default_factory=dict)

    @property
    def total_seconds(self) -> float:
        return self.total_samples / VGM_RATE

    @property
    def loop_seconds(self) -> float:
        return self.loop_samples / VGM_RATE


def _parse_gd3(data: bytes) -> dict:
    off = _u32(data, 0x14)
    if off == 0:
        return {}
    pos = 0x14 + off
    if data[pos:pos + 4] != b"Gd3 ":
        return {}
    # 12-byte Gd3 header, then a run of UTF-16LE null-terminated strings.
    str_start = pos + 12
    raw = data[str_start:]
    fields = []
    cur = bytearray()
    i = 0
    while i + 1 < len(raw) and len(fields) < 11:
        ch = raw[i] | (raw[i + 1] << 8)
        i += 2
        if ch == 0:
            fields.append(cur.decode("utf-16le", "replace"))
            cur = bytearray()
        else:
            cur += raw[i - 2:i]
    keys = ["track_en", "track_jp", "game_en", "game_jp", "system_en",
            "system_jp", "author_en", "author_jp", "date", "vgm_by", "notes"]
    return {k: v for k, v in zip(keys, fields)}


def parse_header(data: bytes) -> VgmHeader:
    version = _u32(data, 0x08)
    total_samples = _u32(data, 0x18)
    loop_off_rel = _u32(data, 0x1C)
    loop_offset = (0x1C + loop_off_rel) if loop_off_rel else 0
    loop_samples = _u32(data, 0x20)
    rate = _u32(data, 0x24)
    do_raw = _u32(data, 0x34)
    data_start = 0x40 if do_raw == 0 else 0x34 + do_raw
    ym_raw = _u32(data, 0x4C)
    ym2610b = bool(ym_raw & 0x80000000)
    ym_clock = ym_raw & 0x7FFFFFFF
    return VgmHeader(version, data_start, total_samples, loop_offset,
                     loop_samples, ym_clock, ym2610b, rate, _parse_gd3(data))


# --- command walker -------------------------------------------------------

# Number of operand bytes that follow each command byte (the command byte itself
# excluded). Special multi-byte / variable commands are handled inline below.
_FIXED = {
    0x4F: 1, 0x50: 1,
    0x61: 2, 0x62: 0, 0x63: 0, 0x66: 0,
}
for c in range(0x51, 0x60):   # chip register writes: <cmd> <reg> <data>
    _FIXED[c] = 2
for c in range(0x70, 0x80):   # wait n+1
    _FIXED[c] = 0
for c in range(0x80, 0x90):   # YM2612 0x2A + wait
    _FIXED[c] = 0
for c in range(0x30, 0x40):   # reserved single-operand
    _FIXED[c] = 1
for c in range(0xA0, 0xC0):   # 2-operand
    _FIXED[c] = 2
for c in range(0xC0, 0xE0):   # 3-operand
    _FIXED[c] = 3
for c in range(0xE0, 0x100):  # 4-operand
    _FIXED[c] = 4
_DACSTREAM = {0x90: 4, 0x91: 4, 0x92: 5, 0x93: 10, 0x94: 1, 0x95: 4}


def walk(data: bytes, hdr: VgmHeader, on_write, on_wait, on_block=None,
         on_loop=None, stop_at_end=True):
    """Walk the VGM command stream.

    on_write(port, reg, val): a chip register write. For YM2610, port 0 = 0x58
        command, port 1 = 0x59 command.
    on_wait(nsamples): advance the timeline by n samples at 44100 Hz.
    on_block(block_type, payload): a 0x67 data block (e.g. 0x82/0x83 ADPCM ROM).
    on_loop(): called once when the parser reaches the loop point (if known).
    """
    pos = hdr.data_start
    n = len(data)
    loop_fired = False
    while pos < n:
        if on_loop and not loop_fired and hdr.loop_offset and pos >= hdr.loop_offset:
            on_loop()
            loop_fired = True
        cmd = data[pos]
        cpos = pos
        pos += 1
        if cmd == 0x66:
            if stop_at_end:
                break
            continue
        if cmd == 0x67:
            # 0x67 0x66 tt ssssssss <data>
            if data[pos] != 0x66:
                raise ValueError(f"bad data block @0x{cpos:X}")
            block_type = data[pos + 1]
            size = _u32(data, pos + 2)
            payload = data[pos + 6:pos + 6 + size]
            pos += 6 + size
            if on_block:
                on_block(block_type, payload)
            continue
        if cmd == 0x68:
            size = _u32(data, pos + 6)
            pos += 10 + size
            continue
        if cmd == 0x61:
            on_wait(data[pos] | (data[pos + 1] << 8))
            pos += 2
            continue
        if cmd == 0x62:
            on_wait(735)
            continue
        if cmd == 0x63:
            on_wait(882)
            continue
        if 0x70 <= cmd <= 0x7F:
            on_wait((cmd & 0x0F) + 1)
            continue
        if 0x80 <= cmd <= 0x8F:
            # YM2612 DAC + wait (cmd & 0xF). Not used by YM2610 but handle gracefully.
            on_wait(cmd & 0x0F)
            continue
        if 0x51 <= cmd <= 0x5F:
            # YM2610: 0x58 = port 0 write, 0x59 = port 1 write. Other 0x5x are
            # writes to chips this pack doesn't use; consume operands and ignore.
            if cmd == 0x58:
                on_write(0, data[pos], data[pos + 1])
            elif cmd == 0x59:
                on_write(1, data[pos], data[pos + 1])
            pos += 2
            continue
        if 0x90 <= cmd <= 0x95:
            pos += _DACSTREAM[cmd]
            continue
        skip = _FIXED.get(cmd)
        if skip is None:
            raise ValueError(f"unhandled VGM command 0x{cmd:02X} @0x{cpos:X}")
        pos += skip
