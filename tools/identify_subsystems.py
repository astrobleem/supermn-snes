#!/usr/bin/env python3
"""
Identify major game subsystems from Superman disassembly.
Look for patterns that indicate game logic, rendering, audio, input, etc.
"""

import re
from collections import defaultdict

pasm_path = "/home/chad/supermn-snes/data/final_disasm.pasm"

with open(pasm_path) as f:
    content = f.read()
    lines = content.split('\n')

# Categorize subroutines by their address ranges and access patterns
subroutines = {}
current_sub = None

for i, line in enumerate(lines):
    # Look for subroutine definitions
    m = re.match(r'(sub|entry)_([0-9a-fA-F]+) = \$([0-9a-fA-F]+)', line)
    if m:
        name = m.group(1) + '_' + m.group(2)
        addr = int(m.group(3), 16)
        current_sub = name
        subroutines[addr] = {
            'name': name,
            'address': addr,
            'references': 0,
            'cchip_refs': 0,
            'sound_refs': 0,
            'sprite_refs': 0,
            'palette_refs': 0,
            'input_refs': 0,
            'vram_refs': 0,
            'jsr_targets': [],
        }

# Count references to each subroutine
for addr, info in subroutines.items():
    target = hex(addr)
    # Count JSR references
    pattern = r'jsr\s+\$' + target[2:].zfill(6)
    refs = len(re.findall(pattern, content, re.IGNORECASE))
    info['references'] = refs

# Check for distinct memory regions accessed
for i, line in enumerate(lines):
    # C-Chip references
    if re.search(r'00900\d', line):
        # Find nearest subroutine
        for addr in sorted(subroutines.keys(), reverse=True):
            if addr <= i * 2:  # rough approximation
                subroutines[addr]['cchip_refs'] += 1
                break
    
    # Sound references
    if re.search(r'80000[0-3]', line):
        for addr in sorted(subroutines.keys(), reverse=True):
            if addr <= i * 2:
                subroutines[addr]['sound_refs'] += 1
                break
    
    # Palette references
    if re.search(r'0B000[0-9A-Fa-f]', line, re.IGNORECASE):
        for addr in sorted(subroutines.keys(), reverse=True):
            if addr <= i * 2:
                subroutines[addr]['palette_refs'] += 1
                break
    
    # Sprite/tile RAM references
    if re.search(r'0E0[0-9A-Fa-f]{3}', line, re.IGNORECASE):
        for addr in sorted(subroutines.keys(), reverse=True):
            if addr <= i * 2:
                subroutines[addr]['sprite_refs'] += 1
                break
    
    # Input references
    if re.search(r'50000[0-9A-Fa-f]', line, re.IGNORECASE):
        for addr in sorted(subroutines.keys(), reverse=True):
            if addr <= i * 2:
                subroutines[addr]['input_refs'] += 1
                break

# Print categorized subroutines
print("=" * 70)
print("GAME SUBSYSTEM ANALYSIS")
print("=" * 70)

categories = {
    'C-Chip Communication': [],
    'Sound': [],
    'Sprite/GFX': [],
    'Palette': [],
    'Input': [],
    'High-level Game': [],
}

for addr, info in sorted(subroutines.items()):
    if info['cchip_refs'] > 0:
        categories['C-Chip Communication'].append(info)
    if info['sound_refs'] > 0:
        categories['Sound'].append(info)
    if info['sprite_refs'] > 0:
        categories['Sprite/GFX'].append(info)
    if info['palette_refs'] > 0:
        categories['Palette'].append(info)
    if info['input_refs'] > 0:
        categories['Input'].append(info)
    # High-level: referenced by many JSRs
    if info['references'] > 5:
        categories['High-level Game'].append(info)

for cat_name, items in categories.items():
    print(f"\n--- {cat_name} ({len(items)} subroutines) ---")
    # Sort by address
    items.sort(key=lambda x: x['address'])
    # Print first 20
    for item in items[:20]:
        refs_str = f"refs={item['references']}"
        detail = []
        if item['cchip_refs']: detail.append(f"cchip={item['cchip_refs']}")
        if item['sound_refs']: detail.append(f"snd={item['sound_refs']}")
        if item['sprite_refs']: detail.append(f"spr={item['sprite_refs']}")
        if item['palette_refs']: detail.append(f"pal={item['palette_refs']}")
        if item['input_refs']: detail.append(f"inp={item['input_refs']}")
        detail_str = ', '.join(detail)
        print(f"  ${item['address']:06X}  {item['name']:20s}  {refs_str:12s}  {detail_str}")

# Print overall statistics
print(f"\n\nTotal subroutines: {len(subroutines)}")
print(f"Total code bytes: {len(subroutines) * 2}")
print()
print("Subroutines by category:")
for cat_name, items in categories.items():
    print(f"  {cat_name:30s}: {len(items):4d}")

# Identify the most-referenced subroutines (likely main game functions)
print("\n\n--- Most Referenced Subroutines (main game functions) ---")
top_refs = sorted(subroutines.values(), key=lambda x: x['references'], reverse=True)
for item in top_refs[:30]:
    print(f"  ${item['address']:06X}  {item['name']:20s}  refs={item['references']}")
