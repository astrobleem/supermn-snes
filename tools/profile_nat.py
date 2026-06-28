#!/usr/bin/env python3
# Hot-function profile over ONE real GAME_TICK from the deterministic NAT (frozen at jh_spin).
# Streams EVERY interpreted 68K PC to $40:8000 ($0718=byte count), histograms by 64-byte region,
# and marks regions at/near a deployed escape. Usage: profile_nat.py [gate]  (gate=0 escapes OFF =
# full stream of all functions; gate=1 escapes ON = only UN-covered code streams -> next targets).
# RUN VIA A SUBPROCESS WRAPPER (Bash->python->subprocess->python->Nexen); a direct python->Nexen
# under the Bash tool dies with signal 16. Needs an absolute rom path. See escape-deploy-shift-safe.
import sys, os, collections, subprocess
if os.environ.get('_PROF_WRAPPED')!='1':                         # self-wrap to get 2 python levels
    os.environ['_PROF_WRAPPED']='1'
    r=subprocess.run([sys.executable]+sys.argv,capture_output=True,text=True,timeout=600,env=os.environ)
    print('\n'.join(l for l in (r.stdout+r.stderr).splitlines()
                     if l.startswith('  $') or 'streamed' in l or 'top ' in l or 'Trace' in l or 'Error' in l))
    sys.exit(r.returncode)
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
GATE=int(sys.argv[1]) if len(sys.argv)>1 else 1
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
DEPLOYED={0x412,0xCB9E,0x15B4,0xCE4,0x111A,0x20E8,0xD96,0xFB8,0x28D4,0x26A0,0x26FA,0x295A,0x284E,
          0x2742,0x267A,0x29B6,0x13BE,0xD9CC,0xDC44,0xD18A,0x2E06,0x2BC2,0xCCD8,0xCC10,0x25110,0x8C2}
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7517,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v): m.write_u16(a,v,'Sa1Memory')
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    runf(150); m.load_state(NAT)
    a7=r16(0x3C)|(r16(0x3E)<<16)
    rb=m.read_memory('snesMemory',0x400000|(a7&0xFFFF),4); R=(rb[0]<<24)|(rb[1]<<16)|(rb[2]<<8)|rb[3]
    w16(0x40,0x3A92); w16(0x42,0); w16(0x0700,0); w16(0x072E,1); w16(0x071A,GATE)
    w16(0x0712,0); w16(0x0710,R&0xFFFF); w16(0x0716,(R>>16)&0xFFFF); w16(0x0760,0); w16(0x0702,0)
    w16(0x0718,0); w16(0x0704,1)
    for _ in range(80):
        runf(10)
        if r16(0x0712): break
    nbytes=r16(0x0718); stream=m.read_memory('snesMemory',0x408000,min(nbytes,0xFFF8))
    pcs=[((stream[i+2]|(stream[i+3]<<8))<<16)|(stream[i]|(stream[i+1]<<8)) for i in range(0,len(stream)-3,4)]
    spin={0x818,0x6C4,0x6C8,0x6CE,0x6FE,0x704,0x708,0x6F0,0x6F2,0x6FA}
    valid=[p for p in pcs if 0x800<=p<0x40000 and p not in spin]
    print("streamed %d PCs (%d bytes); valid game-code %d ; gate=%d trapped=%s"%(len(pcs),nbytes,len(valid),GATE,bool(r16(0x0712))))
    buckets=collections.Counter(p&~0x3F for p in valid)
    def near(region): return any(region in DEPLOYED or d&~0x3F==region for d in DEPLOYED) or any(0<=region-d<0x400 for d in DEPLOYED)
    print("top 30 hot 64-byte regions (* deployed / 'near'):")
    for region,c in buckets.most_common(30):
        mark='*' if (region in DEPLOYED or any(d&~0x3F==region for d in DEPLOYED)) else (' near' if near(region) else '')
        print("  $%06X  %5d  (%4.1f%%) %s"%(region,c,100*c/max(len(valid),1),mark))
