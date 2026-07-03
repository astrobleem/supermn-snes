#!/usr/bin/env python3
"""Re-dump b0 as a NATIVE Nexen save-state (/tmp/b0_native.mss) for DETERMINISTIC resume.

The manual transplant (b0_iram/b0_bwram/b0_cpu via set_cpu_state) can't restore the SA-1's full
internal state, so a fresh transplant per run resumes non-deterministically (breaks validation of
longer escapes). This transplants b0, arms the lockstep ($0700), runs until the interp FREEZES at the
jh_spin clean inter-op boundary ($0702=1, the $3A92/$0708 GAME_TICK call site), then save_state's a
full native snapshot WHILE FROZEN. jh_spin is a pure `lda $0704; beq jh_spin` loop -- it never touches
the 68K PC ($40/$42), so a validator can load_state, inject its frame + synthetic-jsr PC, and release
($0704=1 -> `jmp iloop`) for a CLEAN fetch of the injected PC, regardless of write timing.

IMPORTANT: do NOT release-and-resettle here. GAME_TICK ($3A92@$0708) fires once per GAME frame
(~28672 68K-instr ~= 2048 SNES frames at the interp's ~14 instr/frame), so a short re-freeze wait
saves the interp FREE-RUNNING mid-stream ($0702=0) -- then injection races the running handler and the
synthetic PC is clobbered (interp resumes b0's own stream instead). Save at the FIRST freeze."""
import sys, os, json
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'
cpu=json.load(open('/tmp/b0_cpu.json')); iram=open('/tmp/b0_iram.bin','rb').read(); bwram=open('/tmp/b0_bwram.bin','rb').read()
NAT=sys.argv[1] if len(sys.argv)>1 else '/tmp/b0_native.mss'
with McpSession(rom=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','build','interp.sfc'),mesen=NEXEN,port=7487,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    def setcpu(st): m.tool("set_cpu_state",{k:st[k] for k in ('cpuType','pc','k','a','x','y','sp','d','dbr','ps','emulationMode') if k in st})
    runf(600)
    for o in range(0,len(iram),0x400): wh(0x0000+o,iram[o:o+0x400].hex())
    for o in range(0,len(bwram),0x4000): wh(0x400000+o,bwram[o:o+0x4000].hex(),'snesMemory')
    # b0 is captured AT jh_spin (its IRAM carries $0702=1). Keep it frozen: arm, DON'T clear $0702,
    # force $0704=0 so it can't release. If b0 ever resumes free, wait up to one game frame (~2048
    # SNES frames at ~14 instr/frame) for the next $3A92/$0708 freeze.
    # escapes OFF during capture ($071A=0): the lockstep freeze ($3A92) lives in jsrabs_hook AFTER
    # the escape dispatch (jsrabs_hook2). If $3A92 is itself escaped, escapes-on would dispatch it and
    # NEVER reach the lockstep -> no freeze -> capture fails. Off means the lockstep always wins here.
    setcpu(cpu['sa1']); setcpu(cpu['snes']); w16(0x0700,1); w16(0x0704,0); w16(0x071A,0)
    froze=False
    for _ in range(60):
        if r16(0x0702): froze=True; break
        runf(60)
    assert froze, "interp never froze at jh_spin ($0702 stayed 0) -- lockstep not arming"
    for _ in range(5): w16(0x0704,0); runf(20)   # settle Nexen internal state (spins in jh_spin)
    assert r16(0x0702), "lost the freeze during settle"
    m.save_state(NAT)   # saved WHILE FROZEN at jh_spin (clean inter-op boundary; $0704 release -> jmp iloop)
    print("wrote %s (FROZEN at jh_spin: $0700=%d $0702=%d $0704=%d, tmask=%04X)"%(
        NAT, r16(0x0700), r16(0x0702), r16(0x0704), r16(0x400002,'snesMemory')),flush=True)
