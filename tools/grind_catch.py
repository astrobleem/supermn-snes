import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
def u16(b,o): return b[o]|(b[o+1]<<8)
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    def pc():  return u16(dp(0x40),0)|(u16(dp(0x42),0)<<16)
    def stp(): return u16(dp(0x4E),0)
    def stepc(): return u32(dp(0x4A,4),0)
    def opc(): return u16(dp(0x44),0)
    total=0
    for i in range(40):
        m.run_frames(150); total+=150
        s=stp()
        print(f"  @{total}f PC=${pc():06X} op=${opc():04X} step={stepc()} stop=${s:04X}", flush=True)
        if s!=0:
            print(f"  -> HALTED at step {stepc()}, PC ${pc():06X}, op ${opc():04X}")
            break
    else:
        print(f"  -> still running after {total}f, step={stepc()}")
