import sys
sys.path.insert(0, '/home/chad/SNES-SuperMonkeyIsland/tools')
from mcp_client import McpSession

with McpSession(rom='/home/chad/supermn-snes/build/sprite_test.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen',
                cwd='/home/chad/supermn-snes',
                port=7333) as m:
    m.run_frames(10)
    m.pause()
    
    state = m.get_state()
    print(f'State: {state}')
    
    ppu = m.get_ppu_state()
    print(f'PPU: mode={ppu["bgMode"]}, brightness={ppu["brightness"]}, mainLayers={ppu["mainScreenLayers"]}')
    
    # Take screenshot
    result = m.call('tools/call', {'name': 'take_screenshot', 'arguments': {'format': 'path'}})
    content = result.get('result', {}).get('content', [])
    if content:
        import json
        text = content[0].get('text', '')
        data = json.loads(text)
        print(f'Screenshot: {data}')
    
    # Check OAM
    oam = m.read_memory('snesSpriteRam', 0, 64)
    print(f'OAM first 32: {oam[:32]}')
    
    # Check CGRAM
    cgram = m.read_memory('snesCgRam', 0, 32)
    print(f'CGRAM first 16: {cgram[:16]}')
