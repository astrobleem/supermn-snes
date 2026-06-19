import sys, os, zlib
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
def u16(b,o): return b[o]|(b[o+1]<<8)
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def pc(): return u32(m.read_memory("snesWorkRam",0x40,4),0)
    def wramcrc(): return zlib.crc32(m.read_memory("snesWorkRam",0x10000,0x8000))
    left818=False; reachedmain=False; pcs=set(); crcs=[]
    total=0
    for i in range(14):
        m.run_frames(200); total+=200
        p=pc(); pcs.add(p); crcs.append(wramcrc())
        if p!=0x818: left818=True
        if p==0x532 or (0xA400<=p<=0xA4FF) or (0x2E6A==p): reachedmain=True
        print(f"  @{total}f PC=${p:06X} steps={u32(m.read_memory('snesWorkRam',0x4a,4),0)} crc={crcs[-1]:08X}", flush=True)
    # ring buffer (snesWorkRam 0x0800 = $7E:0800), if still stuck
    rb=m.read_memory("snesWorkRam",0x0800,0x100)
    recent=sorted(set(f"{u32(rb,k):06X}" for k in range(0,0x100,4)))
    crc_evolves = len(set(crcs[-6:]))>1
    print(f"\nM1 (left $0818): {left818}")
    print(f"M2 (reached $0532/$A4xx/main): {reachedmain}   distinct PCs seen: {sorted(f'${x:06X}' for x in pcs)}")
    print(f"M3 (workRAM evolving): {crc_evolves}")
    print(f"ring buffer recent PCs: {recent}")
