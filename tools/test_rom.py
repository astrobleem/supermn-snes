#!/usr/bin/env python3
"""Test the Superman ROM in Mesen-MCP."""

import os
import sys

os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet8"
os.environ["PATH"] = "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")

mesen_exe = "/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
rom_path = "/home/chad/supermn-snes/build/superman.sfc"

from mesen_mcp import McpSession

print(f"Testing: {rom_path}")
print(f"ROM size: {os.path.getsize(rom_path)} bytes")
print()

with McpSession(rom=rom_path, mesen=mesen_exe, port=7336, boot_wait=3.0) as m:
    print("✓ MCP session connected")
    
    m.pause()
    state = m.get_state()
    print(f"✓ State: frameCount={state.get('frameCount')}, isPaused={state.get('isPaused')}")
    
    # Read ROM header
    header = m.read_memory("snesPrgRom", 0x00FFC0, 32)
    print(f"✓ ROM header: {header.hex()}")
    
    # Read code at reset vector
    code = m.read_memory("snesPrgRom", 0x008000, 32)
    print(f"✓ Code at $8000: {code.hex()}")
    
    # Check PPU state
    ppu = m.get_ppu_state()
    print(f"✓ PPU: brightness={ppu.get('brightness')}, mode={ppu.get('mode')}")
    
    # Run some frames
    m.run_frames(60)
    state = m.get_state()
    print(f"✓ After 60 frames: frameCount={state.get('frameCount')}")
    
    # Take a screenshot
    shot = m.take_screenshot(format="path")
    print(f"✓ Screenshot: {shot.get('path', 'N/A')}")
    
    print()
    print("🎮 Superman ROM running in Mesen-MCP!")
