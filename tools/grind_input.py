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
    def status(tag):
        bg=nz(m.read_memory("snesMemory",0x414800,0x1000))
        tm=u16(m.read_memory("snesMemory",0x400002,2),0)
        mb=u16(m.read_memory("snesMemory",0x410000,2),0)
        try: uc=m.take_screenshot(format="path").get("unique_colors")
        except: uc="?"
        st=u16(dp(0x4E),0); pc=u16(dp(0x40),0)|(u16(dp(0x42),0)<<16); op=u16(dp(0x44),0)
        print(f"  [{tag}] step={u32(dp(0x4A,4),0)} tmask=${tm:04X} mailbox=${mb:04X} BGnz={bg} colors={uc} stop=${st:04X} PC=${pc:06X} op=${op:04X}", flush=True)
    def runf(n):
        while n>0: c=min(150,n); m.run_frames(c); n-=c
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    runf(1800); status("clean idle, 1800f")
    runf(1200); status("clean idle, 3000f")
    # inject COIN (SNES Select = bit13 = $2000) briefly
    poke(0x2000); runf(60); poke(0); runf(240); status("after coin pulse")
    # inject START (bit12 = $1000)
    poke(0x1000); runf(60); poke(0); runf(360); status("after start pulse")
    # ring buffer at the halt (most-recent first)
    idx=u16(dp(0x48),0)&0xFF; rb=dp(0x0400,0x100)
    seq=[u32(rb,(idx-4*(k+1))&0xFF) for k in range(20)]
    print("  ring:", " ".join(f"{v:06X}" for v in seq))
    rf=dp(0x00,0x40)
    print("  A0-A7:", " ".join(f"{u32(rf,0x20+4*i):08X}" for i in range(8)))
