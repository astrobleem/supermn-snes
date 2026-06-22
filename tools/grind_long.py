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
    def runf(n):
        while n>0: c=min(150,n); m.run_frames(c); n-=c
    total=0
    base_tm=None
    for k in range(60):           # up to 90000 frames
        runf(1500); total+=1500
        tm=u16(m.read_memory('snesMemory',0x400002,2),0)
        bg=nz(m.read_memory("snesMemory",0x414800,0x1000))
        st=u32(dp(0x4A,4),0)
        if base_tm is None: base_tm=tm
        print(f"@{total}f gF~{st//28672} tmask=${tm:04X} BGnz={bg}", flush=True)
        if bg>50:
            print(f"*** BG POPULATED at {total}f (gameFrame ~{st//28672}) -> gameplay/demo ***", flush=True)
            print("screenshot:", m.take_screenshot(format="path"))
            break
        if tm!=base_tm:
            print(f"*** tmask CHANGED ${base_tm:04X}->${tm:04X} at {total}f -- attract advancing ***", flush=True)
            base_tm=tm
    else:
        print("no BG populate / no sustained change after 90000f")
        print("screenshot:", m.take_screenshot(format="path"))
