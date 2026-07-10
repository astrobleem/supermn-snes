#!/usr/bin/env python3
"""vgm_fm_patches.py — capture + dedupe YM2610 FM patches from VGM register logs.

For every FM key-on in each VGM, snapshot the channel's complete voice state
(4 ops x {DT/MUL, TL, KS/AR, AM/DR, SR, SL/RR, SSG-EG} + FB/ALG + AMS/PMS + the
global LFO reg 0x22) and the note (block/fnum). Dedupe patches across all input
files with carrier-operator TL (= mix volume) normalized out, so one musical
timbre played at several volumes is ONE patch.

Output: a JSON library (patches, per-(file,channel) usage with note histograms)
that the render step turns into looped WAVs, one TAD instrument per patch.

YM2610 FM register model (OPN family):
  - 4 FM channels: key-on selector values {1,2,5,6} (bit2 = part, low bits = ch
    offset 1/2 within the part; ch offsets 0/3 don't exist on YM2610).
  - Per-part regs 0x30..0x9F: reg = base + slot*4 + choff, slot order S1,S3,S2,S4
    at +0,+4,+8,+12 (we keep raw slot order; the renderer replays raw regs).
  - 0xB0+choff = feedback/algorithm; 0xB4+choff = pan/AMS/PMS (pan excluded from
    patch identity); 0xA4/0xA0 = block/fnum (note, not part of the patch).
  - Carriers by algorithm (op1..op4 = S1,S2,S3,S4 -> reg slot offsets 0,8,4,12):
    alg 0-3: op4; alg 4: op2,op4; alg 5,6: op2,op3,op4; alg 7: all four.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

import vgmlib

# key-on selector value -> (part, channel-offset, fm index 0..3)
KEYON_MAP = {1: (0, 1, 0), 2: (0, 2, 1), 5: (1, 1, 2), 6: (1, 2, 3)}
OP_BASES = (0x30, 0x40, 0x50, 0x60, 0x70, 0x80, 0x90)  # DT/MUL,TL,KS/AR,AM/DR,SR,SL/RR,SSG
SLOT_OFFS = (0, 4, 8, 12)                              # raw register slot order S1,S3,S2,S4
# algorithm -> carrier reg-slot offsets (see module docstring)
CARRIER_SLOTS = {
    0: (12,), 1: (12,), 2: (12,), 3: (12,),
    4: (8, 12),
    5: (4, 8, 12), 6: (4, 8, 12),
    7: (0, 4, 8, 12),
}


def fnum_to_freq(block: int, fnum: int, clock: int) -> float:
    if fnum == 0:
        return 0.0
    return fnum * clock / (144.0 * (1 << (21 - block)))


def freq_to_note(f: float) -> str:
    if f <= 0:
        return "?"
    names = "c c+ d d+ e f f+ g g+ a a+ b".split()
    n = 12.0 * math.log2(f / 440.0) + 69.0
    ni = int(round(n))
    return f"{names[ni % 12]}{ni // 12 - 1}"


def capture_file(path: Path) -> dict:
    data = vgmlib.read_vgm(path)
    hdr = vgmlib.parse_header(data)
    regs = [dict(), dict()]          # [part][reg] -> val shadow
    lfo = 0                          # global reg 0x22
    events = []                      # (time, fmidx, patch_bytes, carrier_tls, block, fnum)
    t = [0]

    def snapshot(part: int, choff: int):
        p = regs[part]
        raw = []
        for base in OP_BASES:
            for so in SLOT_OFFS:
                raw.append(p.get(base + so + choff, 0))
        b0 = p.get(0xB0 + choff, 0)
        b4 = p.get(0xB4 + choff, 0)
        raw.append(b0)
        raw.append(b4 & 0x37)        # exclude pan bits 7:6
        raw.append(lfo & 0x0F)       # LFO enable+freq
        # normalize carrier TLs out of the identity; keep them separately
        alg = b0 & 7
        car = CARRIER_SLOTS[alg]
        ident = list(raw)
        carrier_tls = []
        for so in car:
            idx = 4 + SLOT_OFFS.index(so)  # TL block starts at raw[4]
            carrier_tls.append(raw[idx])
            ident[idx] = 0
        return bytes(raw), bytes(ident), carrier_tls

    def on_write(port, reg, val):
        nonlocal lfo
        if port == 0 and reg == 0x22:
            lfo = val
            return
        if port == 0 and reg == 0x28:
            sel = val & 0x07
            if sel in KEYON_MAP and (val & 0xF0):     # any slot keyed on
                part, choff, fmidx = KEYON_MAP[sel]
                raw, ident, ctl = snapshot(part, choff)
                p = regs[part]
                blk_fn = p.get(0xA4 + choff, 0)
                fnum = ((blk_fn & 7) << 8) | p.get(0xA0 + choff, 0)
                block = (blk_fn >> 3) & 7
                events.append((t[0], fmidx, raw, ident, ctl, block, fnum))
            return
        regs[port][reg] = val

    vgmlib.walk(data, hdr, on_write, lambda n: t.__setitem__(0, t[0] + n))
    return {"clock": hdr.ym2610_clock, "events": events}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("vgms", nargs="+")
    ap.add_argument("-o", "--out", default="soundwork/samples/fm_patches.json")
    args = ap.parse_args()

    patches = {}      # ident -> {"id", "raw" (loudest instance), "min_tl", uses}
    usage = {}        # (file, fmidx) -> {"patch_hist": {pid: n}, "note_hist": {...}}
    clock = None
    for vp in sorted(args.vgms):
        vp = Path(vp)
        cap = capture_file(vp)
        clock = cap["clock"]
        for (tt, fmidx, raw, ident, ctl, block, fnum) in cap["events"]:
            key = ident.hex()
            e = patches.setdefault(key, {"id": len(patches), "raw": raw.hex(),
                                         "min_carrier_tl": 127, "keyons": 0})
            e["keyons"] += 1
            mtl = min(ctl) if ctl else 127
            if mtl < e["min_carrier_tl"]:        # loudest instance defines the render TLs
                e["min_carrier_tl"] = mtl
                e["raw"] = raw.hex()
            u = usage.setdefault((vp.stem, fmidx), {"patch_hist": {}, "note_hist": {}})
            u["patch_hist"][e["id"]] = u["patch_hist"].get(e["id"], 0) + 1
            f = fnum_to_freq(block, fnum, clock)
            note = freq_to_note(f)
            nh = u["note_hist"].setdefault(e["id"], {})
            nh[f"{note}|{block}|{fnum}"] = nh.get(f"{note}|{block}|{fnum}", 0) + 1

    plist = sorted(patches.values(), key=lambda e: e["id"])
    out = {
        "ym2610_clock": clock,
        "n_patches": len(plist),
        "patches": plist,
        "usage": [
            {"track": k[0], "fm_voice": k[1],
             "patch_hist": v["patch_hist"],
             "note_hist": v["note_hist"]}
            for k, v in sorted(usage.items())
        ],
        "_raw_layout": "28 op bytes (7 reg-groups x slots S1,S3,S2,S4) + B0 + B4&0x37 + LFO",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"{len(plist)} unique patches from {len(args.vgms)} files -> {args.out}")
    for e in plist:
        print(f"  patch {e['id']:2d}: keyons={e['keyons']:5d} minTL={e['min_carrier_tl']:3d} "
              f"alg={int(e['raw'][-6:-4],16)&7} fb={(int(e['raw'][-6:-4],16)>>3)&7}")


if __name__ == "__main__":
    main()
