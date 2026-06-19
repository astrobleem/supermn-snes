#!/usr/bin/env python3
"""Build the sprite test ROM with proper SNES header."""
import struct
import sys

# Read the Poppy binary
poppy = bytearray(open('src/sprite_test.bin', 'rb').read())
print(f'Poppy binary: {len(poppy)} bytes')

# Code is first 32KB at $8000-$FFFF, data follows at $10000+
code = poppy[:32768]
data = poppy[32768:]
print(f'Code: {len(code)} bytes, Data: {len(data)} bytes')

# We need a ROM big enough for code + data
# Code at $8000-$FFFF (32KB) + data at $10000+
# Total = 0x10000 + len(data) = 65536 + 492572 = 558108
# Round up to 1MB
rom_size = 1024 * 1024
rom = bytearray(rom_size)

# Place code at $8000-$FFFF = file offset 0
rom[0:len(code)] = code

# Place data at $10000+ = file offset $8000
data_file_offset = 0x8000
rom[data_file_offset:data_file_offset + len(data)] = data

# SNES header at $7FC0
title = b'SUPERMAN SPRITE TEST '
assert len(title) == 21, f'Title must be 21 chars, got {len(title)}'

rom[0x7FC0:0x7FC0+21] = title
rom[0x7FD5] = 0x20   # LoROM
rom[0x7FD6] = 0x00   # ROM only
rom[0x7FD7] = 0x0B   # 1024KB
rom[0x7FD8] = 0x00   # No SRAM
rom[0x7FD9] = 0x01   # USA
rom[0x7FDA] = 0x33   # Licensee
rom[0x7FDB] = 0x00   # Version

rom[0x7FDC] = 0
rom[0x7FDD] = 0
rom[0x7FDE] = 0
rom[0x7FDF] = 0

total = sum(rom) & 0xFFFF
complement = (~total) & 0xFFFF
rom[0x7FDC] = complement & 0xFF
rom[0x7FDD] = (complement >> 8) & 0xFF
rom[0x7FDE] = total & 0xFF
rom[0x7FDF] = (total >> 8) & 0xFF

open('build/sprite_test.sfc', 'wb').write(rom)
print(f'ROM built: {len(rom)} bytes ({len(rom)//1024}KB)')
print(f'Reset: ${(rom[0x7FFD]<<8)|rom[0x7FFC]:04X}')
print(f'NMI: ${(rom[0x7FFB]<<8)|rom[0x7FFA]:04X}')
