# Drive the interp forward from gf260 with input (Right + periodic B) to a NEW gameplay moment,
# then dump a fresh consistent transplant triple (/tmp/gf2_*). Input via $410002 (joy5a22 ORs it
# into the $410000 mailbox every frame -> persistent). New freeze validates cold functions.
import sys, os, json
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'
cpu=json.load(open('/tmp/b0_cpu.json')); iram=open('/tmp/b0_iram.bin','rb').read(); bwram=open('/tmp/b0_bwram.bin','rb').read()
NTICKS=int(os.environ.get('NTICKS','120')); OUT='/tmp/gf2_'
RIGHT=0x0100; BTN_B=0x8000
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7469,boot_wait=6.0,socket_timeout=400.0) as m:
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
    def freezeB0():
        transplant(); w16(0x0700,1)
        for _ in range(10):
            if r16(0x0702): break
            runf(60)
    print("[Nexen] boot+transplant gf260...",flush=True); runf(600); freezeB0()
    base_bw=bytes(m.read_memory('snesMemory',0x400000,0x10000))
    print("[Nexen] at gf260 $3A92; tmask=%04X"%r16(0x400002,'snesMemory'),flush=True)
    for ti in range(NTICKS):
        btn=RIGHT | (BTN_B if (ti%6==0) else 0)   # walk right; tap B every 6 ticks
        w16(0x410002, btn, 'snesMemory')          # persistent virtual-controller poke
        w16(0x0700,1); w16(0x0702,0); w16(0x0704,1)
        ok=False
        for _ in range(80):
            runf(20)
            if r16(0x0702): ok=True; break
        if not ok:
            print("  tick %d: no $3A92 within window (stuck?) tmask=%04X"%(ti,r16(0x400002,'snesMemory')),flush=True)
        if ti%10==9:
            cur=bytes(m.read_memory('snesMemory',0x400000,0x10000))
            nd=sum(1 for i in range(0x10000) if base_bw[i]!=cur[i])
            print("  tick %d: tmask=%04X work-RAM diff-vs-gf260=%d"%(ti+1,r16(0x400002,'snesMemory'),nd),flush=True)
    # dump the new freeze (frozen at $3A92)
    sa1=m.get_cpu_state('Sa1'); snes=m.get_cpu_state('Snes')
    json.dump({'sa1':sa1,'snes':snes}, open(OUT+'cpu.json','w'))
    open(OUT+'iram.bin','wb').write(bytes(m.read_memory('Sa1Memory',0x0000,0x800)))
    bw=b''.join(bytes(m.read_memory('snesMemory',0x400000+o,0x8000)) for o in range(0,0x18000,0x8000))
    open(OUT+'bwram.bin','wb').write(bw)
    fin=bytes(m.read_memory('snesMemory',0x400000,0x10000))
    nd=sum(1 for i in range(0x10000) if base_bw[i]!=fin[i])
    print("[Nexen] DUMPED gf2_* after %d ticks; final work-RAM diff-vs-gf260=%d ; tmask=%04X"%(NTICKS,nd,r16(0x400002,'snesMemory')),flush=True)
