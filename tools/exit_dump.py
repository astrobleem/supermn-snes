#!/usr/bin/env python3
# Exit-state dump for isolating a single escape's DIRECT output divergence.
# Injects a MAME triple, runs one GAME_TICK with escapes=ESC, and traps at TRAP (a 68K PC,
# low-16 fetch-trap via $0710) -- e.g. the RETURN PC of a called subroutine. At the trap it dumps
# the FULL work-RAM (-> OUTBASE.wram) and the 68K reg-file+CCR (-> OUTBASE.regs). Run twice with
# builds differing ONLY in the target escape (interp vs native), diff the dumps -> that escape's
# direct output divergence, with everything else held constant. Based on tools/lockstep_trap.py.
# Usage: exit_dump.py <triple> <AC_hex> <ESC> <TRAP_hex> <OUTBASE> [OCC]
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1]; AC=int(sys.argv[2],16); ESC=int(sys.argv[3]); TRAP=int(sys.argv[4],16); OUT=sys.argv[5]
OCC=int(sys.argv[6]) if len(sys.argv)>6 else 1
wramA=open(TD+'/wramA.bin','rb').read(); wramB=open(TD+'/wramB.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;N=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
WN=len(wramA); RN=['d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6','a7']
PORT=int(os.environ.get('PORT','7526'))
print("triple %s AC=%04X ESC=%d TRAP=$%04X OCC=%d OUT=%s"%(TD,AC,ESC,TRAP,OCC,OUT),flush=True)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=PORT,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    if os.environ.get('POKE92'):
        _op=int(os.environ['POKE92'],16)
        _b=bytes(m.read_memory('snesPrgRom',0x297000,0x1000)); _i=_b.find(bytes([0xC9,_op&0xFF,_op>>8]))
        assert _i>=0, 'POKE92 %04X not found'%_op
        m.write_memory('snesPrgRom',0x297000+_i+1,'ffff')
        print('>>> POKE92: jah2 arm %04X disabled'%_op,flush=True)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT); runf(120)
    w16(0x0700,0); w16(0x071A,0); w16(0x0712,0); w16(0x0716,0); w16(0x0710,0x0708); w16(0x0704,1)
    s1=False
    for _ in range(240):
        runf(5)
        if r16(0x0712): s1=True; break
        w16(0x0710,0x0708); w16(0x0716,0)
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    b0=False
    for _ in range(60):
        w16(0x0710,0x3A92); w16(0x0716,0); runf(4)
        if r16(0x0712): b0=True; break
    print("B0 stage1(0708)=%s stage2(3A92)=%s"%(s1,b0),flush=True)
    # inject MAME frame-N over the trapped interp (identical to lockstep_trap)
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,N);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    STREAM=os.environ.get('STREAM')   # if set, enable dbg_fetch ALL-PC stream ($40:8000, ptr $0718)
    w16(0xAC,AC); w16(0x0718,0 if STREAM else 0xFFF8); w16(0x0724,0); w16(0x0730,0); w16(0x0734,0); w16(0x071A,ESC)
    w16(0x073A,int(os.environ.get('CHOKE','0')))
    w16(0x073C,0xA55A if os.environ.get('SWIN')=='1' else 0)
    w16(0x0736,0x5EEC if os.environ.get('SEL')=='1' else 0)
    for _a in (0x407FE0,0x407FE2,0x407FE4,0x407FE6,0x407FE8,0x407FEA): m.write_u16(_a,0,'snesMemory')
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    # release one step, then trap at TRAP. OCC: skip past earlier occurrences.
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    TBANK=(TRAP>>16)&0xFF   # $0716 bank must also match $42 (dbg_fetch checks BOTH low16 and bank)
    seen=0; hit=False
    for _ in range(400):
        w16(0x0712,0); w16(0x0710,TRAP&0xFFFF); w16(0x0716,TBANK); runf(4)
        if r16(0x0712):
            seen+=1
            if seen>=OCC: hit=True; break
            w16(0x0712,0); w16(0x0710,0); w16(0x0716,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    pc=r16(0x40)|(r16(0x42)<<16)
    instr=r16(0x4A)|(r16(0x4C)<<16)
    c=m.read_memory('snesMemory',0x407FE0,12)
    print("TRAP hit=%s seen=%d PC=$%06X instr=%d  bailmark($0724)=%d d5($14)=$%04X d6($18)=$%04X d7($1C)=$%04X"%(
        hit,seen,pc,instr,r16(0x0724),r16(0x14),r16(0x18),r16(0x1C)),flush=True)
    if not hit:
        print(">>> TRAP NOT HIT — aborting dump",flush=True); sys.exit(2)
    if STREAM:
        # decode the ALL-PC stream at $40:8000 (4 bytes/PC LE: lo16 @ +0, bank16 @ +2), filter to RANGE
        nb=r16(0x0718); nb=min(nb,0xFFF8)
        raw=b''
        for o in range(0,nb,0x1000): raw+=bytes(m.read_memory('snesMemory',0x408000+o,min(0x1000,nb-o)))
        pcs=[((raw[i]|(raw[i+1]<<8)) | ((raw[i+2]|(raw[i+3]<<8))<<16)) for i in range(0,len(raw)-3,4)]
        lo,hi=[int(x,16) for x in os.environ.get('RANGE','025110-0259CA').split('-')]
        seq=[p for p in pcs if lo<=(p&0xFFFFFF)<=hi]
        print(">>> STREAM: %d total PCs, %d in range $%06X-$%06X"%(len(pcs),len(seq),lo,hi),flush=True)
        # run-length collapse consecutive repeats + print execution order
        import capstone as _cs; MD=_cs.Cs(_cs.CS_ARCH_M68K,_cs.CS_MODE_BIG_ENDIAN); ROM=open('build/interp.sfc','rb').read()
        def dis(pc):
            try: ins=next(MD.disasm(ROM[0x10000+(pc&0x3FFFFF):0x10000+(pc&0x3FFFFF)+8],pc)); return '%s %s'%(ins.mnemonic,ins.op_str)
            except StopIteration: return '?'
        with open(OUT+'.trace','w') as f:
            for i,p in enumerate(seq): f.write("%06X\n"%(p&0xFFFFFF))
        print(">>> wrote %s.trace (%d PCs). First 60 in execution order:"%(OUT,len(seq)),flush=True)
        for p in seq[:60]:
            print("   $%06X  %s"%(p&0xFFFFFF,dis(p)),flush=True)
    # dump full work-RAM + reg-file
    out=bytes(m.read_memory('snesMemory',0x400000,WN))
    open(OUT+'.wram','wb').write(out)
    rf=bytes(m.read_memory('Sa1Memory',0x00,0x40))
    with open(OUT+'.regs','w') as f:
        f.write("PC=$%06X instr=%d\n"%(pc,instr))
        for i in range(16):
            v=(rf[i*4]|(rf[i*4+1]<<8)|(rf[i*4+2]<<16)|(rf[i*4+3]<<24))
            f.write("%s=%08X\n"%(RN[i],v))
        f.write("Z=%d C=%d N=%d V=%d X=%d\n"%(r16(0x60),r16(0x6E),r16(0x70),r16(0x72),r16(0xA2)))
    # quick self-report: how many work-RAM bytes differ vs the tick-boundary oracle (context only)
    nd=sum(1 for i in range(WN) if out[i]!=wramB[i])
    print(">>> dumped %s.wram (%d B) + %s.regs ; (vs wramB tick-boundary: %d bytes, expected large mid-tick)"%(OUT,WN,OUT,nd),flush=True)
