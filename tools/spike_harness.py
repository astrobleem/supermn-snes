#!/usr/bin/env python3
"""
G2 differential-harness helper for the $412 spike.

prep  : emit the hex blobs to poke into Mesen (code patch, vectors, WRAM inputs,
        count) plus the golden expectations parsed from MAME's goldens_412.txt.
check : given the hex read back from WRAM $7E2400 (stride 4: rem@+0, quot@+2),
        compare every element to the MAME goldens and print PASS/FAIL.

Usage:
  spike_harness.py prep
  spike_harness.py check <outputs_hex>
"""
import json
import sys
from pathlib import Path

BIN = Path("src/spike412.bin")
GOLD = Path("tools/mame-trace/goldens_412.txt")
CODE_LEN = 261
VEC_OFF, VEC_LEN = 0x7FE0, 0x20


def load_goldens():
    rows = []
    for line in GOLD.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        inp, out, d7, ccr = line.split()
        rows.append({
            "input": int(inp, 16),
            "rem": int(out, 16),
            "quot": (int(d7, 16) >> 16) & 0xFFFF,
            "ccr": int(ccr, 16),
        })
    return rows


def prep():
    b = BIN.read_bytes()
    gold = load_goldens()
    n = len(gold)
    # WRAM input array, stride 4, little-endian word at +0
    inp = bytearray()
    for g in gold:
        v = g["input"] & 0xFFFF
        inp += bytes([v & 0xFF, v >> 8, 0, 0])
    out = {
        "codeHex": b[:CODE_LEN].hex(),
        "codeAddr": 0,
        "vecHex": b[VEC_OFF:VEC_OFF + VEC_LEN].hex(),
        "vecAddr": VEC_OFF,
        "countHex": bytes([n & 0xFF, n >> 8]).hex(),
        "countAddr": 0x2000,
        "inputsHex": inp.hex(),
        "inputsAddr": 0x2200,
        "outputsAddr": 0x2400,
        "outputsLen": n * 4,
        "n": n,
        "goldens": gold,
    }
    print(json.dumps(out))


def check(outhex):
    gold = load_goldens()
    data = bytes.fromhex(outhex)
    fails = 0
    print(f"{'in':>6} {'exp_rem':>7} {'got_rem':>7} {'exp_q':>6} {'got_q':>6}  result")
    for i, g in enumerate(gold):
        rem = data[i * 4] | (data[i * 4 + 1] << 8)
        quot = data[i * 4 + 2] | (data[i * 4 + 3] << 8)
        ok = (rem == g["rem"] and quot == g["quot"])
        if not ok:
            fails += 1
        print(f"{g['input']:06X} {g['rem']:7X} {rem:7X} {g['quot']:6X} {quot:6X}  "
              f"{'PASS' if ok else 'FAIL'}")
    print(f"\n{len(gold)-fails}/{len(gold)} vectors match MAME golden  "
          f"({'ALL GREEN' if fails==0 else str(fails)+' FAIL'})")
    return fails


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "check":
        sys.exit(1 if check(sys.argv[2]) else 0)
    prep()
