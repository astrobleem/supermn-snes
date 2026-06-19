#!/usr/bin/env python3
"""Debug: try different memory types for PPU register access."""

import os, sys, time

os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet8"
os.environ["PATH"] = "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")

mesen_exe = "/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
rom_path = "/home/chad/supermn-snes/build/superman.sfc"

from mesen_mcp import McpSession

with McpSession(rom=rom_path, mesen=mesen_exe, port=7341, boot_wait=3.0) as m:
    print("Connected")
    m.pause()
    
    # Try different memory types
    mem_types = ["snesMemory", "snesPrgRom", "snesWorkRam", "snesVideoRam", "snesCgRam", "snesSpriteRam"]
    
    for mt in mem_types:
        try:
            data = m.read_memory(mt, 0, 16)
            print(f"{mt}: {data.hex()}")
        except Exception as e:
            print(f"{mt}: ERROR - {e}")
    
    # Check PPU state
    ppu = m.get_ppu_state()
    print(f"\nPPU state: {ppu}")
    
    # Check CPU state
    state = m.get_state()
    print(f"CPU state: frameCount={state.get('frameCount')}, isPaused={state.get('isPaused')}")
    
    # Try to get a screenshot and check if it's all black
    shot = m.take_screenshot(format="base64")
    if shot.get('data'):
        import base64
        data = base64.b64decode(shot['data'])
        # PNG header check
        print(f"\nScreenshot: {len(data)} bytes")
        print(f"PNG header: {data[:8].hex()}")
        # Check first pixel
        # PNG is compressed, so we can't easily read pixels
        # But we can check if the file is valid
        if data[:8] == bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]):
            print("Valid PNG file")
