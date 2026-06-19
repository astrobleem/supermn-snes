#!/usr/bin/env python3
"""Empirically profile YM2610 usage in a VGM: which FM channels, SSG channels,
ADPCM-A/B channels are actually used, and a register-write histogram.

This is the ground-truth scout: run it before trusting any channel-layout
assumption. It does NOT decode notes — it just reports what the chip is told to do.

Usage:
  python3 tools/sound/vgm_profile.py "soundwork/source/vgm_unpacked/03 Main BGM 1.vgm"
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vgmlib


def profile(path):
    data = vgmlib.read_vgm(path)
    h = vgmlib.parse_header(data)

    reg_hist = Counter()          # (port, reg) -> count
    keyon_vals = Counter()        # 0x28 data values (FM key on/off)
    adpcma_keyon = Counter()      # port1 reg0x00 data values (ADPCM-A dump/keyon)
    adpcmb_ctrl = Counter()       # port0 reg0x10 data values (ADPCM-B control)
    ssg_mixer = Counter()         # port0 reg0x07 values
    blocks = []
    nwrites = [0]

    def on_write(port, reg, val):
        nwrites[0] += 1
        reg_hist[(port, reg)] += 1
        if port == 0 and reg == 0x28:
            keyon_vals[val] += 1
        elif port == 0 and reg == 0x07:
            ssg_mixer[val] += 1
        elif port == 0 and reg == 0x10:
            adpcmb_ctrl[val] += 1
        elif port == 1 and reg == 0x00:
            adpcma_keyon[val] += 1

    def on_wait(n):
        pass

    def on_block(bt, payload):
        blocks.append((bt, len(payload)))

    vgmlib.walk(data, h, on_write, on_wait, on_block)

    print(f"=== {Path(path).name} ===")
    print(f"chip {'YM2610B' if h.ym2610b else 'YM2610'} @ {h.ym2610_clock} Hz, "
          f"{h.total_seconds:.1f}s, {nwrites[0]} reg writes")

    # Which register blocks are touched?
    p0 = sorted(r for (pt, r) in reg_hist if pt == 0)
    p1 = sorted(r for (pt, r) in reg_hist if pt == 1)

    def cls(port, reg):
        if port == 0:
            if reg <= 0x0D:
                return "SSG"
            if 0x10 <= reg <= 0x1C:
                return "ADPCM-B"
            if reg in (0x22, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2A, 0x2B):
                return "FM-global"
            if 0x30 <= reg <= 0xB6:
                return "FM-ch(1,2)"
        else:
            if reg <= 0x2D:
                return "ADPCM-A"
            if 0x30 <= reg <= 0xB6:
                return "FM-ch(3,4)"
        return "?"

    used = Counter()
    for (pt, r), c in reg_hist.items():
        used[cls(pt, r)] += c
    print("section write counts:", dict(sorted(used.items(), key=lambda x: -x[1])))

    # FM key-on analysis: low 3 bits = channel selector, high 4 bits = slot mask.
    print("\nFM key on/off (reg 0x28) channel selectors seen:")
    chan_seen = Counter()
    for val, c in keyon_vals.items():
        sel = val & 0x07
        slots = (val >> 4) & 0x0F
        chan_seen[sel] += c
        tag = "KEYON" if slots else "keyoff"
    for sel in sorted(chan_seen):
        # decode: bit2 = part, bits0-1 = channel-in-part
        part = (sel >> 2) & 1
        cip = sel & 0x03
        print(f"  selector {sel} (part{part} ch{cip})  x{chan_seen[sel]}")

    # SSG: which tone channels enabled in mixer? bit n clear => tone n enabled.
    if ssg_mixer:
        print("\nSSG mixer (reg 0x07) values:",
              [f"{v:08b}" for v in sorted(ssg_mixer)][:8])
        ssg_regs = [r for r in p0 if r <= 0x0D]
        print("  SSG regs written:", [f"0x{r:02X}" for r in ssg_regs])

    # ADPCM-A
    if adpcma_keyon:
        print("\nADPCM-A keyon (port1 reg0x00) values:",
              [f"0x{v:02X}" for v in sorted(adpcma_keyon)])
        ach = set()
        for (pt, r) in reg_hist:
            if pt == 1 and 0x10 <= r <= 0x15:
                ach.add(r - 0x10)
        print("  ADPCM-A channels with start-addr writes:", sorted(ach))

    # ADPCM-B
    if adpcmb_ctrl:
        print("\nADPCM-B control (port0 reg0x10) values:",
              [f"0x{v:02X}" for v in sorted(adpcmb_ctrl)])

    if blocks:
        print("\ndata blocks:", [(f"0x{bt:02X}", sz) for bt, sz in blocks])
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for a in sys.argv[1:]:
        profile(a)
