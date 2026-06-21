import sys, os
sys.path.insert(0, "/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT", "/home/chad/.dotnet8")
os.environ["PATH"] = "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")
from mesen_mcp import McpSession
ROM = "/home/chad/supermn-snes/build/interp.sfc"; MESEN = "/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def be16(b,o): return (b[o]<<8)|b[o+1]
with McpSession(rom=ROM, mesen=MESEN, port=7380, boot_wait=4.0) as m:
    for i in range(14): m.run_frames(200)
    tm = be16(m.read_memory("snesWorkRam",0x10002,2),0)
    print(f"tmask=${tm:04X} (alive={tm==3})")
    def joy(): 
        b=m.read_memory("snesMemory",0x4218,2); return b[0]|(b[1]<<8)
    def inbyte():  # game's copy of $900001 at $F01C50 = $7F:1C50
        return m.read_memory("snesWorkRam",0x11C50,1)[0]
    print(f"idle: JOY1=${joy():04X} $F01C50=${inbyte():02X}")
    # try several Mesen button masks, hold for a game-frame, read JOY1 + input byte
    for name,mask in [("bit11",0x800),("bit8",0x100),("bit0",0x1),("bit1",0x2),("Up?",1<<8),("A?",1<<0)]:
        m.set_input(mask, 250)
        m.run_frames(250)
        print(f"  set {name}=${mask:03X}: JOY1=${joy():04X}  $F01C50=${inbyte():02X}")
        m.set_input(0, 1); m.run_frames(2)
