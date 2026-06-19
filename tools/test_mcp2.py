import sys
sys.path.insert(0, '/home/chad/SNES-SuperMonkeyIsland/tools')
from mcp_client import McpSession

with McpSession(rom='/home/chad/supermn-snes/build/sprite_test.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen',
                cwd='/home/chad/supermn-snes',
                port=7333) as m:
    # Try listing tools again
    tools = m.call('tools/list')
    tool_names = [t['name'] for t in tools.get('result', {}).get('tools', [])]
    print(f'Tools: {len(tool_names)}')
    for name in tool_names:
        print(f'  {name}')
    
    # Try render_palette (simpler)
    try:
        result = m.call('render_palette', {'mode': 'grid'})
        print(f'Palette render: {result}')
    except Exception as e:
        print(f'Palette error: {e}')
    
    # Try render_tile_sheet
    try:
        result = m.call('render_tile_sheet', {'address': 0, 'length': 0x1000, 'palette': 0, 'bpp': 4})
        print(f'Tile sheet: {result}')
    except Exception as e:
        print(f'Tile sheet error: {e}')
