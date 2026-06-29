# Scan consecutive GAME_TICK intervals in the playback; pick the one whose A->B work-RAM delta
# touches the sprite-builder output streams ($1cf6/$20f2/$24ee = a5+disp) -> that interval ran
# $0CE4 (or its sibling $13be). Save that triple for lockstep validation of entry_ce4t.
import sys, shutil, struct
from pathlib import Path
sys.path.insert(0,"/home/chad/mame-mcp"); from mame_mcp.session import MameSession
START=int(sys.argv[1]); OUT=Path(sys.argv[2]); OUT.mkdir(parents=True,exist_ok=True)
HERE=Path("/home/chad/supermn-snes/tools/mame-trace"); ENV=HERE/"record_env"
for d in ("cfg","nvram"):
    if (ENV/d).exists():
        if (HERE/d).exists(): shutil.rmtree(HERE/d)
        shutil.copytree(ENV/d, HERE/d)
def regsA(r):
    v=[r["D%d"%i] for i in range(8)]+[r["A%d"%i] for i in range(7)]+[(r["SP"]+60)&0xFFFFFFFF, r.get("USP",0), r.get("SR",0)]
    return b"".join(struct.pack(">I",x&0xFFFFFFFF) for x in v)
def touches(a,b):  # delta in the X/Y/code stream region $1cf6..$2600 ?
    return any(a[i]!=b[i] for i in range(0x1cf6,0x2600))
s=MameSession(mame="mame", system="superman", rompath=str(HERE/"roms"), workdir=str(HERE), state_directory=str(HERE/"sta"),
              extra_args=["-playback","vplay.inp","-input_directory","/home/chad/supermn-snes/inp"])
try:
    s.launch(boot_wait=25); frame=0
    while frame < START-10:
        step=min(800,START-10-frame)
        r=s.cmd("capture_game_tick", addr=0xF00000, len=4, nth=step, maxFrames=step+400, timeout=180)
        if not r.get("registers"): break
        frame=r["frame"]
    prev=None; prevr=None
    for k in range(40):
        C=s.cmd("capture_game_tick", addr=0xF00000, len=0x4000, nth=1, maxFrames=400, timeout=120)
        if not C.get("hex"): print("no tick @k=%d"%k); break
        w=bytes.fromhex(C["hex"]); r=C["registers"]
        if prev is not None and touches(prev,w):
            (OUT/"regsA.bin").write_bytes(regsA(prevr)); (OUT/"wramA.bin").write_bytes(prev); (OUT/"wramB.bin").write_bytes(w)
            print("STREAM-touching interval k=%d f=%d->%d pc=%04X SP=%06X -> saved"%(k,C["frame"]-1,C["frame"],prevr["pc"] if "pc" in prevr else 0,prevr["SP"]&0xFFFFFF),flush=True)
            break
        prev=w; prevr=r
    else:
        print("no stream-touching interval in 40 ticks",flush=True)
finally: s.stop()
