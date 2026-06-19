import sys
sys.path.insert(0, '/home/chad/SNES-SuperMonkeyIsland/tools')
from mcp_client import McpSession

with McpSession(rom='/home/chad/supermn-snes/build/sprite_test.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen',
                cwd='/home/chad/supermn-snes',
                port=7333) as m:
    # List available tools
    tools = m.call('tools/list')
    print('Available tools:')
    for t in tools.get('result', {}).get('tools', []):
        print(f"  {t['name']}: {t.get('description', '')[:80]}")
