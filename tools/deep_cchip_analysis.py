#!/usr/bin/env python3
"""
Deep analysis of C-Chip protocol from Superman disassembly.
Reconstructs the command sequences and state machine.
"""

pasm_path = "/home/chad/supermn-snes/data/final_disasm.pasm"

with open(pasm_path) as f:
    content = f.read()
    lines = content.split('\n')

# Print full context around each C-Chip access
cchip_addrs = ['0900001', '0900003', '0900005', '0900007', '090001', '090003', '090005', '090007']

print("=" * 70)
print("C-CHIP PROTOCOL ANALYSIS")
print("=" * 70)

# Find lines with C-Chip references and print surrounding context
cchip_lines = []
for i, line in enumerate(lines):
    for addr in cchip_addrs:
        if addr in line and ('move' in line or 'btst' in line or 'cmp' in line or 'bne' in line or 'beq' in line or 'bra' in line or 'jsr' in line or 'lea' in line):
            cchip_lines.append((i, line))
            break

# Deduplicate nearby lines
seen_ranges = set()
for i, line in cchip_lines:
    # Check if we already have a line within 10 lines of this one
    found = False
    for r in seen_ranges:
        if abs(i - r) < 15:
            found = True
            break
    if not found:
        seen_ranges.add(i)
        # Print context
        print(f"\n--- Context around line {i} ---")
        start = max(0, i - 8)
        end = min(len(lines), i + 8)
        for j in range(start, end):
            marker = ">>>" if j == i else "   "
            print(f"  {marker} {lines[j]}")
        print()

# Now analyze the specific C-Chip command sequence at $2BFE
print("\n" + "=" * 70)
print("C-CHIP COMMAND SEQUENCE ANALYSIS")
print("=" * 70)

# Find the block starting at $2BFE
in_block = False
block_lines = []
for i, line in enumerate(lines):
    if '$2BF8' in line or '$2BFE' in line:
        in_block = True
    if in_block:
        block_lines.append(line)
        if len(block_lines) > 30:
            break

print("\nC-Chip command sequence at ~$2BF8:")
for line in block_lines[:40]:
    if line.strip():
        print(f"  {line}")

# Also check the C-Chip response check at $2C2A
print("\n\nC-Chip response check at ~$2C2A:")
in_block = False
block_lines = []
for i, line in enumerate(lines):
    if '$2C24' in line:
        in_block = True
    if in_block:
        block_lines.append(line)
        if len(block_lines) > 20:
            break

for line in block_lines[:25]:
    if line.strip():
        print(f"  {line}")

# And the status check at $3D78
print("\n\nC-Chip status check at ~$3D78:")
in_block = False
block_lines = []
for i, line in enumerate(lines):
    if '$3D6A' in line or '$3D78' in line:
        in_block = True
    if in_block:
        block_lines.append(line)
        if len(block_lines) > 20:
            break

for line in block_lines[:25]:
    if line.strip():
        print(f"  {line}")

# And the interrupt check at $3E1A
print("\n\nC-Chip interrupt check at ~$3E1A:")
in_block = False
block_lines = []
for i, line in enumerate(lines):
    if '$3E1A' in line:
        in_block = True
    if in_block:
        block_lines.append(line)
        if len(block_lines) > 15:
            break

for line in block_lines[:20]:
    if line.strip():
        print(f"  {line}")

# Summary of C-Chip memory map based on observed accesses
print("\n" + "=" * 70)
print("C-CHIP MEMORY MAP (reconstructed from disassembly)")
print("=" * 70)
print("""
From observed 68K accesses:

  $090001 : Command/data byte (write: #$4a, read: status)
             - Written with #$4a at start of command sequence
             - Read at $3AD8 to check response
             
  $090003 : Command/data byte (write: #$46)
             - Written with #$46 during command sequence
             
  $090005 : Command/response byte (write: #$34, read: response)
             - Written with #$34 during command sequence
             - Compared against #$4b (0x4B = 'K'?)
             - Read at $3AF8 to get response byte
             
  $090007 : Status/control register (read-only, bit-tested)
             - Bit 0: checked at $3D78 (ready/busy?)
             - Bit 2: checked at $3E20 (interrupt/status?)
             - Bit 3: checked at $3E28 (interrupt/status?)

COMMAND SEQUENCE (from $2BFE):
  1. lea $090001, a0      ; Point to C-Chip register
  2. move.b #$4a, $090001 ; Send command byte 0x4A
  3. move.b #$46, $090003 ; Send command byte 0x46
  4. move.b #$34, $090005 ; Send command byte 0x34

RESPONSE CHECK (from $2C2A):
  1. cmpi.b #$4b, $090005 ; Check if response == 0x4B
  2. bne.s  (loop)         ; Wait until response matches

STATUS CHECK (from $3D78):
  1. btst #0, $090007      ; Test bit 0 (ready flag?)
  2. bra  (wait)            ; Loop until bit set

INTERRUPT CHECK (from $3E1A):
  1. btst #2, $090007      ; Test bit 2
  2. btst #3, $090007      ; Test bit 3
  3. rts                   ; Return

COMMAND BYTES:
  0x4A = Initiate command / reset?
  0x46 = Parameter byte 1
  0x34 = Parameter byte 2
  0x4B = Expected response (maybe 'K' for OK?)

This looks like a simple command-response protocol:
  1. 68K writes command bytes to $090001-$090005
  2. C-Chip processes the command
  3. C-Chip writes response to $090005
  4. 68K polls $090005 waiting for expected response
  5. Status bits in $090007 indicate state
""")
