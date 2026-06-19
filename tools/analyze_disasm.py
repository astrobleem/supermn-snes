#!/usr/bin/env python3
"""
Analyze the full disassembly to identify key functions.
Find the largest code blocks and cross-reference with known addresses.
"""

import re
from collections import defaultdict

pasm_path = "/home/chad/supermn-snes/data/m68000_full.pasm"

# Parse blocks
blocks = []
current_block = None

with open(pasm_path) as f:
    for line in f:
        line = line.rstrip()
        
        # Block header
        m = re.match(r'; === Block \$([0-9a-fA-F]+)-\$([0-9a-fA-F]+) \((Code|Data)\) ===', line)
        if m:
            if current_block:
                blocks.append(current_block)
            current_block = {
                'start': int(m.group(1), 16),
                'end': int(m.group(2), 16),
                'type': m.group(3),
                'lines': [],
                'size': int(m.group(2), 16) - int(m.group(1), 16),
            }
            continue
        
        if current_block:
            current_block['lines'].append(line)

if current_block:
    blocks.append(current_block)

# Sort by size
code_blocks = [b for b in blocks if b['type'] == 'Code']
code_blocks.sort(key=lambda b: b['size'], reverse=True)

print(f"Total blocks: {len(blocks)}")
print(f"Code blocks: {len(code_blocks)}")
print(f"Data blocks: {len([b for b in blocks if b['type'] == 'Data'])}")
print()

# Print top 30 largest code blocks
print("Top 30 largest code blocks:")
for i, b in enumerate(code_blocks[:30]):
    # Find the label for this block
    label = ""
    for line in b['lines'][:3]:
        m = re.match(r'(entry|sub|loc)_([0-9a-fA-F]+):', line)
        if m:
            label = f"{m.group(1)}_{m.group(2)}"
            break
    
    # Count instructions
    instr_count = sum(1 for l in b['lines'] if '\t' in l and not l.strip().startswith(';'))
    
    # Check for interesting patterns
    block_text = '\n'.join(b['lines'])
    has_cchip = '700000' in block_text or '90000' in block_text
    has_sound = '80000' in block_text
    has_sprite = '0E0000' in block_text or 'sprite' in block_text.lower()
    has_palette = '0B0000' in block_text
    has_input = '50000' in block_text or 'input' in block_text.lower()
    
    flags = []
    if has_cchip: flags.append("C-CHIP")
    if has_sound: flags.append("SOUND")
    if has_sprite: flags.append("SPRITE")
    if has_palette: flags.append("PALETTE")
    if has_input: flags.append("INPUT")
    
    flag_str = f" [{', '.join(flags)}]" if flags else ""
    
    print(f"  {i+1:2d}. 0x{b['start']:06X}-0x{b['end']:06X}  size={b['size']:4d}B  {label:20s}  ({instr_count:3d} instr){flag_str}")

# Find all references to key addresses
print("\n\nKey address references:")
key_addrs = {
    '$00900C01': 'C-Chip command port',
    '$00900000': 'C-Chip shared RAM',
    '$00800000': 'Sound (YM2610)',
    '$00800001': 'Sound command port',
    '$00800003': 'Sound status port',
    '$000E0000': 'Sprite/tile RAM',
    '$000B0000': 'Palette RAM',
    '$000D0000': 'Video attribute RAM',
    '$000F0000': 'Work RAM',
    '$00500000': 'DIP switches',
    '$00500001': 'Input ports',
}

with open(pasm_path) as f:
    content = f.read()

for addr, desc in key_addrs.items():
    # Count references
    count = content.count(addr)
    if count > 0:
        # Find a few example lines
        examples = []
        for line in content.split('\n'):
            if addr in line and ('move' in line or 'jsr' in line or 'lea' in line):
                examples.append(line.strip()[:80])
                if len(examples) >= 3:
                    break
        print(f"\n  {addr} ({desc}): {count} references")
        for ex in examples:
            print(f"    {ex}")
