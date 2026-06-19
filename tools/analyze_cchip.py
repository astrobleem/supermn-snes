#!/usr/bin/env python3
"""
Analyze C-Chip protocol from Superman disassembly.

C-Chip memory map (from MAME taito_x.cpp):
  $900000-$9007FF : mem68_r/mem68_w (C-Chip shared RAM, 1KB window)
  $900800-$900FFF : asic_r/asic68_w (ASIC registers)
  $900800 : Bank select (write) / status (read)
  $900801 : ASIC RAM byte 0
  $900802 : ASIC RAM byte 1
  $900803 : ASIC RAM byte 2
  $900805 : Command/response byte
  $900807 : Status/control byte

From the disassembly, we see accesses to:
  $090001 - likely ASIC RAM or command reg
  $090003 - likely ASIC RAM
  $090005 - command/response byte
  $090007 - status/control byte (bit 0, 2, 3 checked)
"""

import re

pasm_path = "/home/chad/supermn-snes/data/final_disasm.pasm"

with open(pasm_path) as f:
    lines = f.readlines()

# Find all C-Chip related code blocks
cchip_blocks = []
current_block = None
in_cchip_block = False

for i, line in enumerate(lines):
    line = line.rstrip()
    
    # Check if this is a block header
    m = re.match(r'; === Block \$([0-9a-fA-F]+)-\$([0-9a-fA-F]+) \((Code|Data)\) ===', line)
    if m:
        if current_block and in_cchip_block:
            cchip_blocks.append(current_block)
        
        current_block = {
            'start': int(m.group(1), 16),
            'end': int(m.group(2), 16),
            'type': m.group(3),
            'lines': [],
            'addresses': [],
        }
        in_cchip_block = False
        continue
    
    if current_block:
        current_block['lines'].append(line)
        
        # Check for C-Chip address references
        if re.search(r'00900[0-9A-Fa-f]{2}', line) or re.search(r'\$900[0-9A-Fa-f]{2}', line):
            in_cchip_block = True
            # Extract the address
            addr_match = re.search(r'009?0?0?([0-9A-Fa-f]{2})', line)
            if addr_match:
                current_block['addresses'].append(addr_match.group(0))

if current_block and in_cchip_block:
    cchip_blocks.append(current_block)

print(f"Found {len(cchip_blocks)} C-Chip related code blocks")
print()

# Print each block with context
for block in cchip_blocks:
    print(f"=== Block ${block['start']:06X}-${block['end']:06X} (size={block['end']-block['start']}B) ===")
    for line in block['lines']:
        if line.strip():
            print(f"  {line}")
    print()

# Also search for specific C-Chip patterns
print("\n\n=== C-CHIP PROTOCOL ANALYSIS ===\n")

# Find all writes to C-Chip registers
print("Writes to C-Chip registers:")
for i, line in enumerate(lines):
    line = line.rstrip()
    # Match: move.b/move.w #value, $09000X or move.b/move.w dN, $09000X
    m = re.search(r'move\.[bw]\s+(#\S+|d\d),\s*\$?0*900([0-9A-Fa-f]{2})', line, re.IGNORECASE)
    if m:
        value = m.group(1)
        reg = m.group(2)
        # Get context (previous 3 lines)
        ctx_start = max(0, i - 3)
        ctx = '\n'.join(l.rstrip() for l in lines[ctx_start:i+1])
        print(f"  Write to $090{reg}: {value}")
        print(f"    Context: ...{lines[i-1].rstrip() if i > 0 else ''}")
        print(f"    {line}")
        print()

# Find all reads from C-Chip registers
print("\nReads from C-Chip registers:")
for i, line in enumerate(lines):
    line = line.rstrip()
    m = re.search(r'move\.[bw]\s+\$?0*900([0-9A-Fa-f]{2}),\s*(#\S+|d\d|\(.*\))', line, re.IGNORECASE)
    if m:
        reg = m.group(1)
        dest = m.group(2)
        print(f"  Read from $090{reg} -> {dest}: {line}")

# Find btst instructions on C-Chip registers
print("\nBit tests on C-Chip registers:")
for i, line in enumerate(lines):
    line = line.rstrip()
    m = re.search(r'btst\s+#(\d+),\s*\$?0*900([0-9A-Fa-f]{2})', line, re.IGNORECASE)
    if m:
        bit = m.group(1)
        reg = m.group(2)
        # Get the branch that follows
        next_lines = '\n'.join(l.rstrip() for l in lines[i:min(i+3, len(lines))])
        print(f"  btst #{bit}, $090{reg}: {line}")
        if i + 1 < len(lines):
            print(f"    -> {lines[i+1].rstrip()}")
        print()
