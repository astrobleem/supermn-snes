import sys,os,json
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'
w=sys.argv[1] if len(sys.argv)>1 else 'gf2'
cpu=json.load(open('/tmp/%s_cpu.json'%w)); iram=open('/tmp/%s_iram.bin'%w,'rb').read(); bwram=open('/tmp/%s_bwram.bin'%w,'rb').read()
TGT=[0x2242,0x284E,0x2742,0x267A,0x29B6,0x25A40]
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7473,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    def setcpu(st): m.tool("set_cpu_state",{k:st[k] for k in ('cpuType','pc','k','a','x','y','sp','d','dbr','ps','emulationMode') if k in st})
    def transplant():
        for o in range(0,len(iram),0x400): wh(0x0000+o,iram[o:o+0x400].hex())
        for o in range(0,len(bwram),0x4000): wh(0x400000+o,bwram[o:o+0x4000].hex(),'snesMemory')
        setcpu(cpu['sa1']); setcpu(cpu['snes'])
    def freeze():
        transplant(); w16(0x0700,1)
        for _ in range(10):
            if r16(0x0702): break
            runf(60)
    runf(600); freeze()
    base=bytes(m.read_memory('snesMemory',0x400000,0x10000))
    # sanity: run ONE tick (no debug-freeze), confirm $3A92 re-fires + work RAM changes
    w16(0x0718,0xFFF8); w16(0x410002,0,'snesMemory'); w16(0x0710,0); w16(0x0716,0); w16(0x0700,1); w16(0x0702,0); w16(0x0704,1)
    ok=False
    for _ in range(80):
        runf(20)
        if r16(0x0702): ok=True; break
    cur=bytes(m.read_memory('snesMemory',0x400000,0x10000))
    nd=sum(1 for i in range(0x10000) if base[i]!=cur[i])
    print("[%s] tick ran=%s ($3A92 re-fired) work-RAM changed this tick=%d"%(w,ok,nd),flush=True)
    # probe cold targets
    for t in TGT:
        freeze(); w16(0x071A,0); w16(0x0712,0); w16(0x0710,t); w16(0x0716,0); w16(0x0700,1); w16(0x0702,0); w16(0x0704,1)
        fired=0
        for _ in range(60):
            runf(20)
            if r16(0x0712): fired=1; break
            if r16(0x0702): break
        print("  cold $%06X reached-by-%s-tick=%s"%(t,w,'YES' if fired else 'no'),flush=True)
