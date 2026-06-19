#!/usr/bin/env python3
"""Debug PPU register reads."""

import os, sys, time

os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet8"
os.environ["PATH"] = "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")

mesen_exe = "/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
rom_path = "/home/chad/supermn-snes/build/superman.sfc"

from mesen_mcp import McpSession

with McpSession(rom=rom_path, mesen=mesen_exe, port=7339, boot_wait=5.0) as m:
    print("Connected")
    m.resume()
    time.sleep(2)
    m.pause()
    
    # Read all PPU registers
    ppu_regs = m.read_memory("snesMemory", 0x2100, 0x40)
    print("PPU registers $2100-$213F:")
    for i in range(0, 0x40, 16):
        hex_str = " ".join("%02X" % b for b in ppu_regs[i:i+16])
        print(f"  $21{i:02X}: {hex_str}")
    
    # Read CPU registers
    print(f"\nFrame count: {m.get_state()['frameCount']}")
    
    # Try writing INIDISP directly via MCP
    print("\nWriting #$0F to INIDISP via write_memory...")
    m.write_memory("snesMemory", 0x2100, "0F")
    
    time.sleep(0.1)
    m.pause()
    
    # Read back
    inidisp = m.read_memory("snesMemory", 0x2100, 1)
    print(f"INIDISP after write: {inidisp.hex()}")
    
    # Take screenshot
    shot = m.take_screenshot(format="path")
    print(f"Screenshot: {shot.get('path', 'N/A')}")
