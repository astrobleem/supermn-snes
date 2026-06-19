import sys
sys.path.insert(0, '/home/chad/SNES-SuperMonkeyIsland/tools')
from mcp_client import McpSession

with McpSession(rom='/home/chad/supermn-snes/build/sprite_test.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen',
                cwd='/home/chad/supermn-snes',
                port=7333) as m:
    # Try calling tools/call directly
    try:
        result = m.call('tools/call', {'name': 'take_screenshot', 'arguments': {'format': 'path'}})
        print(f'tools/call result: {result}')
    except Exception as e:
        print(f'tools/call error: {e}')
    
    # Try with different method name
    try:
        result = m.call('take_screenshot', {'format': 'path'})
        print(f'direct result: {result}')
    except Exception as e:
        print(f'direct error: {e}')
