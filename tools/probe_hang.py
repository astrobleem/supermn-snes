#!/usr/bin/env python3
"""Boot to the ispin hang and dump the failing-opcode diagnostics: $40/$42 (PC),
$44 (opcode), $5E (idone marker), and the PC ring buffer ($0800, 64*4)."""
import sys, os
sys.path.insert(0, "/home/chad/Mesen2/python")
os.environ.setdefault("DOTNET_ROOT", "/home/chad/.dotnet8")
os.environ["PATH"] = "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")
from mesen_mcp import McpSession
ROM = "/home/chad/supermn-snes/build/interp.sfc"
MESEN = "/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
def u16(b, o): return b[o] | (b[o+1] << 8)
def u32(b, o): return b[o] | (b[o+1] << 8) | (b[o+2] << 16) | (b[o+3] << 24)
with McpSession(rom=ROM, mesen=MESEN, port=7350, boot_wait=3.0) as m:
    laststeps = -1
    for i in range(16):
        m.run_frames(200)
        steps = u32(m.read_memory("snesWorkRam", 0x4a, 4), 0)
        pc = u32(m.read_memory("snesWorkRam", 0x40, 4), 0)
        if steps == laststeps:
            print(f"HUNG at ~{(i+1)*200}f, PC=${pc:06X} steps={steps}")
            break
        laststeps = steps
    dp = m.read_memory("snesWorkRam", 0x40, 0x08)   # $40..$47
    op = u16(dp, 0x44-0x40)
    pc = u32(dp, 0)
    s5e = u16(m.read_memory("snesWorkRam", 0x5e, 2), 0)
    print(f"PC=${pc & 0xFFFFFF:06X} opcode($44)=${op:04X} $5E=${s5e:04X}")
    rb = m.read_memory("snesWorkRam", 0x0800, 0x100)
    pcs = [u32(rb, k) & 0xFFFFFF for k in range(0, 0x100, 4)]
    # ring index at $48 marks the most-recent slot
    idx = u16(m.read_memory("snesWorkRam", 0x48, 2), 0) & 0xFF
    print(f"ring idx $48=${idx:02X}")
    # print the ring in chronological-ish order (last ~24 distinct)
    order = [pcs[((idx//4 + k) % 64)] for k in range(64)]
    print("recent PCs (oldest->newest):")
    print("  " + " ".join(f"{p:04X}" for p in order[-24:]))
