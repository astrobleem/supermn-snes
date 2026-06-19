import struct

# Read the Poppy binary (32KB)
poppy_data = bytearray(open('src/main.bin', 'rb').read())

# Create a 64KB ROM
rom = bytearray(65536)

# Copy poppy code to bank 0
rom[0:len(poppy_data)] = poppy_data

# Write the SNES header at $7FC0
title = b"SUPERMAN ARCADE      "
assert len(title) == 21

rom[0x7FC0:0x7FC0+21] = title
rom[0x7FD5] = 0x30   # Map mode: LoROM + FastROM
rom[0x7FD6] = 0x00   # Cart type: ROM only
rom[0x7FD7] = 0x08   # ROM size: 256KB
rom[0x7FD8] = 0x00   # SRAM size: none
rom[0x7FD9] = 0x01   # Country: USA
rom[0x7FDA] = 0x33   # Licensee code
rom[0x7FDB] = 0x00   # Version

# Clear checksum area
rom[0x7FDC] = 0
rom[0x7FDD] = 0
rom[0x7FDE] = 0
rom[0x7FDF] = 0

# Calculate checksum
total = sum(rom) & 0xFFFF
complement = (~total) & 0xFFFF

# Write checksum
rom[0x7FDC] = complement & 0xFF
rom[0x7FDD] = (complement >> 8) & 0xFF
rom[0x7FDE] = total & 0xFF
rom[0x7FDF] = (total >> 8) & 0xFF

# Verify by reading back
verify = sum(rom) & 0xFFFF

# The verify should equal total because:
# verify = total_zeros + complement_checksum_bytes + checksum_bytes
# complement_bytes = ~total (as 2 LE bytes)
# checksum_bytes = total (as 2 LE bytes)
# So verify = total + (~total) + total = $FFFF + total = total (mod 65536)
# Wait: total + (~total) = $FFFF, then $FFFF + total = $10000 + total - 1... no
# $FFFF + total = $FFFF + total. If total = $6565, then $FFFF + $6565 = $16564.
# $16564 mod 65536 = $6564. Not $6565.

# Actually: verify = total + complement_value + checksum_value
# where complement_value = complement (as 16-bit) and checksum_value = total (as 16-bit)
# = total + (~total) + total
# = $FFFF + total
# = $FFFF + $6565 = $16564
# mod 65536 = $6564

# So verify should be $6564, not $6565 or $6763

print(f'total (zeroed): ${total:04X}')
print(f'complement: ${complement:04X}')
print(f'verify (filled): ${verify:04X}')
print(f'expected verify: ${(total + complement + total) & 0xFFFF:04X}')

# Write ROM
open('build/superman.sfc', 'wb').write(rom)
open('distribution/superman.sfc', 'wb').write(rom)

# Read back and verify
readback = open('build/superman.sfc', 'rb').read()
readback_sum = sum(readback) & 0xFFFF
print(f'readback sum: ${readback_sum:04X}')

print(f'\nROM built: {len(rom)} bytes')
print(f'Title: {title.decode("ascii", errors="replace")}')
print(f'Map mode: ${rom[0x7FD5]:02X}')
print(f'Reset vector: ${(rom[0x7FFD]<<8)|rom[0x7FFC]:04X}')
print(f'NMI vector: ${(rom[0x7FFB]<<8)|rom[0x7FFA]:04X}')
