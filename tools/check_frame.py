import sys, os
sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
def be(b,o): return (b[o]<<8)|b[o+1]
with McpSession(rom="/home/chad/supermn-snes/build/interp.sfc",mesen="/home/chad/Mesen2/bin/linux-x64/Release/Mesen",port=7361,boot_wait=5.0) as m:
    for i in range(16): m.run_frames(200)
    print("tmask",hex(be(m.read_memory('snesWorkRam',0x10002,2),0)),"F01C56",be(m.read_memory('snesWorkRam',0x11C56,2),0))
    m.run_frames(200)
    print("F01C56 again",be(m.read_memory('snesWorkRam',0x11C56,2),0))
    shot=m.take_screenshot(format="path"); print("screenshot:",shot)
