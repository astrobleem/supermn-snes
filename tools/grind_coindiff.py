import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
COIN=0x2000
def want(gf):
    if 120<=gf<135 or 150<=gf<160: return COIN
    return 0
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    def gf(): return u32(dp(0x4A,4),0)//28672
    def wr(): return m.read_memory("snesMemory",0x400000,0x2000)
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    snap=None; cur=-1
    for it in range(200):
        m.run_frames(150)
        g=gf(); inp=want(g)
        if inp!=cur: poke(inp); cur=inp
        if snap is None and g>=110:
            snap=wr(); print(f"snapshot at gF~{g}; A8(phase)=${dp(0xA8,1)[0]:02X} A2(X)=${dp(0xA2,1)[0]:02X}", flush=True)
        if snap is not None and g>=185:
            s2=wr()
            ch=[(i,snap[i],s2[i]) for i in range(len(snap)) if snap[i]!=s2[i]]
            print(f"INTERP coin diff gF110->gF{g}: {len(ch)} bytes changed", flush=True)
            for i,a,b in ch: print(f"  40{i:04X}: {a:02X} -> {b:02X}", flush=True)
            print(f"A8(phase)=${dp(0xA8,1)[0]:02X}", flush=True)
            break
