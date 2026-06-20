import sys, os
sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
with McpSession(rom="/home/chad/supermn-snes/build/interp.sfc",mesen="/home/chad/Mesen2/bin/linux-x64/Release/Mesen",port=7358,boot_wait=5.0) as m:
    for i in range(15): m.run_frames(200)
    tm=m.read_memory("snesWorkRam",0x10002,2); print(f"tmask=${(tm[0]<<8)|tm[1]:04X}")
    oam=m.read_memory("snesSpriteRam",0,32)
    print("OAM[0..7]:",oam.hex())
    # count on-screen sprites (Y<224)
    on=sum(1 for n in range(128) if m.read_memory("snesSpriteRam",n*4+1,1)[0]<224)
    print(f"on-screen sprites (Y<224): {on}")
    shot=m.take_screenshot(format="path"); print("screenshot:",shot)
