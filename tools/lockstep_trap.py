#!/usr/bin/env python3
# Full-tick lockstep using the $0710/$0712 PC-TRAP (fires at instruction fetch -> ESCAPE-COMPATIBLE,
# unlike the $0700/$0702 jsr-hook freeze which is bypassed when the GAME_TICK path itself is escaped).
# Trap at $0710=$3A92 (the GAME_TICK boundary wramB is captured at). Inject MAME frame-N, run one tick
# with escapes=ESC, diff vs wramB. Usage: lockstep_trap.py <triple-dir> [AC_hex] [ESC]
# WIP: B0 trap acquisition not yet firing (B0 stage1(0708)=False). profile_real uses the SAME $0710=
# $0708 trap successfully -- replicate its exact sequence: `runf(150); m.load_state(NAT); <set flags
# incl w16(0x0704,1)>; w16(0x0710,0x0708); for: runf(5); if $0712: break` (boot Nexen BEFORE load_state,
# set $0704=1, arm $0710 once). Then 2-stage to $3A92 for the wramB phase. See mame-capture-precision.
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1]; AC=int(sys.argv[2],16) if len(sys.argv)>2 else 0x2F60; ESC=int(sys.argv[3]) if len(sys.argv)>3 else 0
wramA=open(TD+'/wramA.bin','rb').read(); wramB=open(TD+'/wramB.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;N=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
NEXEN=os.environ.get(
    'NEXEN',
    '/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/linux-x64/publish/Nexen',
)
NAT=os.environ.get('NAT','/tmp/b0_native.mss')
WN=len(wramA)
print("triple %s AC=%04X ESC=%d WN=%d SP=%06X"%(TD,AC,ESC,WN,SP&0xFFFFFF),flush=True)
with McpSession(rom=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','build','interp.sfc'),mesen=NEXEN,port=int(os.environ.get('PORT','7526')),boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT)
    if os.environ.get('POKEOP'):
        # disable one bhp_bank_ext escape arm: cmp #$XXXX -> #$FFFF in BOTH bank-$00 ROM copies
        _op=int(os.environ['POKEOP'],16)
        _b=bytes(m.read_memory('snesPrgRom',0xD1F2,0x80)); _i=_b.find(bytes([0xC9,_op&0xFF,_op>>8]))
        assert _i>=0, 'POKEOP %04X not found'%_op
        m.write_memory('snesPrgRom',0xD1F2+_i+1,'ffff'); m.write_memory('snesPrgRom',0xD1F2+_i+1-0x8000,'ffff')
        print('>>> POKEOP: bhp arm %04X disabled'%_op,flush=True)
    if os.environ.get('POKEROM'):
        # generic ROM patch(es): "fileoff:hexbytes[,fileoff:hexbytes...]" (single copy; for bank-$00
        # use POKEOP-style two-copy logic instead). e.g. zero an xlat sub-table entry to disable one
        # table-dispatched escape for an A/B arm.
        for _spec in os.environ['POKEROM'].split(','):
            _off,_hx=_spec.split(':')
            m.write_memory('snesPrgRom',int(_off,16),_hx)
            print('>>> POKEROM: file $%06X <- %s'%(int(_off,16),_hx),flush=True)
    if os.environ.get('POKE92'):
        # disable one jah2_ext/jah2_ext_bsr arm in the $92 escbank (file $290000, single copy)
        _op=int(os.environ['POKE92'],16)
        _b=bytes(m.read_memory('snesPrgRom',0x297000,0x1000)); _i=_b.find(bytes([0xC9,_op&0xFF,_op>>8]))
        assert _i>=0, 'POKE92 %04X not found'%_op
        m.write_memory('snesPrgRom',0x297000+_i+1,'ffff')
        print('>>> POKE92: jah2 arm %04X disabled'%_op,flush=True); runf(120)
    # CRITICAL: NAT is saved FROZEN at jh_spin via $0700/$0702/$0704 -> set $0704=1 to RELEASE it,
    # else the interp never runs (instr=0) and no trap fires.
    w16(0x0700,0); w16(0x071A,0); w16(0x0712,0); w16(0x0716,0); w16(0x0710,0x0708); w16(0x0704,1)
    # B0 stage 1: reach gameplay via the $0708 IRQ (a direct $3A92 trap from NAT never fires)
    s1=False
    for _ in range(240):
        runf(5)
        if r16(0x0712): s1=True; break
        w16(0x0710,0x0708); w16(0x0716,0)   # re-arm (one-shot clears on release)
    # release one step, then stage 2: trap the GAME_TICK $3A92 (the wramB phase)
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    b0=False
    for _ in range(60):
        w16(0x0710,0x3A92); w16(0x0716,0); runf(4)
        if r16(0x0712): b0=True; break
    print("B0 stage1(0708)=%s stage2(3A92)=%s"%(s1,b0),flush=True)
    # inject MAME frame-N over the trapped interp
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,N);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,AC); w16(0x0718,0xFFF8); w16(0x0724,0); w16(0x0730,0); w16(0x0734,0); w16(0x071A,ESC)
    w16(0x073A,int(os.environ.get('CHOKE','0')))          # fetch-chokepoint gate (ce4/13be)
    w16(0x073C,0xA55A if os.environ.get('SWIN')=='1' else 0)  # switch-IN escape gate (magic-match)
    w16(0x073E,1 if os.environ.get('C9A6OFF')=='1' else 0)    # c9a6 validation toggle (1=skip=without-c9a6 baseline)
    w16(0x0736,0x5EEC if os.environ.get('SEL')=='1' else 0)   # scheduler-SELECT escape gate (lhs_sel)
    for _a in (0x407FE0,0x407FE2,0x407FE4,0x407FE6,0x407FE8,0x407FEA): m.write_u16(_a,0,'snesMemory')  # ce4t/swin/8fa/fd2/c9a6/sel counters
    if os.environ.get('LH072E') is not None: w16(0x072E, int(os.environ['LH072E'],0))  # loop_hook enable (per-fetch tax probe)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    # release one step past B0, then trap at the next $0708 IRQ entry (B1). NOTE: with escapes ON the
    # GAME_TICK $3A92 is itself a native escape (entry_3a92) so the interp never FETCHES $3A92 -> can't
    # trap there; $0708 (IRQ entry, before entry_3a92 runs) is escape-safe. Small phase offset vs wramB
    # (the $0708->$3A92 IRQ prologue).
    B1PC=int(os.environ.get('B1PC','0708'),16)
    GPPROF=os.environ.get('GPPROF')
    HK=os.environ.get('HOOKTEST')   # comma-sep hex SA-1 addresses to exec-hook (reliable; not memory counters)
    if HK:
        for a in HK.split(','): m.add_exec_hook(int(a,16), cpu_type='Sa1')
        print(">>> exec-hooks armed:", HK, flush=True)
    # CYCLES=1: SA-1 cycle meter. Read the SA-1 cycleCount at tick START (here, just before release)
    # and tick END (B1 trap) -> SA-1 cycles for one GAME_TICK. Measure DELTAS within this continuous
    # run only (load_state transplants cycleCount -- never span an injection). Compare ESC=0 vs 1.
    CYC=os.environ.get('CYCLES')
    cyc0 = m.get_cpu_state('Sa1').get('cycleCount') if CYC else None
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    if GPPROF: w16(0x0718,0); w16(0x0762,0)   # enable dbg_fetch (ALL) + ilog (REAL interpreted) streams
    b1=False
    for _ in range(400):
        # bank-aware B1 trap: $0716 = the PC bank (dbg_fetch checks BOTH low16 and bank). Pass B1PC as
        # a full 24-bit PC (e.g. 011778) to trap a bank-!=0 PC; low-16 B1PC (0708/0818) -> bank 0 as before.
        w16(0x0710,B1PC&0xFFFF); w16(0x0716,(B1PC>>16)&0xFF); runf(4)
        if r16(0x0712): b1=True; break
    if CYC:
        cyc1 = m.get_cpu_state('Sa1').get('cycleCount')
        dc = (cyc1-cyc0) if (cyc0 is not None and cyc1 is not None) else None
        print(">>> SA-1 cycles this tick (B0->B1, ESC=%d) = %s  [cyc0=%s cyc1=%s]"%(ESC,dc,cyc0,cyc1),flush=True)
    if HK:
        print(">>> hook_diag:", m.hook_diag(), flush=True)
        for h in m.list_hooks(): print(">>>   hook:", h, flush=True)
    if GPPROF:
        import collections
        na,nr=r16(0x0718),r16(0x0762)
        def dec(buf,nb): return [((buf[i+2]|(buf[i+3]<<8))<<16)|(buf[i]|(buf[i+1]<<8)) for i in range(0,min(nb,len(buf))-3,4)]
        if os.environ.get('ALLSTREAM'):
            # ilog is DEAD (choke_tramp replaced it) -> use the dbg_fetch ALL stream ($0718 @ $40:8000).
            # With escapes armed, "all fetched" ~= genuinely-interpreted + 1-entry dispatch markers.
            nb=min(na,0x7FF8)
            raw=b''
            for o in range(0,nb,0x1000): raw+=bytes(m.read_memory('snesMemory',0x408000+o,min(0x1000,nb-o)))
            real=dec(raw,nb)
            print(">>> ALLSTREAM: %d fetched PCs ($0718=%d bytes%s)"%(len(real),na," CAPPED" if na>=0x7FF8 else ""),flush=True)
            sd=os.environ.get('STREAMDUMP')   # write the CHRONOLOGICAL fetch stream (one hex PC/line)
            if sd: open(sd,'w').write('\n'.join('%06X'%(p&0xFFFFFF) for p in real))
        else:
            real=dec(bytes(m.read_memory('snesMemory',0x40C000,min(nr,0x3FF8))),nr)
        reg=collections.Counter(p&0xFFFFC0 for p in real)
        print(">>> GAMEPLAY interpreted stream: %d REAL PCs, top 64B regions:"%len(real),flush=True)
        import capstone as _cs; _MD=_cs.Cs(_cs.CS_ARCH_M68K,_cs.CS_MODE_BIG_ENDIAN)
        _ROM=open('build/interp.sfc','rb').read()
        for reg64,cnt in reg.most_common(24):
            try: ins=next(_MD.disasm(_ROM[0x10000+(reg64&0x3FFFFF):0x10000+(reg64&0x3FFFFF)+8],reg64)); d='%s %s'%(ins.mnemonic,ins.op_str)
            except StopIteration: d='?'
            print(">>>   $%06X  x%-4d  [%s]"%(reg64,cnt,d),flush=True)
        ex=os.environ.get('EXACT')   # "lo-hi[,lo-hi...]" hex ranges -> exact-PC histogram
        if ex:
            for rng in ex.split(','):
                lo,hi=[int(x,16) for x in rng.split('-')]
                h=collections.Counter(p&0xFFFFFF for p in real if lo<=(p&0xFFFFFF)<=hi)
                print(">>> EXACT $%06X-$%06X (%d PCs):"%(lo,hi,sum(h.values())),flush=True)
                for pc,c in sorted(h.items()):
                    try: ins=next(_MD.disasm(_ROM[0x10000+(pc&0x3FFFFF):0x10000+(pc&0x3FFFFF)+8],pc)); d='%s %s'%(ins.mnemonic,ins.op_str)
                    except StopIteration: d='?'
                    print(">>>   $%06X x%-4d %s"%(pc,c,d),flush=True)
        tgt=os.environ.get('PRED')
        if tgt:
            t=int(tgt,16); preds=collections.Counter()
            for i,p in enumerate(real):
                if (p&0xFFFFFF)==t and i>0: preds[real[i-1]&0xFFFFFF]+=1
            print(">>> predecessors of $%06X (interpreted stream):"%t,flush=True)
            for pp,c in preds.most_common(8):
                try: ins=next(_MD.disasm(_ROM[0x10000+(pp&0x3FFFFF):0x10000+(pp&0x3FFFFF)+8],pp)); d='%s %s'%(ins.mnemonic,ins.op_str)
                except StopIteration: d='?'
                print(">>>   from $%06X x%-3d [%s]"%(pp,c,d),flush=True)
        sw=os.environ.get('STREAMWIN')
        if sw:
            t=int(sw,16)
            idx=next((i for i,p in enumerate(real) if (p&0xFFFFFF)==t), None)
            if idx is None: print(">>> STREAMWIN: $%06X not in stream"%t,flush=True)
            else:
                print(">>> ordered stream around FIRST $%06X (idx %d):"%(t,idx),flush=True)
                for j in range(max(0,idx-int(os.environ.get("STREAMWIN_N","20"))), min(len(real),idx+4)):
                    p=real[j]&0xFFFFFF
                    try: ins=next(_MD.disasm(_ROM[0x10000+(p&0x3FFFFF):0x10000+(p&0x3FFFFF)+8],p)); d='%s %s'%(ins.mnemonic,ins.op_str)
                    except StopIteration: d='?'
                    print(">>>   [%d] $%06X  %s%s"%(j,p,d," <<<" if j==idx else ""),flush=True)
        if os.environ.get('ENTRYCLASS'):
            # classify FUNCTION ENTRIES: an interpreted PC whose predecessor is a control transfer.
            def mn(pc):
                try: return next(_MD.disasm(_ROM[0x10000+(pc&0x3FFFFF):0x10000+(pc&0x3FFFFF)+8],pc)).mnemonic.split('.')[0]
                except StopIteration: return '?'
            CF={'jsr','bsr','rts','jmp','rte','rtr','rtd'}
            ent=collections.Counter()   # (target, kind) -> count
            for i in range(1,len(real)):
                pm=mn(real[i-1]&0xFFFFFF)
                if pm in CF: ent[(real[i]&0xFFFFFF, pm)]+=1
            print(">>> FUNCTION ENTRIES via control-transfer (kind | target | count | disasm):",flush=True)
            for (t,k),c in ent.most_common(28):
                try: ins=next(_MD.disasm(_ROM[0x10000+(t&0x3FFFFF):0x10000+(t&0x3FFFFF)+8],t)); d='%s %s'%(ins.mnemonic,ins.op_str)
                except StopIteration: d='?'
                print(">>>   %-4s $%06X x%-4d [%s]"%(k,t,c,d),flush=True)
    instr=r16(0x4A)|(r16(0x4C)<<16)
    c=m.read_memory('snesMemory',0x407FE0,12)
    ce4t=c[0]|(c[1]<<8); swn=c[2]|(c[3]<<8); f8fa=c[4]|(c[5]<<8); ffd2=c[6]|(c[7]<<8); fc9a6=c[8]|(c[9]<<8); fsel=c[10]|(c[11]<<8)
    print("B1 trap=%s instr=%d ce4=%d 13be=%d ceb6=%d esc=%d  [ctrs: ce4t=%d swin=%d 8fa=%d fd2=%d c9a6=%d sel=%d]"%(
        b1,instr,r16(0x0724),r16(0x0730),r16(0x0734),ESC,ce4t,swn,f8fa,ffd2,fc9a6,fsel),flush=True)
    if os.environ.get('REGDUMP'):
        rf=bytes(m.read_memory('Sa1Memory',0x00,0x40))
        nm=['d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6','a7']
        print("=== reg file @ B1 (PC=$%04X) ==="%B1PC,flush=True)
    print("  $AC=$%04X  $4A/4C(instr)=%d  $AA(vbl)=$%04X  $A8=$%04X"%(r16(0xAC),r16(0x4A)|(r16(0x4C)<<16),r16(0xAA),r16(0xA8)),flush=True)
        for i in range(16):
            lo=rf[i*4]|(rf[i*4+1]<<8); hi=rf[i*4+2]|(rf[i*4+3]<<8)
            print("  %s=$%04X%04X"%(nm[i],hi,lo),flush=True)
        md=os.environ.get("MEMDUMP")
        if md:
            for rng in md.split(","):
                a=int(rng,16); b=bytes(m.read_memory("snesMemory",0x400000+a,16))
                print("  $F0%04X: %s"%(a," ".join("%02X"%x for x in b)),flush=True)
    out=bytes(m.read_memory('snesMemory',0x400000,WN))
    excl=set(range(0x170A-0x80,0x170A+0x80))
    diff=[i for i in range(WN) if out[i]!=wramB[i] and i not in excl]
    print(">>> $40 diff vs MAME wramB = %d bytes (stack-excl)"%len(diff),flush=True)
    lim=len(diff) if os.environ.get('FULLDIFF') else 20
    for i in diff[:lim]: print("   $F0%04X: interp=%02X mame=%02X (A=%02X)"%(i,out[i],wramB[i],wramA[i]),flush=True)
    print(">>>", "GREEN" if len(diff)<=8 else "DIFF=%d"%len(diff),flush=True)
