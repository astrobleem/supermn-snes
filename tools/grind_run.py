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
    def wcrc(): return zlib.crc32(m.read_memory("snesMemory",0x400000,0x10000))
    def pc(): return u16(dp(0x40),0)|(u16(dp(0x42),0)<<16)
    def runf(n):
        while n>0: c=min(150,n); m.run_frames(c); n-=c
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    runf(1800)
    poke(0x2000); runf(240); poke(0); runf(120)   # coin
    for k in range(8):
        runf(300)
        bg=nz(m.read_memory("snesMemory",0x414800,0x1000))
        cnt=m.read_memory("snesMemory",0x401C7A,2)[0]
        print(f"  +{(k+1)*300}f: PC=${pc():06X} tmask=${u16(m.read_memory('snesMemory',0x400002,2),0):04X} BGnz={bg} cnt40:1C7A=${cnt:02X} wcrc={wcrc():08X}", flush=True)
