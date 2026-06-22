import sys, os
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
    def gf(): return u32(dp(0x4A,4),0)//28672
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    def tmask(): return u16(m.read_memory('snesMemory',0x400002,2),0)
    m.load_state_slot(1); g0=gf()
    print(f"loaded gF~{g0} cr=${m.read_memory('snesMemory',0x401C63,1)[0]:02X}", flush=True)
    poke(0x1000); rel=False
    for it in range(70):
        m.run_frames(150); g=gf()
        if g>=g0+10 and not rel: poke(0); rel=True
        if (tmask()>>8)==0x3B and g>=g0+95: break
    print(f"gameplay gF~{g} tmask=${tmask():04X}", flush=True)
    # shadow region nonzero counts ($41 = arcade video shadow)
    for name,addr in [("pal $412000",0x412000),("sprcode $414000",0x414000),
                      ("bg-shadow $414800",0x414800),("bg-shadow $414C00",0x414c00),
                      ("WORKRAM $400800",0x400800),("WORKRAM $400C00",0x400c00),
                      ("WORKRAM $404800",0x404800)]:
        try: print(f"  {name}: nz={nz(m.read_memory('snesMemory',addr,0x800))}", flush=True)
        except Exception as e: print(f"  {name}: err {e}", flush=True)
    try:
        pp=m.get_ppu_state()
        print("PPU:", {k:pp.get(k) for k in ('bgMode','mainScreenLayers','subScreenLayers','forcedBlank','screenBrightness') if k in pp}, flush=True)
    except Exception as e: print("ppu err", e, flush=True)
    print("shot:", m.take_screenshot(format="path"), flush=True)
