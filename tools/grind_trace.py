import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
def u16(b,o): return b[o]|(b[o+1]<<8)
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2):   # SA-1 DP / IRAM
        return m.read_memory("Sa1Memory", o, n)
    def pc():  return u16(dp(0x40),0)|(u16(dp(0x42),0)<<16)
    def stp(): return u16(dp(0x4E),0)
    def stepc(): return u32(dp(0x4A,4),0)
    def opc(): return u16(dp(0x44),0)
    total=0; halted=False
    for i in range(40):
        m.run_frames(150); total+=150
        s=stp()
        print(f"  @{total}f PC=${pc():06X} op=${opc():04X} step={stepc()} stop=${s:04X}", flush=True)
        if s!=0:
            halted=True; break
    # full ring buffer: Sa1Memory $0400, 64 entries * 4 bytes; idx at $48
    rb=dp(0x0400, 0x100)
    idx=u16(dp(0x48),0)
    print(f"\nHALTED={halted} ring idx=${idx:04X}")
    n=idx&0xFF
    order=[(n - 4*(k+1)) & 0xFF for k in range(0,64)]  # most-recent first
    seq=[u32(rb,o) for o in order if o+4<=0x100]
    print("ring (most-recent first):", " ".join(f"{v:06X}" for v in seq[:40]))
    # 68K register file D0-D7 ($00-$1F), A0-A7 ($20-$3F)
    rf=dp(0x00,0x40)
    print("D0-D7:", " ".join(f"{u32(rf,4*i):08X}" for i in range(8)))
    print("A0-A7:", " ".join(f"{u32(rf,0x20+4*i):08X}" for i in range(8)))
