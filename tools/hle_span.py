#!/usr/bin/env python3
# hle_span.py — SPIN-FREE cycle reading AT a 68K PC (HLE spike measurement). The old CYCLES=1 B1PC
# method reads cycleCount frames AFTER the $0710 trap fires (the SA-1 busy-spins in df_spin, counting
# cycles, until the harness polls) -> up to ~4 frames of nondeterministic spin pollution, useless for
# ~10K-cyc spans. THIS tool exec-hooks DF_SPIN ITSELF (the trap's spin loop is a distinct SA-1 PC),
# so run_until stops the SA-1 the moment the trap fires: zero pollution, works for ANY 68K PC (incl.
# bank $01). Span cost = [run at PC_end] - [run at PC_start]: cross-run deltas are valid because the
# staging is deterministic (same NAT + same writes -> cycle-identical up to the release).
# SAME-RUN two-point span: trap PC1 (read cyc1 at the df_spin pause), wake and re-pause at DFG_RFF
# (the instruction AFTER df_gap's one-shot `stz $0710` -> a re-arm written there survives), arm PC2,
# trap again (cyc2). Cross-run absolute cycleCounts are NOT comparable (load_state transplants the
# counter + session-boot variance) -- only same-run deltas.
# Usage: hle_span.py <triple> <PC1_hex24> <PC2_hex24> [POKE]
#        hle_span.py <triple> tick            <- TICK-TOTAL mode: cyc0 at the $3A92 release (paused
#          at DFG_RFF during the wake, ~15 cyc past the tick entry), cyc1 at the $0818 idle trap ->
#          one full GAME_TICK, spin-free. The Phase-0 canonical tick total (replaces the polluted
#          CYCLES=1 B1PC numbers).
#   POKE=1 -> disable the HLE dispatch first (bhp_bank_ext's `cmp #$2B6C` -> `#$FFFF`) so the tree
#   interprets = the baseline arm. NB the ROM has TWO bank-$00 images: file $0-$7FFF (the SA-1's
#   LoROM mirror = what the SA-1 FETCHES) and $8000-$FFFF (the 5A22's) -> poke BOTH.
#   Env ESC0=1 -> ALL escape gates off after staging ($071A/$073A/$073C/$0736 = 0) = the pure-interp
#   arm for per-context interp-rate calibration. Default: production gates on (match the shipped tick).
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1]; TICK=(sys.argv[2].lower()=='tick')
PC1=0 if TICK else int(sys.argv[2],16); PC2=0x0818 if TICK else int(sys.argv[3],16)
POKE=[] if (TICK or len(sys.argv)<5) else [0x2B6C if x=='1' else int(x,16) for x in sys.argv[4].split(',')]  # bhp_bank_ext cmp operand(s) to kill
ESC0=os.environ.get('ESC0')=='1'
DF_SPIN=0x00E2CF; DFG_RFF=0x00D1D9     # src/interp.sym df_spin / dfg_rff (re-check after interp rebuild)
wramA=open(TD+'/wramA.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;Nf=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA); NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
print("triple %s  %s  POKE(hle-off)=%s ESC0=%s"%(TD,("TICK-TOTAL ($3A92->$0818)" if TICK else "PC1=$%06X PC2=$%06X"%(PC1,PC2)),POKE,ESC0),flush=True)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=int(os.environ.get('PORT','7542')),boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def cyc(): return m.get_cpu_state('Sa1').get('cycleCount')
    def instr(): return r16(0x4A)|(r16(0x4C)<<16)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT); runf(120)
    for _op in POKE:
        blob=bytes(m.read_memory('snesPrgRom',0xD1F2,0x80))
        i=blob.find(bytes([0xC9,_op&0xFF,_op>>8]))
        assert i>=0, 'cmp operand %04X not found in bhp_bank_ext'%_op
        wh(0xD1F2+i+1,'ffff','snesPrgRom')           # 5A22 copy (file $8000-$FFFF)
        wh(0xD1F2+i+1-0x8000,'ffff','snesPrgRom')    # SA-1 LoROM-mirror copy (file $0-$7FFF) = the fetched one
        chk=bytes(m.read_memory('Sa1Memory',0xD1F2+i,3)); print("poked bhp arm %04X (Sa1 sees) -> %s"%(_op,chk.hex()),flush=True)
        assert chk[1:]==b'\xff\xff', "SA-1 still sees the old operand -- mirror offset wrong"
    w16(0x0700,0); w16(0x071A,0); w16(0x0712,0); w16(0x0716,0); w16(0x0710,0x0708); w16(0x0704,1)
    for _ in range(240):
        runf(5)
        if r16(0x0712): break
        w16(0x0710,0x0708); w16(0x0716,0)
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    for _ in range(60):
        w16(0x0710,0x3A92); w16(0x0716,0); runf(4)
        if r16(0x0712): break
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,Nf);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,0x2F60); w16(0x0718,0xFFF8); w16(0x0724,0); w16(0x0730,0); w16(0x0734,0); w16(0x071A,1)
    w16(0x073A,1); w16(0x073C,0xA55A); w16(0x0736,0x5EEC)   # production gates on (match the shipped tick)
    if ESC0: w16(0x071A,0); w16(0x073A,0); w16(0x073C,0); w16(0x0736,0)   # pure-interp calibration arm
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    h_spin=m.add_exec_hook(DF_SPIN, cpu_type='Sa1'); h_rff=m.add_exec_hook(DFG_RFF, cpu_type='Sa1')
    if TICK:
        # point 0 = the $3A92 release wake, paused at DFG_RFF (~15 cyc past the tick entry, $0710
        # already one-shot-cleared); point 1 = the $0818 idle fetch trap. One full GAME_TICK.
        w16(0x0712,0); w16(0x0714,1)
        r1=m.run_until(max_frames=10, hook_handle=h_rff); c1=cyc(); i1=instr()
        r2=r1
    else:
        w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)   # release $3A92 (trap disarmed)
        w16(0x0710,PC1&0xFFFF); w16(0x0716,(PC1>>16)&0xFF)    # arm PC1 (tick is ~17 frames; runf(1) passed is safe)
        r1=m.run_until(max_frames=900, hook_handle=h_spin); c1=cyc(); i1=instr()
        print("trap1 reason=%s cyc=%s instr=%d"%((r1 or {}).get('reason'),c1,i1),flush=True)
        # wake: release the spin, pause again right AFTER df_gap's one-shot `stz $0710`, re-arm for PC2
        w16(0x0712,0); w16(0x0714,1)
        r2=m.run_until(max_frames=10, hook_handle=h_rff)
    w16(0x0710,PC2&0xFFFF); w16(0x0716,(PC2>>16)&0xFF)
    r3=m.run_until(max_frames=1800, hook_handle=h_spin); c2=cyc(); i2=instr()
    print("trap2 reason=%s cyc=%s instr=%d"%((r3 or {}).get('reason'),c2,i2),flush=True)
    ok=all((x or {}).get('reason')=='hookFired' for x in (r1,r2,r3))
    print(">>> SPAN %s->%06X = %s cyc  (interp-instr = %d)"%(("TICK" if TICK else "%06X"%PC1),PC2,(c2-c1) if ok else 'N/A',i2-i1),flush=True)
