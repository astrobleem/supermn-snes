import sys
sys.path.insert(0, '/home/chad/SNES-SuperMonkeyIsland/tools')
from mcp_client import McpSession

with McpSession(rom='/home/chad/supermn-snes/build/sprite_test.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen',
                cwd='/home/chad/supermn-snes',
                port=7333) as m:
    # Run a few frames
    m.run_frames(10)
    m.pause()
    
    # Take screenshot via tools/call
    result = m.call('tools/call', {'name': 'take_screenshot', 'arguments': {'format': 'path'}})
    content = result.get('result', {}).get('content', [])
    if content:
        import json
        text = content[0].get('text', '')
        data = json.loads(text)
        print(f'Screenshot: {data}')
    
    # Render OAM
    result = m.call('tools/call', {'name': 'render_oam', 'arguments': {'mode': 'positioned'}})
    content = result.get('result', {}).get('content', [])
    if content:
        import json
        text = content[0].get('text', '')
        data = json.loads(text)
        print(f'OAM render: {data}')
    
    # Render palette
    result = m.call('tools/call', {'name': 'render_palette', 'arguments': {'mode': 'grid'}})
    content = result.get('result', {}).get('content', [])
    if content:
        import json
        text = content[0].get('text', '')
        data = json.loads(text)
        print(f'Palette: {data}')
