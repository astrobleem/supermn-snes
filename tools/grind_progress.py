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
    def bgmap(): return m.read_memory("snesMemory",0x414800,0x1000)  # BG tilemap shadow
    def wcrc(): return zlib.crc32(m.read_memory("snesMemory",0x400000,0x10000))
    total=0
    for k in range(12):
        for _ in range(8): m.run_frames(150)
        total+=1200
        bg=bgmap(); st=u32(dp(0x4A,4),0); tm=u16(m.read_memory("snesMemory",0x400002,2),0)
        try: uc=m.take_screenshot(format="path").get("unique_colors")
        except: uc="?"
        print(f"@{total}f step={st} gameFrames~{st//28672} tmask=${tm:04X} BGtilemap_nz={nz(bg)}/4096 wcrc={wcrc():08X} screenColors={uc}", flush=True)
