#!/usr/bin/env python3
# Ground-truth validator for JMP-STATE / table-dispatched escapes (the no-push convention) — the
# gating tool for the AOT table-coverage grind. Sibling of val_escape_mame (which does synthetic-jsr
# for jsr-convention escapes). Here we DISPATCH via a synthetic `jmp (a0)` with a0=$TGT, which routes
# op_jmp_idx -> ojmp_hook -> xlat table -> entry_<TGT> (entered no-push, PC=handler, the real return
# already on the 68K stack from the injected MAME frame). We trap at the handler's rts-target
# R=[SP] (read from the injected wram) and diff regs+$40 vs MAME's exit. Bypasses the sub-realtime
# interp-vs-interp alignment problem entirely (only MAME ground truth, see batch-mame-validator memory).
# Needs /tmp/supermn-scratch/frame_<TGT>/{entry,exit}_*.bin (extract_frame/extract_exit at $TGT).
# Usage: val_jmpstate_mame.py <hex-addr>
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TGT=int(sys.argv[1],16); FD='/tmp/supermn-scratch/frame_%x'%TGT; SCRATCH=0xFF00
regs=open(FD+'/entry_regs.bin','rb').read(); wram=open(FD+'/entry_wram.bin','rb').read()
exitw=open(FD+'/exit_wram.bin','rb').read(); exitr=open(FD+'/exit_regs.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
RN=['d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6']
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
R=be32(wram,(SP&0xFFFF))&0xFFFFFF   # the handler's return = [SP] (no-push: real return on the stack)
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
Z=(SR>>2)&1;C=SR&1;N=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
print("$%06X jmp-state: SP=$%06X  R=[SP]=$%06X (trap exit here)"%(TGT,SP&0xFFFFFF,R),flush=True)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7516,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def rd(a,n,mt='Sa1Memory'): return bytes(m.read_memory(mt,a,n))
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    runf(600)
    def run_on():
        for attempt in range(8):
            m.load_state(NAT)
            wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7))); wh(0x3C, le32(SP))
            w16(0x60,Z);w16(0x6E,C);w16(0x70,N);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7);w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0);w16(0xAC,0x7000)
            w16(0x0718,0xFFF8)
            for o in range(0,0x10000,0x4000): wh(0x400000+o,wram[o:o+0x4000].hex(),'snesMemory')
            w16(0x410000,0x0100,'snesMemory'); w16(0x410002,0x0100,'snesMemory')
            # synthetic `jmp (a0)` ($4ED0) at SCRATCH with a0 = TGT -> op_jmp_idx -> ojmp_hook -> table
            wh(0x400000+SCRATCH, '4ed0','snesMemory'); wh(0x20, le32(TGT)); w16(0x40,SCRATCH); w16(0x42,0x00F0)
            w16(0x071A,1); w16(0x0712,0); w16(0x0710,R&0xFFFF); w16(0x0716,(R>>16)&0xFF); w16(0x0702,0); w16(0x0704,1)
            for _ in range(60):
                runf(20)
                if r16(0x0712) or r16(0x0702): break
            if r16(0x0712): return rd(0x400000,0x10000,'snesMemory'), rd(0x00,0x3C)
            print("  attempt %d froze=0, retry"%attempt,flush=True)
        return None,None
    esc,escr=run_on()
    assert esc is not None, "escape never trapped at R=$%06X"%R
    def le(b,s): i=s*4; return b[i]|(b[i+1]<<8)|(b[i+2]<<16)|(b[i+3]<<24)
    # a0 was overwritten with TGT for dispatch -> exclude a0 from the reg compare
    rdiff=[RN[s] for s in range(15) if s!=8 and le(escr,s)!=be32(exitr,s*4)]
    print("REG diff (excl a0=dispatch) escape-vs-MAME: %s"%(rdiff or 'NONE'),flush=True)
    for s in range(15):
        if RN[s] in rdiff: print("   %s: esc=%08X mame=%08X"%(RN[s],le(escr,s),be32(exitr,s*4)),flush=True)
    a7=SP&0xFFFF; STK=0x200
    excl=set(range(SCRATCH,SCRATCH+2)) | set((a7-1-k)&0xFFFF for k in range(STK))
    mism=[i for i in range(0x10000) if esc[i]!=exitw[i] and i not in excl]
    print("escape-vs-MAME $40 mismatches (excl scratch/stack): %d"%len(mism),flush=True)
    for i in mism[:20]: print("   $F0%04X: esc=%02X mame=%02X (entry=%02X)"%(i,esc[i],exitw[i],wram[i]),flush=True)
    ok=(not mism) and (not rdiff)
    print(">>>", "GREEN -- jmp-state entry_%x == MAME ground truth"%TGT if ok
          else "RED -- $40 mismatches=%d ; regdiff=%s"%(len(mism), rdiff or 'none'),flush=True)
