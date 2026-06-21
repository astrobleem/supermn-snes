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
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    def runf(n):
        while n>0: c=min(150,n); m.run_frames(c); n-=c
    def stat(t):
        print(f"  [{t}] tmask=$%04X BGnz=%d stop=$%04X step=%d"%(u16(m.read_memory('snesMemory',0x400002,2),0), nz(m.read_memory("snesMemory",0x414800,0x1000)), u16(dp(0x4E),0), u32(dp(0x4A,4),0)), flush=True)
    runf(1800); stat("title")
    # 4 clean coin pulses
    for i in range(4):
        poke(0x2000); runf(160); poke(0); runf(160)
    stat("4 coins")
    # start, held across a couple game-frames
    poke(0x1000); runf(300); poke(0); runf(300); stat("start#1")
    poke(0x1000); runf(300); poke(0); runf(300); stat("start#2")
    for k in range(5):
        runf(500); stat(f"+{(k+1)*500}f")
        if nz(m.read_memory("snesMemory",0x414800,0x1000))>50:
            print("   *** BG POPULATED ***"); break
    print("screenshot:", m.take_screenshot(format="path"))
