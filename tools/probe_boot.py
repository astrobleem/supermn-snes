#!/usr/bin/env python3
"""Probe boot progress: distinguish a hard hang (PC + steps frozen) from a slow
loop (steps climbing, F01C56 eventually moving). Runs a long budget and samples."""
import sys, os
sys.path.insert(0, "/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT", "/home/chad/.dotnet8")
os.environ["PATH"] = "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")
from mesen_mcp import McpSession
ROM = "/home/chad/supermn-snes/build/interp.sfc"
MESEN = "/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u32(b, o): return b[o] | (b[o+1] << 8) | (b[o+2] << 16) | (b[o+3] << 24)
def be16(b, o): return (b[o] << 8) | b[o+1]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 30
with McpSession(rom=ROM, mesen=MESEN, port=7349, boot_wait=3.0) as m:
    total = 0
    for i in range(N):
        m.run_frames(200); total += 200
        pc = u32(m.read_memory("snesWorkRam", 0x40, 4), 0)
        steps = u32(m.read_memory("snesWorkRam", 0x4a, 4), 0)
        tm = be16(m.read_memory("snesWorkRam", 0x10002, 2), 0)
        fc = be16(m.read_memory("snesWorkRam", 0x11C56, 2), 0)
        print(f"  @{total}f PC=${pc:06X} steps={steps} tmask=${tm:04X} F01C56={fc}", flush=True)
        if tm == 0x0003 and fc > 5:
            print("REACHED LIVE LOOP"); break
