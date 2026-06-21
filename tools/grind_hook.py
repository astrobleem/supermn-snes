import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u16(b,o): return b[o]|(b[o+1]<<8)
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    def stp(): return u16(dp(0x4E),0)
    # hook the 4-byte return slot on BOTH cpus, fire on any write
    h_snes=m.add_write_hook(0x400334, 0x400337, cpu_type="Snes")
    h_sa1 =m.add_write_hook(0x400334, 0x400337, cpu_type="Sa1")
    print("hooks:", h_snes, h_sa1)
    allnotes=[]
    total=0
    while total<1300:
        m.run_frames(3); total+=3
        notes=m.drain_notifications(timeout=0.05)
        for n in notes:
            p=n.get("params",n)
            allnotes.append(p)
        if stp()!=0:
            print(f"halt @f{total} stop=${stp():04X}")
            break
    notes=m.drain_notifications(timeout=0.2)
    for n in notes: allnotes.append(n.get("params",n))
    print(f"total hook fires captured: {len(allnotes)}")
    # show the last ~15 (closest to the corruption)
    for p in allnotes[-15:]:
        print("  ", p)
