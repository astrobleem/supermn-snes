#!/usr/bin/env python3
"""Map logical row-start writes through MAME's Superman video device."""

from __future__ import annotations

import json

import validate_render_helpers as base


def main() -> int:
    mame = base.MameSession(
        mame="/snap/bin/mame",
        system="superman",
        rompath=str(base.MAME_TRACE / "roms"),
        workdir=str(base.MAME_TRACE),
        state_directory=str(base.MAME_TRACE / "sta"),
        extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
    )
    try:
        mame.launch(boot_wait=25)
        mame.pause()
        for plane in (0xE00800, 0xE00C00):
            mame.write_block(plane, bytes(0x400))
            rows = list(range(0, 0x380, 0x40))
            requested = {}
            for index, offset in enumerate(rows):
                value = 0x1000 | index
                requested[offset] = value
                mame.write_block(plane + offset, value.to_bytes(2, "big"))
            observed = {
                offset: int.from_bytes(mame.read_block(plane + offset, 2), "big")
                for offset in rows
            }
            print(
                json.dumps(
                    {
                        "event": "plane",
                        "plane": f"{plane:06X}",
                        "requested": {f"{key:03X}": value for key, value in requested.items()},
                        "observed": {f"{key:03X}": value for key, value in observed.items()},
                    },
                    sort_keys=True,
                )
            )
    finally:
        mame.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
