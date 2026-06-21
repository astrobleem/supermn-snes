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
    def wram(): return m.read_memory("snesMemory",0x400000,0x4000)  # work RAM low 16KB
    def st(): return f"step={u32(dp(0x4A,4),0)} tmask=${u16(m.read_memory('snesMemory',0x400002,2),0):04X} BGnz={nz(m.read_memory('snesMemory',0x414800,0x1000))} stop=${u16(dp(0x4E),0):04X}"
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    def runf(n):
        while n>0: c=min(150,n); m.run_frames(c); n-=c
    def diff(a,b,tag):
        ch=[(i,a[i],b[i]) for i in range(len(a)) if a[i]!=b[i]]
        print(f"  {tag}: {len(ch)} bytes changed:", " ".join(f"40{i:04X}:{x:02X}->{y:02X}" for i,x,y in ch[:24]))
    runf(1800); print("title:", st())
    a=wram()
    poke(0x2000); runf(240); poke(0); runf(120)   # coin held ~2 game-frames, release
    b=wram(); print("after coin1:", st()); diff(a,b,"coin1 diff")
    poke(0x2000); runf(240); poke(0); runf(120)   # second coin
    c=wram(); print("after coin2:", st()); diff(b,c,"coin2 diff")
    poke(0x1000); runf(240); poke(0); runf(300)   # start held ~2 game-frames
    d=wram(); print("after start:", st()); diff(c,d,"start diff")
    runf(800); print("after +800f:", st())
    pc=u16(dp(0x40),0)|(u16(dp(0x42),0)<<16); op=u16(dp(0x44),0)
    print(f"HALT PC=${pc:06X} op=${op:04X} stop=${u16(dp(0x4E),0):04X}")
    idx=u16(dp(0x48),0)&0xFF; rb=dp(0x0400,0x100)
    print("ring:", " ".join(f"{u32(rb,(idx-4*(k+1))&0xFF):06X}" for k in range(16)))
