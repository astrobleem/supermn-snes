import sys, os, zlib
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u16(b,o): return b[o]|(b[o+1]<<8)
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
def nz(b): return sum(1 for x in b if x!=0)
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    for _ in range(16): m.run_frames(150)
    print("step:", u32(dp(0x4A,4),0), "tmask $40:0002=$%04X"%u16(m.read_memory("snesMemory",0x400002,2),0))
    # video shadow $41: palette $2000, sprite Y/ctrl $3000, sprite code/X $4000
    pal=m.read_memory("snesMemory",0x412000,0x1000)
    d0 =m.read_memory("snesMemory",0x413000,0x1000)
    cod=m.read_memory("snesMemory",0x414000,0x4000)
    print(f"shadow $41 nonzero bytes: pal={nz(pal)}/4096  d0={nz(d0)}/4096  code={nz(cod)}/16384")
    # does the SA-1 write the shadow ($41) over the next frames?
    h=m.add_write_hook(0x412000,0x417FFF,cpu_type="Sa1")
    m.run_frames(20)
    notes=m.drain_notifications(timeout=0.3)
    print(f"SA-1 writes to shadow $41 over 20f: {len(notes)}")
    # does the game leave the idle loop? sample PC over frames
    pcs={}
    for _ in range(30):
        m.run_frames(2)
        p=u16(dp(0x40),0)|(u16(dp(0x42),0)<<16); pcs[p]=pcs.get(p,0)+1
    print("PC histogram (30 samples):", {f"${k:06X}":v for k,v in sorted(pcs.items(),key=lambda x:-x[1])[:8]})
