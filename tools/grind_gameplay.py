import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u16(b,o): return b[o]|(b[o+1]<<8)
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
def nz(b): return sum(1 for x in b if x!=0)
# MAME-matched game-frame schedule: coin1 120-135, coin2 150-160, start 200-215, gameplay ~251
COIN=0x2000; START=0x1000
def want_input(gf):
    if 120<=gf<135: return COIN
    if 150<=gf<160: return COIN
    if 200<=gf<215: return START
    return 0
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    def gf(): return u32(dp(0x4A,4),0)//28672
    def tmask(): return u16(m.read_memory('snesMemory',0x400002,2),0)
    def bg(): return nz(m.read_memory("snesMemory",0x414800,0x1000))
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    cur=-1; last_tm=None
    for it in range(220):                 # plenty of chunks to reach gf~290
        m.run_frames(150)
        g=gf(); inp=want_input(g)
        if inp!=cur: poke(inp); cur=inp
        tm=tmask()
        if tm!=last_tm:
            print(f"gF~{g} tmask=${tm:04X} BGnz={bg()} inp=${inp:04X}", flush=True)
            last_tm=tm
        elif it%6==0:
            print(f"gF~{g} tmask=${tm:04X} BGnz={bg()} inp=${inp:04X}", flush=True)
        if (tm>>8)==0x3B or bg()>50:   # gameplay $003B BE = $3B00 LE (hi byte $3B)
            print(f"*** GAMEPLAY tmask=${tm:04X} BGnz={bg()} at gF~{g} ***", flush=True)
            print("screenshot:", m.take_screenshot(format="path"))
            break
        if g>=295:
            print(f"reached gF{g} without gameplay; final tmask=${tm:04X} BGnz={bg()}")
            print("screenshot:", m.take_screenshot(format="path"))
            break
