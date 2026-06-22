import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u16(b,o): return b[o]|(b[o+1]<<8)
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
COIN=0x2000; START=0x1000
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    def gf(): return u32(dp(0x4A,4),0)//28672
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    def st():
        pc=u16(dp(0x40),0)|(u16(dp(0x42),0)<<16); op=u16(dp(0x44),0)
        return f"step={u32(dp(0x4A,4),0)} PC=${pc:06X} op=${op:04X} stop=${u16(dp(0x4E),0):04X} tmask=${u16(m.read_memory('snesMemory',0x400002,2),0):04X} cr=${m.read_memory('snesMemory',0x401C63,1)[0]:02X}"
    def bg(): return sum(1 for x in m.read_memory("snesMemory",0x414800,0x1000) if x!=0)
    cur=-1; laststep=-1; stuckcnt=0
    for it in range(300):
        m.run_frames(150); g=gf()
        if 105<=g<113 or 120<=g<128: inp=COIN
        elif 140<=g<150: inp=START
        else: inp=0
        if inp!=cur: poke(inp); cur=inp
        step=u32(dp(0x4A,4),0)
        tm=u16(m.read_memory('snesMemory',0x400002,2),0); bgn=bg()
        if g>=135:
            print(f"gF~{g} {st()} BG={bgn}", flush=True)
        if (tm>>8)==0x3B or bgn>50:
            print(f"*** GAMEPLAY REACHED at gF~{g} tmask=${tm:04X} BG={bgn} ***", flush=True)
            print("shot:", m.take_screenshot(format="path")); break
        if step==laststep: stuckcnt+=1
        else: stuckcnt=0
        laststep=step
        if stuckcnt>=3 and g>=140:
            print("=== HALTED ===", flush=True); print(st(), flush=True)
            idx=u16(dp(0x48),0)&0xFF; rb=dp(0x0400,0x100)
            print("ring(newest first):", " ".join(f"{u32(rb,(idx-4*(k+1))&0xFF):06X}" for k in range(20)), flush=True)
            break
        if g>=218: print("reached gf218, no gameplay, no halt; tmask=$%04X"%tm); break
