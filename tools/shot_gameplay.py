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
    for it in range(40):
        m.run_frames(500)
        if (tmask()>>8)==0x3B and it>=14:
            break
    for _ in range(2):  # let the level palette finish loading/fading in
        m.run_frames(500)
    m.save_state_slot(5)   # settled-gameplay state for fast re-use
    print("gf",gf(),"tmask",hex(tmask()),flush=True)
    def hx(b): return " ".join(f"{b[i]|(b[i+1]<<8):04X}" for i in range(0,len(b),2))
    cg=m.read_memory("snesCgRam",0,64)
    print("CGRAM slot0:",hx(cg[0:32]),flush=True)
    print("CGRAM slot1:",hx(cg[32:64]),flush=True)
    tbl=m.read_memory("snesMemory",0x7E8940,32)
    print("bank->slot:"," ".join(f"{i}:{tbl[i]:02X}" for i in range(32) if tbl[i]!=0xFF),flush=True)
    sh=m.read_memory("snesMemory",0x412240,32)
    print("bank18 shadow:",hx(sh),flush=True)
    dg=m.read_memory("snesMemory",0x7E8A00,4)
    print("FILL dst=%04X F0=%04X"%(dg[0]|(dg[1]<<8),dg[2]|(dg[3]<<8)),flush=True)
    st=m.read_memory("snesMemory",0x7E8000,32)
    print("staging slot0:",hx(st),flush=True)
    b0=m.read_memory("snesMemory",0x412000,32)
    print("bank0 shadow:",hx(b0),flush=True)
    p=m.take_screenshot(format="path")
    print("shot",p,flush=True)
    try: shutil.copy(p,"/home/chad/supermn-snes/bg_render.png"); print("copied to bg_render.png")
    except Exception as e: print("copy err",e)
# (appended diag read happens via separate run)
