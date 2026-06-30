#!/usr/bin/env python3
# IN-PLACE single-yield differential for the native scheduler switch-OUT (task #15) and switch-IN
# (task #16). Pins the unpinned ESC=0 DIFF~44 *integration* divergence of entry_swo by diffing the
# escape build against the committed build IN PLACE across consecutive yields of ONE faithful tick --
# NO injection of mid-tick state (which yield_faithful.py PHASE B proved is a dead end: the SA-1
# native stack, $41 shadow, $0700+ control and HW/cycle state aren't reproduced by DP+workRAM alone).
#
# HOW IT WORKS (the re-firing-freeze instrument, src/interp.pasm df_gap, gated on $0730=$5A5A):
#   * dbg_fetch's $0710 PC-freeze fires at FETCH time, BEFORE loop_hook/swo_tramp (interp.pasm L231
#     `jsr dbg_fetch` precedes L239 `jsr loop_hook`). So BOTH builds freeze at $0532 *pre*-switch-out,
#     symmetrically -- the committed build then interprets $0532-$0550; the escape build runs entry_swo.
#   * With $0730=$5A5A, df_gap SKIPS its one-shot `stz $0710`, so the freeze stays armed and re-fires
#     at the NEXT $0532 on its own -> the harness single-steps yield-by-yield through one whole tick.
#   * At each freeze we snapshot the interp's OWN state (DP/reg-file + work RAM) -- no MAME capture, so
#     no prefetch skew. Snapshot y reflects the cumulative effect of switch-outs 0..y-1. The FIRST y
#     where committed[y] != escape[y] pins switch-out (y-1) as the first to diverge, and the differing
#     bytes (work-RAM $F0xxxx + 68K reg file) localise the bug (expected near enable mask $F00001/2 +
#     sprite coords, per handoff §3).
#
# DEPENDS ON: the df_gap re-firing-freeze edit being built into BOTH ROMs (it's inert unless $0730 is
# set, so it can live permanently in src/interp.pasm). Build interp_committed.sfc with the switch-OUT
# escape REVERTED (GREEN) and interp.sfc with entry_swo wired.
#
# USAGE:
#   python3 tools/swo_inplace_diff.py [triple-dir]
# ENV (all optional):
#   FREEZE_PC=0532   yield bracket PC. 0532 = switch-OUT (pre). For switch-IN (task #16) use 075C
#                    (post switch-out + shared scan, = the switch-in entry the interpreter re-fetches)
#                    or 07E4 (the movem restore). Both builds must reach it as a fetched PC.
#   MAXY=24          max yields to capture per tick (one tick ~= 21-22 switch-outs)
#   COM=<path>       committed ROM (default build/interp_committed.sfc)
#   ESC=<path>       escape   ROM (default build/interp.sfc)
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession

TD     = sys.argv[1] if len(sys.argv)>1 else '/tmp/supermn-scratch/ce4trip64'
FRZ    = int(os.environ.get('FREEZE_PC','0532'),16)
MAXY   = int(os.environ.get('MAXY','24'))
NEXEN  = '/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'
NAT    = '/tmp/b0_native.mss'
COM    = os.environ.get('COM','/home/chad/supermn-snes/build/interp_committed.sfc')
ESC    = os.environ.get('ESC','/home/chad/supermn-snes/build/interp.sfc')

regs=open(TD+'/regsA.bin','rb').read(); wramA=open(TD+'/wramA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;Nf=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA)

def sess(rom,port):
    return McpSession(rom=rom,mesen=NEXEN,port=port,boot_wait=6.0,socket_timeout=300.0)
def helpers(m):
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v): m.write_u16(a,v,'Sa1Memory')
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    return r16,w16,wh,runf
def to_3a92(m):
    # boot to native, then freeze at the IRQ call site ($0708) and step to the GAME_TICK ($3A92).
    r16,w16,wh,runf=helpers(m)
    m.load_state(NAT); runf(120)
    w16(0x0700,0); w16(0x0738,0); w16(0x0730,0); w16(0x071A,1); w16(0x0712,0); w16(0x0716,0); w16(0x0710,0x0708); w16(0x0704,1)
    for _ in range(240):
        runf(5)
        if r16(0x0712): break
        w16(0x0710,0x0708); w16(0x0716,0)
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    for _ in range(60):
        w16(0x0710,0x3A92); w16(0x0716,0); runf(4)
        if r16(0x0712): break
def inject_ce4(m):
    r16,w16,wh,runf=helpers(m)
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,Nf);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,0x2F60); w16(0x0718,0xFFF8); w16(0x072E,1)   # $072E=1: loop_hook live (lh_sched + entry_swo)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    m.write_u16(0x410000,0,'snesMemory'); m.write_u16(0x410002,0,'snesMemory')

def snapshot(m):
    iram=bytes(m.read_memory('Sa1Memory',0x0000,0x0700))      # $0000-$06FF (excl harness $0700+)
    wram=bytes(m.read_memory('snesMemory',0x400000,0x10000))  # 68K work RAM (a5 base $F00000)
    return iram,wram

def capture(rom,port,tag):
    # Drive ONE faithful tick, re-firing-freeze at FRZ, snapshot at each yield. Returns [(iram,wram),..].
    snaps=[]
    with sess(rom,port) as m:
        r16,w16,wh,runf=helpers(m)
        to_3a92(m); inject_ce4(m)
        # arm the re-firing freeze, then release from the $3A92 freeze and run to the first FRZ
        w16(0x0716,0); w16(0x0710,FRZ); w16(0x0730,0x5A5A)
        w16(0x0712,0); w16(0x0714,1)
        for y in range(MAXY):
            ok=False
            for _ in range(80):
                if r16(0x0712): ok=True; break     # frozen at the next FRZ
                runf(1)
            if not ok: break                        # no more FRZ this tick -> done
            snaps.append(snapshot(m))
            w16(0x0712,0); w16(0x0714,1)            # release -> df_gap keeps $0710 armed -> next FRZ
        w16(0x0730,0)                               # disarm the instrument
        print(">>> %-9s %s: captured %d %04X-yields"%(tag,os.path.basename(rom),len(snaps),FRZ),flush=True)
    return snaps

# IRAM offsets that LEGITIMATELY differ once the two builds fetch different instruction counts
# (the escape collapses $0532-$0550) -> mask them so they don't drown the real signal.
IRAM_MASK=set(range(0x400,0x600))                   # 64-entry PC ring buffer
IRAM_MASK|= {0x48,0x49}                             # ring write index
IRAM_MASK|= {0x4A,0x4B,0x4C,0x4D}                   # interp instr counter ($4A/$4C)
IRAM_MASK|= {0x44,0x45}                             # current opcode (same PC -> usually equal, mask anyway)

def diff_pair(c,e):
    ic,wc=c; ie,we=e
    iramd=[(o,ic[o],ie[o]) for o in range(len(ic)) if ic[o]!=ie[o] and o not in IRAM_MASK]
    wramd=[(o,wc[o],we[o]) for o in range(len(wc)) if wc[o]!=we[o]]
    return iramd,wramd

# ---- run both builds, compare yield-by-yield ----
print(">>> triple=%s  FREEZE_PC=$%04X  MAXY=%d"%(TD,FRZ,MAXY),flush=True)
snC=capture(COM,7561,'committed')
snE=capture(ESC,7562,'escape')
N=min(len(snC),len(snE))
if len(snC)!=len(snE):
    print(">>> NOTE yield counts differ (committed=%d escape=%d) -> divergence by yield %d at latest"%(len(snC),len(snE),N),flush=True)

first=None
for y in range(N):
    iramd,wramd=diff_pair(snC[y],snE[y])
    if iramd or wramd:
        if first is None: first=y
        tag='  <=== FIRST DIVERGENCE' if y==first else ''
        print("\n>>> yield %d: %d reg/IRAM diffs, %d work-RAM diffs%s"%(y,len(iramd),len(wramd),tag),flush=True)
        for o,c,e in iramd[:24]:
            nm={0x3C:'a7.lo',0x3E:'a7.hi'}.get(o, ('d%d'%(o//4) if o<0x20 else 'a%d'%((o-0x20)//4)) if o<0x3C else '')
            print("    DP   $%02X %-5s committed=%02X escape=%02X"%(o,nm,c,e),flush=True)
        for o,c,e in wramd[:40]:
            print("    wram $F0%04X    committed=%02X escape=%02X"%(o,c,e),flush=True)
        if len(wramd)>40: print("    ... (+%d more work-RAM diffs)"%(len(wramd)-40),flush=True)
        break   # the first diverging yield is what we want; stop (later yields cascade)
    else:
        print(">>> yield %d: identical"%y,flush=True)

if first is None:
    print("\n>>> NO DIVERGENCE in %d yields at FREEZE_PC=$%04X."%(N,FRZ),flush=True)
    print(">>> If the parked escape still shows DIFF~44 under lockstep, the divergence is either past"
          " yield %d (raise MAXY) or only visible at a different bracket (try FREEZE_PC=075C / 07E4),"
          " or in state outside DP+workRAM ($41 shadow) -- extend snapshot() to read $41:0000+."%N,flush=True)
else:
    print("\n>>> FIRST DIVERGENCE at yield %d => switch-out #%d is the first to diverge."%(first,first-1),flush=True)
    print(">>> Inspect the diffs above against entry_swo: $0536 movem save / $053E SP-save (move.l a7,(a6))"
          " / $0544-$054E descriptor yield-mark / the $075C-exit reg state (d2,a3,$4a(a5)).",flush=True)
