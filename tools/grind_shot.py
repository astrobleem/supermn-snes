import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u16(b,o): return b[o]|(b[o+1]<<8)
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    for _ in range(20): m.run_frames(150)
    # is the game state evolving? sample work RAM crc + the frame mailbox
    import zlib
    def wcrc(): return zlib.crc32(m.read_memory("snesMemory",0x400000,0x4000))
    c1=wcrc(); fr1=u16(dp(0x300,2)) if False else None
    m.run_frames(120); c2=wcrc()
    print("step:", u32(dp(0x4A,4),0), "PC=$%06X"%(u16(dp(0x40),0)|(u16(dp(0x42),0)<<16)))
    print("work-RAM evolving across 120f:", c1!=c2, f"({c1:08X} -> {c2:08X})")
    # ppu state + screenshot
    try:
        ppu=m.get_ppu_state()
        print("PPU:", {k:ppu.get(k) for k in ("forcedBlank","bgMode","mainScreenLayers","brightness") if k in ppu})
    except Exception as e: print("ppu err", e)
    shot=m.take_screenshot(format="path")
    print("screenshot:", shot)
