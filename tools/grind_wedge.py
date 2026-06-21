import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u16(b,o): return b[o]|(b[o+1]<<8)
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    def runf(n):
        while n>0: c=min(150,n); m.run_frames(c); n-=c
    runf(1800)
    poke(0x2000); runf(240); poke(0); runf(120)
    print("68K step:", u32(dp(0x4A,4),0), "68K PC=$%06X"%(u16(dp(0x40),0)|(u16(dp(0x42),0)<<16)))
    # sample the SA-1 65816 PC many times to find the spin loop
    for cpu in ("Sa1","Snes"):
        pcs={}
        for _ in range(30):
            s=m.get_cpu_state(cpu_type=cpu)
            p=(s.get("k",0)<<16)|s.get("pc",0)
            pcs[p]=pcs.get(p,0)+1
            m.run_frames(1)
        print(f"{cpu} stopState={s.get('stopState')} PC histogram:", {f"${k:06X}":v for k,v in sorted(pcs.items(),key=lambda x:-x[1])[:8]})
