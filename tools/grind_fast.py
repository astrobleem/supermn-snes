import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u16(b,o): return b[o]|(b[o+1]<<8)
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
START=0x1000
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    def gf(): return u32(dp(0x4A,4),0)//28672
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    def b(a): return m.read_memory("snesMemory",a,1)[0]
    def tmask(): return u16(m.read_memory('snesMemory',0x400002,2),0)
    def bg(): return sum(1 for x in m.read_memory("snesMemory",0x414800,0x1000) if x!=0)
    def st():
        pc=u16(dp(0x40),0)|(u16(dp(0x42),0)<<16); op=u16(dp(0x44),0)
        return f"PC=${pc:06X} op=${op:04X} stop=${u16(dp(0x4E),0):04X} tmask=${tmask():04X} cr=${b(0x401C63):02X} BG={bg()}"
    m.load_state_slot(1)
    g0=gf()
    print(f"LOADED slot 1: gF~{g0} cr=${b(0x401C63):02X} tmask=${tmask():04X}", flush=True)
    if b(0x401C63)!=0x02 or g0<120:
        print("!! slot load looks wrong (cross-ROM incompatible?) — abort", flush=True); sys.exit(0)
    poke(START); lastg=-1; stuck=0; rel=False
    for it in range(90):
        m.run_frames(150); g=gf()
        if g>=g0+10 and not rel: poke(0); rel=True
        step=u32(dp(0x4A,4),0); tm=tmask(); bgn=bg()
        if g==lastg: stuck+=1
        else: stuck=0
        lastg=g
        if stuck>=5:
            print(f"=== GAME-FRAME FROZEN at gF~{g} (infinite loop in one frame) ===", flush=True)
            print(st(), flush=True)
            idx=u16(dp(0x48),0)&0xFF; rb=dp(0x0400,0x100)
            print("ring:", " ".join(f"{u32(rb,(idx-4*(k+1))&0xFF):06X}" for k in range(28)), flush=True)
            # An regs $20+n*4 (A0..A7), Dn $00+n*4 (D0..D7)
            reg=dp(0x00,0x40)
            print("A:", " ".join(f"A{n}={u32(reg,0x20+n*4):06X}" for n in range(8)), flush=True)
            print("D:", " ".join(f"D{n}={u32(reg,n*4):08X}" for n in range(8)), flush=True)
            break
        if g%4==0 or bgn>0 or (tm>>8)==0x3B:
            print(f"gF~{g} {st()}", flush=True)
        if bgn>50:
            print(f"*** PLAYFIELD RENDERED: tmask=${tm:04X} BG={bgn} at gF~{g} ***", flush=True)
            print("shot:", m.take_screenshot(format="path")); break
        if u16(dp(0x4E),0)==0xDEAD:
            print("=== HALTED $DEAD ===", flush=True); print(st(), flush=True); break
        if g>=g0+150:
            print(f"reached gF{g}, tmask=${tm:04X} BG={bgn}, no render/halt", flush=True)
            print("shot:", m.take_screenshot(format="path")); break
