import sys, os, shutil
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u16(b,o): return b[o]|(b[o+1]<<8)
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
START=0x1000
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def gf(): return u32(m.read_memory("Sa1Memory",0x4A,4),0)//28672
    def tmask(): return u16(m.read_memory('snesMemory',0x400002,2),0)
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    m.load_state_slot(4); poke(START)
    for it in range(80):
        m.run_frames(150)
        if (tmask()>>8)==0x3B and it>40:
            break
    m.run_frames(8)
    print("gf",gf(),"tmask",hex(tmask()),flush=True)
    p=m.take_screenshot(format="path")
    print("shot",p,flush=True)
    try: shutil.copy(p,"/home/chad/supermn-snes/bg_render.png"); print("copied to bg_render.png")
    except Exception as e: print("copy err",e)
