#!/usr/bin/env python3
"""Test the Superman port ROM — run more frames and check PPU state."""

import os, sys, time

os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet8"
os.environ["PATH"] = "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")

mesen_exe = "/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
rom_path = "/home/chad/supermn-snes/build/superman.sfc"

from mesen_mcp import McpSession

with McpSession(rom=rom_path, mesen=mesen_exe, port=7338, boot_wait=5.0) as m:
    print("Connected")
    
    # Run 300 frames (5 seconds at 60fps) without pausing
    m.resume()
    time.sleep(6)
    m.pause()
    
    state = m.get_state()
    print(f"Frame count: {state.get('frameCount')}")
    
    # Check PPU registers directly
    brightness = m.read_memory("snesMemory", 0x2100, 1)
    bgmode = m.read_memory("snesMemory", 2105, 1)
    print(f"INIDISP (brightness): {brightness.hex()}")
    print(f"BGMODE: {bgmode.hex()}")
    
    # Check if NMI has fired
    nmi = m.read_memory("snesMemory", 0x4210, 1)
    print(f"RDNMI: {nmi.hex()}")
    
    # Take screenshot
    shot = m.take_screenshot(format="path")
    print(f"Screenshot: {shot.get('path', 'N/A')}")
    
    # Check the actual pixel data
    shot64 = m.take_screenshot(format="base64")
    if shot64.get('data'):
        import base64
        data = base64.b64decode(shot64['data'])
        # Check first few bytes
        print(f"Screenshot data length: {len(data)}")
        print(f"First 20 bytes: {data[:20].hex()}")
