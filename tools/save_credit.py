import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u16(b,o): return b[o]|(b[o+1]<<8)
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
COIN=0x2000
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    def gf(): return u32(dp(0x4A,4),0)//28672
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    def b(a): return m.read_memory("snesMemory",a,1)[0]
    def tmask(): return u16(m.read_memory('snesMemory',0x400002,2),0)
    cur=-1
    for it in range(170):
        m.run_frames(150); g=gf()
        if 105<=g<113 or 120<=g<128: inp=COIN
        else: inp=0
        if inp!=cur: poke(inp); cur=inp
        if g>=135:
            poke(0)
            bgnz=sum(1 for x in m.read_memory("snesMemory",0x414800,0x1000) if x!=0)
            print(f"at gF~{g} cr=${b(0x401C63):02X} tmask=${tmask():04X} BG($414800 nz)={bgnz}", flush=True)
            m.save_state_slot(1)
            print("SAVED credited-attract slot 1 (gf%d, credits=2)"%g, flush=True)
            break
