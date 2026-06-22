import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
COIN=0x2000; START=0x1000
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    def gf(): return u32(dp(0x4A,4),0)//28672
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    def rb(addr,n): return m.read_memory("snesMemory",addr,n)
    def hexs(b): return " ".join(f"{x:02X}" for x in b)
    cur=-1; a5base=None
    for it in range(160):
        m.run_frames(150); g=gf()
        # coin held gf108-128, start held gf134-150
        if 108<=g<128: inp=COIN
        elif 134<=g<150: inp=START
        else: inp=0
        if inp!=cur: poke(inp); cur=inp
        if g>=100:
            a5=u32(dp(0x2A,4),0)            # A5 register
            mb=u32(dp(0x66,2)&0 if False else dp(0x66,2),0) if False else None
            # input store = (A5 & 0xFFFF)+1C4E within work RAM bank $40
            base=0x400000 + ((a5)&0xFFFF)
            store=rb(base+0x1C4E,4)         # $1C4E/4F/50 = P1/P2/coins
            mail=rb(0x410000,4)             # mailbox (joy_read source) + $410002 poke
            print(f"gF~{g} inp=${inp:04X} A5=${a5:06X} store[1C4E..51]={hexs(store)} mailbox={hexs(mail)}", flush=True)
        if g>=158: break
