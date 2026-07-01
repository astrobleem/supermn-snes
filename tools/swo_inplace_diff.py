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
    m.load_state(NAT)
    # NAT was saved at jh_spin AFTER boot ran `sta $072E` (interp.pasm L154), so it carries
    # $072E!=0 -> loop_hook (lh_gen->swo_tramp->entry_swo) is LIVE. On the escape build that fires
    # entry_swo at the very first $0532 of runf(120) -> PC=$0000 crash BEFORE we reach $3A92.
    # Zero $072E for the whole boot drive (the freeze is $072E-independent); inject_ce4 re-enables it.
    print(">>> NAT $072E=$%04X -> zeroed for boot (loop_hook/entry_swo OFF until inject)"%r16(0x072E),flush=True)
    w16(0x072E,0); runf(120)
    w16(0x0700,0); w16(0x0738,0); w16(0x0730,0); w16(0x071A,1); w16(0x0712,0); w16(0x0716,0); w16(0x0710,0x0708); w16(0x0704,1)
    for _ in range(240):
        runf(5)
        if r16(0x0712): break
        w16(0x0710,0x0708); w16(0x0716,0)
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    reached=False
    for _ in range(60):
        w16(0x0710,0x3A92); w16(0x0716,0); runf(4)
        if r16(0x0712): reached=True; break
    print(">>> to_3a92: reached $3A92=%s  $40=$%04X $42=$%04X"%(reached,r16(0x40),r16(0x42)),flush=True)
    return reached
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
        if not snaps:
            # 0 captures -> escape died before the first $0532. Dump the PC ring ($0400, 64x4B:
            # low16,high16) + write idx $48 to see WHERE it went, plus the live interp PC ($40/$42).
            raw=bytes(m.read_memory('Sa1Memory',0x0400,0x100)); idx=r16(0x48)&0xFF
            def ent(k): o=(k*4)&0xFF; return (raw[o]|(raw[o+1]<<8))|((raw[o+2]|(raw[o+3]<<8))<<16)
            last=((idx//4)-1)%64
            seq=[ent((last-19+j)%64) for j in range(20)]
            print(">>> %-9s CAPTURED 0. live PC=$%04X%04X  ringidx=$%02X"%(tag,r16(0x42),r16(0x40),idx),flush=True)
            print(">>> %-9s PC ring last20 (oldest->newest): %s"%(tag," ".join("%06X"%p for p in seq)),flush=True)
        # entry_swo debug sentinels at $40:7FE0 (last fire wins; fire counter accumulates). Read
        # unconditionally so even an escape build that stalls at 1 capture (PC=$0000 resume crash,
        # never reaches yield 1) still reports what entry_swo SAW: a7(pre) + the resume-PC it pulled
        # from (a7+2). A wrong/zero resumePC directly confirms the $053E move.l a7,(a6) SP-save bug.
        sent=bytes(m.read_memory('snesMemory',0x407FE0,10))
        fire=sent[0]|(sent[1]<<8)
        a7=((sent[4]|(sent[5]<<8))<<16)|(sent[2]|(sent[3]<<8))
        rpc=(sent[6]<<16)|(sent[7]<<8)|sent[8]
        print(">>> %-9s sentinels $40:7FE0  fire=%d  a7(pre)=$%06X  resumePC(@a7+2)=$%06X"%(tag,fire,a7,rpc),flush=True)
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

def dump_swo_inputs(snap,tag):
    # Derive entry_swo's exact INPUTS + computed targets from a $0532 pre-fire (yield-0) snapshot.
    # DP reg file: D0=$00..D7=$1C, A0=$20,A1=$24,A2=$28,A3=$2C,A4=$30,A5=$34,A6=$38,A7=$3C (LE32).
    # 68K work RAM is BIG-endian; $F0xxxx -> wram[addr&0xFFFF]. entry_swo uses reg LO16 + base $400000.
    iram,wram=snap
    def dp32(o): return iram[o]|(iram[o+1]<<8)|(iram[o+2]<<16)|(iram[o+3]<<24)
    def w32(a): o=a&0xFFFF; return (wram[o]<<24)|(wram[o+1]<<16)|(wram[o+2]<<8)|wram[o+3]
    def w16(a): o=a&0xFFFF; return (wram[o]<<8)|wram[o+1]
    a7=dp32(0x3C); a5=dp32(0x34); a6=dp32(0x38); a4=dp32(0x30)
    a7lo=a7&0xFFFF
    new_a7=(a7&0xFFFF0000)|((a7lo-0x3C)&0xFFFF)          # $0536 movem: a7 lo16 -= 60 (no borrow to hi)
    # trap frame @ a7 (op_trap pushed). Show a few interpretations so the resume-PC layout is unambiguous.
    frame=[wram[(a7lo+k)&0xFFFF] for k in range(8)]
    respc_swo=(frame[2]<<16)|(frame[3]<<8)|frame[4]      # what entry_swo's sentinel reads: (a7+2..4)
    respc_std=(frame[3]<<16)|(frame[4]<<8)|frame[5]      # 68K [SR.w, PC.l] -> 24b PC at (a7+3..5)
    sp_tgt=w32(a5+6)                                     # a6 = *(a5+6): where new a7 is stored
    desc_tgt=w32(a5+0x4a)                                # a4 = *(a5+$4a): descriptor to mark
    desc_w=w16(desc_tgt&0xFFFF)
    print(">>> %s ENTRY_SWO INPUTS @ yield0 ($0532 pre-fire):"%tag,flush=True)
    print("    a7=$%08X  a5=$%08X  a6=$%08X  a4=$%08X"%(a7,a5,a6,a4),flush=True)
    print("    new_a7(saved)=$%08X   trap frame @a7 = %s"%(new_a7," ".join("%02X"%b for b in frame)),flush=True)
    print("    resumePC: entry_swo-reads(a7+2..4)=$%06X   68K-std(a7+3..5)=$%06X"%(respc_swo,respc_std),flush=True)
    print("    SP-save: a6=*(a5+6)=$%08X  -> writes new_a7 (BE long) at $F0%04X"%(sp_tgt,sp_tgt&0xFFFF),flush=True)
    print("    descr:   a4=*(a5+$4a)=$%08X  (a4).w=$%04X -> $%04X  at $F0%04X"%(desc_tgt,desc_w,(desc_w&0xcfff)|0xc000,desc_tgt&0xFFFF),flush=True)

def _dp32(iram,o): return iram[o]|(iram[o+1]<<8)|(iram[o+2]<<16)|(iram[o+3]<<24)
def _w32(wram,a): o=a&0xFFFF; return (wram[o]<<24)|(wram[o+1]<<16)|(wram[o+2]<<8)|wram[o+3]
def _w16(wram,a): o=a&0xFFFF; return (wram[o]<<8)|wram[o+1]

def capture_selffreeze(rom,port):
    # SELFFREEZE mode: entry_swo self-freezes (spins) after ONE switch-out (work-RAM flag $40:7FEE),
    # so there is NO PC=$0000 cascade. Capture INPUTS at the $0532 pre-fire freeze, release once, then
    # capture OUTPUTS while entry_swo spins (state stable). Single session -> immune to the A/B non-det.
    with sess(rom,port) as m:
        r16,w16,wh,runf=helpers(m)
        to_3a92(m); inject_ce4(m)
        wh(0x407FE0,'00'*0x10,'snesMemory')            # zero sentinel region ($40:7FE0..7FEF)
        if os.environ.get('SLOTTGT'):
            tgt=int(os.environ['SLOTTGT'],16)
            m.write_u16(0x407FEA,tgt,'snesMemory')       # freeze-at-slot target
            m.write_u16(0x407FEC,0x5A5A,'snesMemory')    # ARM freeze-at-slot (spin when $56>=target)
            print(">>> SLOTTGT: entry_swo spins at loop top when $56>=$%04X"%tgt,flush=True)
        else:
            m.write_u16(0x407FEE,0x5A5A,'snesMemory')   # ARM end self-freeze (after full switch-out)
        w16(0x0716,0); w16(0x0710,0x0532); w16(0x0730,0)   # one-shot $0532 freeze (yield 0, pre-fire)
        w16(0x0712,0); w16(0x0714,1)
        ok=False
        for _ in range(120):
            if r16(0x0712): ok=True; break
            runf(1)
        if not ok:
            print(">>> SELFFREEZE: never reached $0532 (yield 0)",flush=True); return None
        inp=(bytes(m.read_memory('Sa1Memory',0x0000,0x0700)), bytes(m.read_memory('snesMemory',0x400000,0x10000)))
        w16(0x0712,0); w16(0x0714,1)                    # release -> entry_swo fires ONCE -> (bug) loops
        # multi-timepoint sample: is the movem loop advancing (infinite) or terminated? watch $54/$56/PC.
        for t in (1,1,2,4):
            runf(t)
            ir=bytes(m.read_memory('Sa1Memory',0x0040,0x20))   # $40..$5F
            try: pc=m.get_cpu_state('Sa1').get('pc')
            except Exception: pc=None
            g54=ir[0x54-0x40]|(ir[0x55-0x40]<<8); g56=ir[0x56-0x40]|(ir[0x57-0x40]<<8)
            print(">>>   t+%d: PC=%s  $54(wptr)=$%04X  $56(slot)=$%04X"%(t,('$%06X'%pc) if isinstance(pc,int) else pc,g54,g56),flush=True)
        out=(bytes(m.read_memory('Sa1Memory',0x0000,0x0700)), bytes(m.read_memory('snesMemory',0x400000,0x10000)))
        sent=bytes(m.read_memory('snesMemory',0x407FE0,10))
        try: cpu=m.get_cpu_state('Sa1')
        except Exception as e: cpu={'err':str(e)}
        return inp,out,sent,cpu

def analyze_selffreeze(inp,out,sent,cpu=None):
    iram0,wram0=inp; iram1,wram1=out
    if cpu is not None:
        pc=cpu.get('pc'); pc=('$%06X'%pc) if isinstance(pc,int) else str(pc)
        print(">>> SA-1 spin state: PC=%s  A=%s X=%s Y=%s D=%s DBR=%s P=%s"%(pc,
            cpu.get('a'),cpu.get('x'),cpu.get('y'),cpu.get('d'),cpu.get('dbr',cpu.get('db')),cpu.get('p',cpu.get('ps'))),flush=True)
    # loop scratch + full reg-file diff (input vs output) to see what entry_swo actually touched
    print(">>> DP scratch @out: $50=%02X%02X $52=%02X%02X $54=%02X%02X $56=%02X%02X"%(
        iram1[0x51],iram1[0x50],iram1[0x53],iram1[0x52],iram1[0x55],iram1[0x54],iram1[0x57],iram1[0x56]),flush=True)
    changed=[o for o in range(0x40) if iram0[o]!=iram1[o]]
    print(">>> reg-file bytes changed by entry_swo ($00-$3F): %s"%(",".join("$%02X"%o for o in changed) or "NONE"),flush=True)
    a7=_dp32(iram0,0x3C); a5=_dp32(iram0,0x34); a7lo=a7&0xFFFF
    new_a7=(a7&0xFFFF0000)|((a7lo-0x3C)&0xFFFF)
    a6tgt=_w32(wram0,a5+6); a4tgt=_w32(wram0,a5+0x4a); descw0=_w16(wram0,a4tgt)
    fire=sent[0]|(sent[1]<<8)
    print("\n>>> ===== SELFFREEZE input->output verification (single fire) =====",flush=True)
    print(">>> fire=%d (expect 1)  a7=$%08X new_a7=$%08X a5=$%08X"%(fire,a7,new_a7,a5),flush=True)
    names=['d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6']
    ok1=True
    print(">>> [1] movem block @ $F0%04X (60B) vs reg file D0-A6:"%(new_a7&0xFFFF),flush=True)
    for i in range(15):
        reg=_dp32(iram0,i*4); got=_w32(wram1,new_a7+i*4)
        if got!=reg: ok1=False
        if got!=reg or i<1 or i>=13:
            print("    %-3s +%02d  reg=$%08X saved=$%08X %s"%(names[i],i*4,reg,got,'' if got==reg else '<== MISMATCH'),flush=True)
    print("    [1] movem: %s"%('PASS' if ok1 else 'FAIL'),flush=True)
    saved_sp=_w32(wram1,a6tgt)
    print(">>> [2] SP-save @ (a6)=$F0%04X = $%08X  expect new_a7=$%08X  %s"%(a6tgt&0xFFFF,saved_sp,new_a7,'PASS' if saved_sp==new_a7 else 'FAIL'),flush=True)
    exp=(descw0&0xcfff)|0xc000; got=_w16(wram1,a4tgt)
    print(">>> [3] descr @ (a4)=$F0%04X = $%04X  expect $%04X (from $%04X)  %s"%(a4tgt&0xFFFF,got,exp,descw0,'PASS' if got==exp else 'FAIL'),flush=True)
    print(">>> output reg file: a7=$%08X a6=$%08X a4=$%08X d0=$%08X $7C=$%04X"%(
        _dp32(iram1,0x3C),_dp32(iram1,0x38),_dp32(iram1,0x30),_dp32(iram1,0x00),iram1[0x7C]|(iram1[0x7D]<<8)),flush=True)

# ---- run both builds, compare yield-by-yield ----
print(">>> triple=%s  FREEZE_PC=$%04X  MAXY=%d"%(TD,FRZ,MAXY),flush=True)
if os.environ.get('SELFFREEZE'):
    print(">>> SELFFREEZE mode: single-fire entry_swo input->output verification (escape build only)",flush=True)
    r=capture_selffreeze(ESC,7562)
    if r: analyze_selffreeze(*r)
    sys.exit(0)
snC=capture(COM,7561,'committed')
snE=capture(ESC,7562,'escape')
if snE: dump_swo_inputs(snE[0],'escape   ')   # the real entry_swo inputs (pre-fire)
if snC: dump_swo_inputs(snC[0],'committed')   # cross-check (same $0532 pre-state)
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
