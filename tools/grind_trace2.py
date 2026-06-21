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
    def stp(): return u16(dp(0x4E),0)
    def ring():
        rb=dp(0x0400,0x100); idx=u16(dp(0x48),0)&0xFF
        order=[(idx-4*(k+1))&0xFF for k in range(64)]
        return [u32(rb,o) for o in order if o+4<=0x100]
    seen=[]
    total=0; halted=False
    while total<1400:
        m.run_frames(3); total+=3
        if stp()!=0:
            halted=True; print(f"HALT at frame {total}"); break
        for v in reversed(ring()):
            if not seen or v!=seen[-1]: seen.append(v)
    comp=[]
    for v in seen:
        if not comp or comp[-1]!=v: comp.append(v)
    print(f"halted={halted}; path len={len(comp)}; last 140:")
    print(" ".join(f"{v:06X}" for v in comp[-140:]))
