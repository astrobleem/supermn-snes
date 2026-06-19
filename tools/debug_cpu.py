#!/usr/bin/env python3
"""Debug: check if CPU is executing our code."""

import os, sys, time

os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet8"
os.environ["PATH"] = "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")

mesen_exe = "/home/chad/Mesen2/bin/linux-x64/Release/Mesen"
rom_path = "/home/chad/supermn-snes/build/superman.sfc"

from mesen_mcp import McpSession

with McpSession(rom=rom_path, mesen=mesen_exe, port=7340, boot_wait=3.0) as m:
    print("Connected")
    m.pause()
    
    # Check CPU state
    state = m.get_state()
    print(f"isPaused: {state.get('isPaused')}")
    print(f"frameCount: {state.get('frameCount')}")
    
    # Read ROM at $8000 to verify it's there
    rom_check = m.read_memory("snesPrgRom", 0x008000, 16)
    print(f"ROM at $8000: {rom_check.hex()}")
    
    # Read the actual ROM file
    with open(rom_path, "rb") as f:
        file_data = f.read()
    print(f"File at $8000: {file_data[0x8000:0x8010].hex()}")
    
    # Check if they match
    if bytes(rom_check) == file_data[0x8000:0x8010]:
        print("ROM data MATCHES")
    else:
        print("ROM data MISMATCH!")
    
    # Read vectors
    vectors = m.read_memory("snesPrgRom", 0x007FE0, 32)
    print(f"\nVectors at $7FE0:")
    for i in range(0, 32, 4):
        addr = (vectors[i+1] << 8) | vectors[i]
        print(f"  $7FE{i:02X}: ${addr:04X}")
    
    # Read reset vector specifically
    rv = m.read_memory("snesPrgRom", 0x007FFC, 4)
    rv_addr = (rv[1] << 8) | rv[0]
    print(f"\nReset vector: ${rv_addr:04X}")
    
    # Check what's at the reset vector target
    if rv_addr >= 0x8000:
        target_data = m.read_memory("snesPrgRom", rv_addr - 0x8000 + 0x8000, 8)
    else:
        target_data = m.read_memory("snesPrgRom", rv_addr, 8)
    print(f"Data at reset target: {target_data.hex()}")
