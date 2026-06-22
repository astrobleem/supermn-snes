import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
def u16(b,o): return b[o]|(b[o+1]<<8)
def nz(b): return sum(1 for x in b if x!=0)
COIN=0x2000; START=0x1000
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    def gf(): return u32(dp(0x4A,4),0)//28672
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    def b(a): return m.read_memory("snesMemory",a,1)[0]
    def tmask(): return u16(m.read_memory('snesMemory',0x400002,2),0)
    def bg(): return nz(m.read_memory("snesMemory",0x414800,0x1000))
    cur=-1
    for it in range(140):
        m.run_frames(150); g=gf()
        # coin1 105-113, coin2 120-128 (credits=2), start 140-150 (single clean press)
        if 105<=g<113 or 120<=g<128: inp=COIN
        elif 140<=g<150: inp=START
        else: inp=0
        if inp!=cur: poke(inp); cur=inp
        if g>=132:
            tm=tmask()
            last=u16(dp(0xB4,2),0); prev=u16(dp(0xB6,2),0)
            print(f"gF~{g} inp=${inp:04X} cr[1C63]=${b(0x401C63):02X} 8(A6)_last=${last:04X} 8(A6)_prev=${prev:04X} tmask=${tm:04X}", flush=True)
            if (tm>>8)==0x3B or bg()>50:
                print(f"*** GAMEPLAY at gF~{g} tmask=${tm:04X} ***", flush=True)
                print("shot:", m.take_screenshot(format="path")); break
        if g>=162:
            print("DONE start test", flush=True); break
