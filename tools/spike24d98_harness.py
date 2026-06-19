#!/usr/bin/env python3
"""
G2 differential harness for the $24D98 spike (timer-countdown/clamp).
Parses MAME goldens (goldens_24d98.txt: "VEC id timer active f8 delta flags
WRITES a:v:m,..."), builds the WRAM input records + per-vector expected output
slot (input patched with MAME's writes), and checks Mesen's output against it.

WRAM record (16 bytes, little-endian): +0 id +2 timer +4 active_lo +6 active_hi
  +8 f8 +12 delta +14 flags. active is stored 0x00010000 (lo=0,hi=1).
Arcade write addresses map to slot fields (68K big-endian long for active):
  F03702->id(+0)  F03704->timer(+2)  F03706->active_hi(+6)  F03708->active_lo(+4)
  F0370A->f8(+8)

  prep            -> JSON blob to poke
  check <outhex>  -> compare Mesen output records to expected
"""
import json
import re
import sys
from pathlib import Path

BIN = Path("src/spike24d98.bin")
GOLD = Path("tools/mame-trace/goldens_24d98.txt")
CODE_LEN = None
VEC_OFF, VEC_LEN = 0x7FE0, 0x20
BASE = 0x2200            # WRAM record base (snesWorkRam offset)
STRIDE = 16
WR_MAP = {0xF03702: ("id", 0), 0xF03704: ("timer", 2),
          0xF03706: ("active_hi", 6), 0xF03708: ("active_lo", 4),
          0xF0370A: ("f8", 8)}


def load():
    vecs = []
    for line in GOLD.read_text().splitlines():
        line = line.strip()
        if not line.startswith("VEC"):
            continue
        head, _, wr = line.partition("WRITES")
        _, idv, timer, active, f8, delta, flags = head.split()
        rec = {"id": int(idv, 16), "timer": int(timer, 16),
               "active_lo": 0x0000, "active_hi": 0x0001,  # active != 0
               "f8": int(f8, 16), "delta": int(delta, 16), "flags": int(flags, 16)}
        # expected = input slot patched with MAME writes
        exp = {"id": rec["id"], "timer": rec["timer"], "f8": rec["f8"],
               "active_lo": rec["active_lo"], "active_hi": rec["active_hi"]}
        for w in wr.strip().split(","):
            if not w:
                continue
            addr, val, _mask = w.split(":")
            field = WR_MAP.get(int(addr, 16))
            if field:
                exp[field[0]] = int(val, 16) & 0xFFFF
        vecs.append({"in": rec, "exp": exp})
    return vecs


def le16(v):
    return bytes([v & 0xFF, (v >> 8) & 0xFF])


def prep():
    b = BIN.read_bytes()
    # code length = last nonzero byte in low region
    end = max(i for i in range(0x4000) if b[i] != 0)
    vecs = load()
    arr = bytearray()
    for v in vecs:
        r = v["in"]
        rec = (le16(r["id"]) + le16(r["timer"]) + le16(r["active_lo"]) +
               le16(r["active_hi"]) + le16(r["f8"]) + le16(0) +
               le16(r["delta"]) + le16(r["flags"]))
        assert len(rec) == STRIDE
        arr += rec
    print(json.dumps({
        "codeHex": b[:end + 1].hex(), "codeLen": end + 1,
        "vecHex": b[VEC_OFF:VEC_OFF + VEC_LEN].hex(), "vecAddr": VEC_OFF,
        "countHex": le16(len(vecs)).hex(), "countAddr": 0x2000,
        "inputsHex": arr.hex(), "inputsAddr": BASE,
        "outputsAddr": BASE, "outputsLen": len(vecs) * STRIDE, "n": len(vecs),
    }))


def check(outhex):
    vecs = load()
    data = bytes.fromhex(outhex)
    fails = 0
    print(f"{'#':>2} {'id':>4} {'tmr':>5} {'act':>5} {'f8':>4}   exp(id,tmr,act,f8)   result")
    for i, v in enumerate(vecs):
        o = i * STRIDE
        got = {
            "id": data[o] | (data[o + 1] << 8),
            "timer": data[o + 2] | (data[o + 3] << 8),
            "active_lo": data[o + 4] | (data[o + 5] << 8),
            "active_hi": data[o + 6] | (data[o + 7] << 8),
            "f8": data[o + 8] | (data[o + 9] << 8),
        }
        e = v["exp"]
        ok = all(got[k] == e[k] for k in ("id", "timer", "active_lo", "active_hi", "f8"))
        if not ok:
            fails += 1
        act = (got["active_hi"] << 16) | got["active_lo"]
        eact = (e["active_hi"] << 16) | e["active_lo"]
        print(f"{i:2} {got['id']:4X} {got['timer']:5X} {act:5X} {got['f8']:4X}   "
              f"({e['id']:X},{e['timer']:X},{eact:X},{e['f8']:X})   "
              f"{'PASS' if ok else 'FAIL'}")
    print(f"\n{len(vecs)-fails}/{len(vecs)} vectors match MAME golden  "
          f"({'ALL GREEN' if fails==0 else str(fails)+' FAIL'})")
    return fails


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "check":
        sys.exit(1 if check(sys.argv[2]) else 0)
    prep()
