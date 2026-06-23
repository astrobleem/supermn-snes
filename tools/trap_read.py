import sys, os
sys.path.insert(0,"/home/chad/supermn-snes/tools"); sys.path.insert(0,"/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT","/home/chad/.dotnet8")
os.environ["PATH"]="/home/chad/.dotnet8:/home/chad/.dotnet10:"+os.environ.get("PATH","")
from mesen_mcp import McpSession
ROM="/home/chad/supermn-snes/build/interp.sfc"; MESEN="/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
LOG=open("/home/chad/supermn-snes/trap_read.out","w")
def out(*a):
    s=" ".join(str(x) for x in a); LOG.write(s+"\n"); LOG.flush(); print(s,flush=True)
def u16(b,o): return b[o]|(b[o+1]<<8)
def u32(b,o): return b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)
START=0x1000
PCS=[]  # now: ring of spawn bit-numbers (D1 at $04A4)
with McpSession(rom=ROM, mesen=MESEN, port=7346, boot_wait=3.0) as m:
    def dp(o,n=2): return m.read_memory("Sa1Memory", o, n)
    def gf(): return u32(dp(0x4A,4),0)//28672
    def tmask(): return u16(m.read_memory('snesMemory',0x400002,2),0)
    def poke(v): m.write_hex(0x410002, f"{v&0xFF:02x}{(v>>8)&0xFF:02x}", "snesMemory")
    def cap():
        b=m.read_memory("snesMemory",0x417E10,8)
        d7=u16(b,0); a7=u16(b,2)
        sb=b[4:8]  # stack bytes at [A7+24..27], BE
        flag=u16(m.read_memory("snesMemory",0x417E1E,2),0)
        idword=(sb[2]<<8)|sb[3]  # word at A7+26
        return d7,a7,sb,idword,flag
    m.load_state_slot(4)
    m.write_hex(0x417E10, "00"*16, "snesMemory")
    out("loaded slot4 gf~",gf(),"cleared")
    poke(START)
    for it in range(90):
        m.run_frames(150)
        g=gf(); tm=tmask()
        d7,a7,sb,idword,flag=cap()
        if flag or ((tm>>8)==0x3B and it>44):
            out(f"it{it} gF~{g} flag={flag} | D7(read id)=${d7:04X} A7lo=${a7:04X} stack[A7+24..27]={[hex(x) for x in sb]} -> id-word@A7+26=${idword:04X} (caller pushed #$10=16)")
            if flag: break
    d7,a7,sb,idword,flag=cap()
    out(f"FINAL flag={flag} D7(read)=${d7:04X} A7lo=${a7:04X} bytes={[hex(x) for x in sb]} idword@+26=${idword:04X}")
out("DONE")
