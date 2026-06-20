#!/usr/bin/env python3
"""Stage-1 video-plumbing check: boot the interpreter to its live game loop and
verify the store-dispatch refactor (a) didn't regress the boot and (b) is mirroring
the hardware video banks into $7E shadow RAM.

Mesen "snesWorkRam" offset map:
  0x00000..0x0FFFF = $7E:0000-FFFF   (shadow regions live here)
  0x10000..0x1FFFF = $7F:0000-FFFF   (68K work RAM $F0xxxx)
So: tmask $F00002 -> 0x10002 ; frame ctr $F01C56 -> 0x11C56 ;
    SHADOW_PAL $7E:2000 -> 0x2000 ; SHADOW_D0 $7E:3000 -> 0x3000 ;
    SHADOW_COD $7E:4000 -> 0x4000.
"""
import sys, os, zlib
sys.path.insert(0, "/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT", "/home/chad/.dotnet8")
os.environ["PATH"] = "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")
from mesen_mcp import McpSession

ROM = "/home/chad/supermn-snes/build/interp.sfc"
MESEN = "/home/chad/Mesen2/bin/linux-x64/Release/Mesen"

def u32(b, o): return b[o] | (b[o+1] << 8) | (b[o+2] << 16) | (b[o+3] << 24)
def u16(b, o): return b[o] | (b[o+1] << 8)
def nz(b): return sum(1 for x in b if x)

with McpSession(rom=ROM, mesen=MESEN, port=7347, boot_wait=3.0) as m:
    def pc(): return u32(m.read_memory("snesWorkRam", 0x40, 4), 0)
    # 68K values are big-endian in $7F work RAM -> byteswap the LE read
    def be16(o): b = m.read_memory("snesWorkRam", o, 2); return (b[0] << 8) | b[1]
    def tmask(): return be16(0x10002)
    def fctr(): return be16(0x11C56)
    pcs = set(); tmasks = []; fctrs = []; total = 0
    for i in range(14):
        m.run_frames(200); total += 200
        pcs.add(pc()); tmasks.append(tmask()); fctrs.append(fctr())
        print(f"  @{total}f PC=${pc():06X} tmask=${tmasks[-1]:04X} F01C56={fctrs[-1]}", flush=True)
    # shadow regions after reaching the live loop
    pal = m.read_memory("snesWorkRam", 0x2000, 0x1000)   # SHADOW_PAL ($B0 palette)
    d0  = m.read_memory("snesWorkRam", 0x3000, 0x1000)   # SHADOW_D0  ($D0 Y/scroll)
    cod = m.read_memory("snesWorkRam", 0x4000, 0x4000)   # SHADOW_COD ($E0 sprite code/X)
    m.run_frames(120)
    pal2 = m.read_memory("snesWorkRam", 0x2000, 0x1000)
    cod2 = m.read_memory("snesWorkRam", 0x4000, 0x4000)

    # boot is "alive" once tmask reaches $0003 and holds; early $0000/$0100 are boot-in-progress
    tmask_ok = (0x0003 in tmasks) and tmasks[-1] == 0x0003
    fctr_ok  = fctrs[-1] > fctrs[0]
    pal_pop  = nz(pal); cod_pop = nz(cod); d0_pop = nz(d0)
    pal_evolve = (pal != pal2); cod_evolve = (cod != cod2)
    # dump shadow palette for offline reconciliation vs MAME
    open("/tmp/interp_shadow_pal.bin", "wb").write(pal)
    open("/tmp/interp_shadow_cod.bin", "wb").write(cod)

    print(f"\n=== Stage-1 results ===")
    print(f"tmask stable $0003:        {tmask_ok}   (saw {sorted(set(f'${t:04X}' for t in tmasks))})")
    print(f"$F01C56 increments:        {fctr_ok}   ({fctrs[0]} -> {fctrs[-1]})")
    print(f"SHADOW_PAL populated:      {pal_pop>0}   ({pal_pop}/{len(pal)} nonzero bytes)")
    print(f"SHADOW_COD populated:      {cod_pop>0}   ({cod_pop}/{len(cod)} nonzero bytes)")
    print(f"SHADOW_D0  populated:      {d0_pop>0}   ({d0_pop}/{len(d0)} nonzero bytes)")
    print(f"SHADOW_PAL evolves:        {pal_evolve}")
    print(f"SHADOW_COD evolves:        {cod_evolve}")
    print(f"distinct PCs: {sorted(f'${x:06X}' for x in pcs)}")
    print(f"wrote /tmp/interp_shadow_pal.bin (4KB), /tmp/interp_shadow_cod.bin (16KB)")
    # evolve is informational only: the interpreter is ~100x slower than realtime,
    # so a 120-frame window rarely spans a full game-frame. Not a gate.
    ok = tmask_ok and fctr_ok and pal_pop > 0 and cod_pop > 0 and d0_pop > 0
    print(f"\nSTAGE-1 {'PASS' if ok else 'FAIL'} (evolve checks are informational)")
