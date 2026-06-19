#!/usr/bin/env python3
"""Quick subsystem identification from disassembly."""

import re

pasm_path = "/home/chad/supermn-snes/data/final_disasm.pasm"

with open(pasm_path) as f:
    content = f.read()

# Find all subroutines
subs = {}
for m in re.finditer(r'(sub|entry)_([0-9a-fA-F]+) = \$([0-9a-fA-F]+)', content):
    name = m.group(1) + '_' + m.group(2)
    addr = int(m.group(3), 16)
    subs[addr] = {'name': name, 'refs': 0, 'cchip': 0, 'sound': 0, 'sprite': 0, 'palette': 0, 'input': 0}

# Count JSR references
for addr in subs:
    target = f"${addr:06X}"
    subs[addr]['refs'] = len(re.findall(r'jsr\s+' + re.escape(target), content, re.IGNORECASE))

# Count memory region accesses
cchip_matches = list(re.finditer(r'00900\d', content))
sound_matches = list(re.finditer(r'80000[0-3]', content))
sprite_matches = list(re.finditer(r'0E0[0-9A-Fa-f]{3}', content, re.IGNORECASE))
palette_matches = list(re.finditer(r'0B000[0-9A-Fa-f]', content, re.IGNORECASE))
input_matches = list(re.finditer(r'50000[0-9A-Fa-f]', content, re.IGNORECASE))

print(f"C-Chip accesses: {len(cchip_matches)}")
print(f"Sound accesses: {len(sound_matches)}")
print(f"Sprite RAM accesses: {len(sprite_matches)}")
print(f"Palette accesses: {len(palette_matches)}")
print(f"Input accesses: {len(input_matches)}")

# Print top referenced subroutines
print("\n--- Top 30 Most Referenced Subroutines ---")
top = sorted(subs.values(), key=lambda x: x['refs'], reverse=True)
for item in top[:30]:
    print(f"  ${item['address']:06X}  {item['name']:20s}  refs={item['refs']}")

# Print all subroutines with references > 0
print(f"\n--- All Referenced Subroutines ({sum(1 for s in subs.values() if s['refs'] > 0)}) ---")
referenced = sorted([(addr, info) for addr, info in subs.items() if info['refs'] > 0], key=lambda x: x[1]['refs'], reverse=True)
for addr, info in referenced[:50]:
    print(f"  ${addr:06X}  {info['name']:20s}  refs={info['refs']}")
