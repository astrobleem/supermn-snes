#!/usr/bin/env python3
"""Print a header/metadata report for one or more VGM/VGZ files.

Usage:
  python3 tools/sound/vgm_header_report.py soundwork/source/vgm_unpacked/*.vgm
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vgmlib


def main(argv):
    for arg in argv:
        p = Path(arg)
        try:
            data = vgmlib.read_vgm(p)
        except Exception as e:  # noqa: BLE001
            print(f"{p.name}: {e}")
            continue
        h = vgmlib.parse_header(data)
        loop = f"{h.loop_seconds:.2f}s @0x{h.loop_offset:X}" if h.loop_offset else "none"
        print(f"{p.name}")
        print(f"  version       0x{h.version:08X}")
        print(f"  chip          {'YM2610B' if h.ym2610b else 'YM2610'} @ {h.ym2610_clock} Hz")
        print(f"  data_start    0x{h.data_start:X}")
        print(f"  total         {h.total_samples} ({h.total_seconds:.2f}s)")
        print(f"  loop          {loop}")
        if h.gd3.get("track_en"):
            print(f"  title         {h.gd3['track_en']}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1:])
