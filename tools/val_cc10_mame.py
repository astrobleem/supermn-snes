# Validate entry_cc10 (the ON escape) against MAME GROUND TRUTH. Inject $00CC10's MAME entry frame on
# the deterministic native base, run the escape via synthetic jsr to the $F0FF06 trap, then diff the
# escape's resulting $40 work RAM against MAME's captured exit_wram. They must match everywhere except
# the synthetic scratch ($FF00-$FF07) and the escape's pushed return (a7-4). This bypasses the broken
# OFF interpreter reference entirely -- compares the escape directly to the arcade.
import sys, os, json
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TGT=0xCC10; FD='/tmp/supermn-scratch/frame_cc10'; SCRATCH=0xFF00
regs=open(FD+'/entry_regs.bin','rb').read(); wram=open(FD+'/entry_wram.bin','rb').read(); exitw=open(FD+'/exit_wram.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]; SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
Z=(SR>>2)&1;C=SR&1;N=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
jsrb=bytes([0x4E,0xB9,0x00,0x00,(TGT>>8)&0xFF,TGT&0xFF])
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7505,boot_wait=6.0,socket_timeout=300.0) as m:
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
            wh(0x400000+SCRATCH, jsrb.hex(),'snesMemory'); w16(0x40,SCRATCH); w16(0x42,0x00F0)
            w16(0x071A,1); w16(0x0712,0); w16(0x0710,SCRATCH+6); w16(0x0716,0x00F0); w16(0x0702,0); w16(0x0704,1)
            for _ in range(60):
                runf(20)
                if r16(0x0712) or r16(0x0702): break
            if r16(0x0712): return rd(0x400000,0x10000,'snesMemory')
            print("  attempt %d froze=0, retry"%attempt,flush=True)
        return None
    esc=run_on()
    assert esc is not None, "escape never trapped"
    a7=SP&0xFFFF
    excl=set(range(SCRATCH,SCRATCH+8)) | set(range((a7-4)&0xFFFF,((a7-4)&0xFFFF)+4))
    # MAME ground-truth deltas (entry->exit), and the escape's deltas (entry->escape)
    mame_d={i:(wram[i],exitw[i]) for i in range(0x10000) if wram[i]!=exitw[i] and i not in excl}
    esc_d ={i:(wram[i],esc[i])   for i in range(0x10000) if wram[i]!=esc[i]   and i not in excl}
    print("MAME deltas (%d): %s"%(len(mame_d),{("$F0%04X"%i):"%02X->%02X"%v for i,v in sorted(mame_d.items())}),flush=True)
    print("ESC  deltas (%d): %s"%(len(esc_d), {("$F0%04X"%i):"%02X->%02X"%v for i,v in sorted(esc_d.items())}),flush=True)
    # full-image mismatch (excluding scratch/stack): escape work RAM must equal MAME exit work RAM
    mism=[i for i in range(0x10000) if esc[i]!=exitw[i] and i not in excl]
    print("escape-vs-MAME full $40 mismatches (excl scratch/stack): %d"%len(mism),flush=True)
    for i in mism[:30]: print("   $F0%04X: esc=%02X mame=%02X (entry=%02X)"%(i,esc[i],exitw[i],wram[i]),flush=True)
    print(">>>", "GREEN -- entry_cc10 == MAME ground truth (bit-exact)" if not mism else "RED -- %d mismatches"%len(mism),flush=True)
