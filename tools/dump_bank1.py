import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
LOG=open("/home/chad/supermn-snes/dump_bank1.out","w")
def out(*a):
    s=" ".join(str(x) for x in a); LOG.write(s+"\n"); LOG.flush(); print(s,flush=True)
def u16(b,o): return b[o]|(b[o+1]<<8)
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
def nz(b): return sum(1 for x in b if x!=0)
def be16(b,o): return (b[o]<<8)|b[o+1]
START=0x1000
def dumpregion(b, base, label):
    out(f"--- {label} @ ${base:06X} ---")
    fnz=next((i for i,x in enumerate(b) if x!=0), None)
    out(f"  nz_bytes={nz(b)} first_nz_off={fnz}")
    out("  start[0..24] BE:", " ".join(f"{be16(b,2*i):04X}" for i in range(24)))
    if fnz is not None and fnz>=4:
        o=fnz&~1
        out(f"  @firstnz off={o}:", " ".join(f"{be16(b,o+2*i):04X}" for i in range(24)))
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    def gf(): return u32(dp(0x4A,4),0)//28672
    def tmask(): return u16(m.read_memory('snesMemory',0x400002,2),0)
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    m.load_state_slot(4)
    out("loaded slot4 gf~",gf())
    poke(START)
    done=False
    for it in range(120):
        m.run_frames(150)
        g=gf(); tm=tmask()
        if it%4==0: out(f"it{it} gF~{g} tmask=${tm:04X}")
        if (tm>>8)==0x3B or g>=250:
            out(f"reached gF~{g} tmask=${tm:04X}")
            # find the brick-BG sequence 1634 1635 1636 (BE bytes) anywhere in $40 work RAM and $41 shadow
            seq=bytes([0x16,0x34,0x16,0x35,0x16,0x36])
            for bank in (0x40,0x41):
                blob=m.read_memory("snesMemory",bank<<16,0x10000)
                i=blob.find(seq); locs=[]
                while i>=0 and len(locs)<5:
                    locs.append(i); i=blob.find(seq,i+1)
                out(f"  brick-seq in ${bank:02X}: "+("NONE" if not locs else " ".join(f"${bank:02X}:{x:04X}" for x in locs)))
            # also any lone 1634 in each bank
            for bank in (0x40,0x41):
                blob=m.read_memory("snesMemory",bank<<16,0x10000)
                cnt=sum(1 for k in range(0,len(blob)-1) if blob[k]==0x16 and blob[k+1]==0x34)
                out(f"  bytes 16 34 in ${bank:02X}: {cnt}")
            code=m.read_memory("snesMemory",0x414800,0x400)
            col =m.read_memory("snesMemory",0x414C00,0x400)
            dumpregion(code,0x414800,"bank1 CODE")
            dumpregion(col, 0x414C00,"bank1 COL")
            for name,addr in (("2A32",0x402A32),("2A34",0x402A34),("2A37",0x402A37),("2A38",0x402A38),("2A3C",0x402A3C)):
                w=m.read_memory("snesMemory",addr,4)
                out(f"  ${name}: {w[0]:02X} {w[1]:02X} {w[2]:02X} {w[3]:02X}")
            done=True; break
    if not done: out("never reached level; last gF~",gf())
out("DONE")
