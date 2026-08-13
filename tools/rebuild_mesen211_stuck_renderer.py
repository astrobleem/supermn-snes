#!/usr/bin/env python3
"""Rebuild one wedged legacy-Mesen renderer checkpoint with a selected ROM.

This is an explicitly intervened diagnostic for old checkpoints whose serialized
5A22 renderer never reaches an idle boundary.  It freezes the SA-1 producer,
refreshes only the selected ROM's video-supervisor mirror, discards the stale
renderer job/queues, seeds the private cache from the paused live X1 planes, and
resumes the 5A22 at its WRAM worker loop.  It never modifies the ROM or advances
the game tick, and it is not same-lineage, fresh-boot, performance, or gameplay
acceptance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import capture_mesen211_transitions as capture  # noqa: E402
from capture_snes_input_framebuffers import (  # noqa: E402
    QUEUE_CODE_MARK_OFFSET,
    QUEUE_PROMOTER_LENGTH,
    QUEUE_PROMOTER_WRAM_OFFSET,
    VIDEO_FILE_BASE,
    VIDEO_WRAM_LENGTH,
    VIDEO_WRAM_OFFSET,
    configure_dotnet,
    write_checked,
)
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--port", type=int, default=43541)
    parser.add_argument("--max-frames", type=int, default=1200)
    parser.add_argument("--checkpoint-step", type=int, default=50)
    parser.add_argument("--coherent-idle-settle-frames", type=int, default=2)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def coherent_idle(row: dict[str, Any]) -> bool:
    generations = (
        row["snapshot_generation"],
        row["direct_generation"],
        row["rendered_generation"],
    )
    return (
        row["renderer_busy"] == 0
        and row["render_queue_primary"] == 0
        and row["render_queue_secondary"] == 0
        and len(set(generations)) == 1
        and not (row["snapshot_generation"] & 1)
    )


def cpu_pc(state: dict[str, Any]) -> int:
    return ((int(state.get("k", 0)) & 0xFF) << 16) | (
        int(state.get("pc", 0)) & 0xFFFF
    )


def resume_snes_worker(
    m: McpSession,
) -> tuple[dict[str, Any], int, bytes]:
    before = m.get_cpu_state("Snes")
    address = cpu_pc(before)
    # Legacy Mesen's MCP intentionally has no set_cpu_state tool.  The wedged
    # foreground renderer executes from the writable $7F mirror, so replace
    # its exact paused instruction with JML $7E:F000.  The next frame executes
    # the redirect; no serialized return frame or source ROM byte is changed.
    if not (0x7F8000 <= address < 0x7FB000 or address == 0x00942C):
        raise RuntimeError(
            f"refusing to redirect unexpected 5A22 PC ${address:06X}; "
            "expected the serialized renderer mirror or NMI trampoline"
        )
    # The frame API normally pauses at the ROM NMI trampoline before its JML.
    # Route that one entry through private WRAM, establish wl_poll's native
    # A16/X16, DP=$0000, DBR=$00 contract, then enter the real worker.  The
    # caller restores the trampoline immediately after advancing one frame.
    shim = bytes.fromhex("c230a900005be220a90048abc2305c00f07e")
    shim_write = write_checked(
        m,
        0x07E00,
        shim,
        "install one-shot 5A22 worker-resume shim",
    )
    original = bytes(m.read_memory("snesMemory", address, 4))
    redirect = bytes.fromhex("5c007e7e")
    m.write_memory("snesMemory", address, redirect.hex())
    observed = bytes(m.read_memory("snesMemory", address, 4))
    if observed != redirect:
        raise RuntimeError(
            f"5A22 worker redirect did not verify at ${address:06X}: "
            f"{observed.hex()}"
        )
    return (
        {
            "reason": "one-shot redirect from the paused 5A22 boundary through a width/bank-safe shim to wl_poll",
            "region": f"snesMemory ${address:06X}-${address + 3:06X}",
            "bytes": redirect.hex(),
            "original_bytes": original.hex(),
            "before": before,
            "shim": "7E7E00",
            "shim_write": shim_write,
            "target_pc": "7EF000",
        },
        address,
        original,
    )


def main() -> int:
    args = parse_args()
    if (
        args.max_frames <= 0
        or args.checkpoint_step <= 0
        or args.coherent_idle_settle_frames < 0
    ):
        raise SystemExit("invalid frame count")
    for path in (args.rom, args.state, args.emulator):
        if not path.is_file():
            raise FileNotFoundError(path)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    output.mkdir(parents=True)

    configure_dotnet(args.emulator)
    rom = args.rom.resolve()
    rom_bytes = rom.read_bytes()
    if len(rom_bytes) != 0x400000:
        raise SystemExit("expected a 4 MiB production ROM")
    if int.from_bytes(rom_bytes[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")

    interventions: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    settled = False
    idle_streak = 0
    with McpSession(
        rom=rom,
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=300.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        start = capture.snapshot(m)
        frozen_tick = start["tick"]
        interventions.append(
            capture.park_sa1_at_current_pc(
                m, "freeze the exact game/X1 producer during renderer reconstruction"
            )
        )

        mirror = rom_bytes[
            VIDEO_FILE_BASE : VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH
        ]
        for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000):
            interventions.append(
                write_checked(
                    m,
                    VIDEO_WRAM_OFFSET + offset,
                    mirror[offset : offset + 0x1000],
                    "cross-ROM checkpoint video-mirror refresh",
                )
            )
        interventions.append(
            write_checked(
                m,
                QUEUE_CODE_MARK_OFFSET,
                bytes(2),
                "force the selected ROM's lazy queue-promoter installation",
            )
        )
        interventions.append(
            write_checked(
                m,
                QUEUE_PROMOTER_WRAM_OFFSET,
                bytes(QUEUE_PROMOTER_LENGTH),
                "remove the checkpoint's superseded queue-promoter code",
            )
        )

        live_bg = bytes(m.read_memory("snesMemory", 0x414800, 0x0800))
        live_palette = bytes(m.read_memory("snesMemory", 0x412000, 0x0400))
        live_y = bytes(
            m.read_memory("snesMemory", 0x413401 + column * 0x20, 1)[0]
            for column in range(16)
        )
        interventions.append(
            write_checked(
                m,
                0x02000,
                live_bg,
                "seed renderer BG code/color cache from paused live X1 planes",
            )
        )
        interventions.append(
            write_checked(
                m,
                0x02800,
                live_palette,
                "seed renderer palette cache from paused live X1 palette",
            )
        )
        interventions.append(
            write_checked(
                m,
                0x072C0,
                live_y,
                "seed current per-column Y metadata from paused live X1 records",
            )
        )

        # The serialized job cannot be resumed under a different supervisor.
        # Discard it explicitly, then force one complete cache-backed render.
        for offset, length, label in (
            (0x0899C, 2, "discard serialized renderer-busy ownership"),
            (0x089D2, 2, "discard serialized primary queue"),
            (0x089D6, 2, "discard serialized secondary queue"),
            (0x0A000, 0x0800, "clear legacy BG code/slot hash"),
            (0x0D000, 0x0180, "clear legacy BG reverse ownership"),
            (0x07C00, 0x00C0, "clear legacy BG free list"),
        ):
            interventions.append(write_checked(m, offset, bytes(length), label))
        interventions.append(
            write_checked(
                m,
                0x089F0,
                bytes([0xFF]) * 16,
                "invalidate the serialized applied BG column map",
            )
        )
        for offset, value, label in (
            (0x089C2, 0x0000, "reset BG free-list count"),
            (0x000DC, 0x0001, "start BG artwork allocation at slot one"),
            (0x089D0, 0xB7C5, "install reserved-blank reverse-map marker"),
            (0x089C4, 0x0000, "clear legacy prepared-list length"),
            (0x08982, 0x0000, "invalidate legacy raw BG cache marker"),
            (0x08990, 0x0001, "force a BG renderer event"),
            (0x089BC, 0xFFFF, "force one complete BG rebuild"),
            (0x089BE, 0x0001, "force the seeded live palette"),
            (0x072B1, 0x0000, "invalidate serialized Mode-2 publication"),
        ):
            interventions.append(
                write_checked(m, offset, value.to_bytes(2, "little"), label)
            )

        direct_generation = int.from_bytes(
            m.read_memory("snesWorkRam", 0x089A0, 2), "little"
        )
        forced_generation = (direct_generation + 2) & 0xFFFE
        if forced_generation == 0:
            forced_generation = 2
        interventions.append(
            write_checked(
                m,
                0x0899A,
                forced_generation.to_bytes(2, "little"),
                "publish the seeded cache as a complete private generation",
            )
        )
        frame_ack = int.from_bytes(
            m.read_memory("snesMemory", 0x003302, 2), "little"
        )
        forced_request = (frame_ack + 1) & 0xFFFF or 1
        interventions.append(
            write_checked(
                m,
                0x01F1E,
                forced_request.to_bytes(2, "little"),
                "publish the forced local rebuild to the render worker",
            )
        )
        redirect_record, redirect_address, redirect_original = resume_snes_worker(m)
        interventions.append(redirect_record)

        start_after = capture.snapshot(m)
        start_after["relative_frame"] = 0
        start_after["screenshot"] = capture.take_screenshot(
            m, output / "frame-000000.png"
        )
        start_after["checkpoint"] = capture.save_checkpoint(
            m, output / "frame-000000.mss"
        )
        samples.append(start_after)

        for relative in range(1, args.max_frames + 1):
            response = m.set_input(0, 1)
            m.pause()
            advanced = int(response.get("framesAdvanced", response.get("frames", 0)))
            if advanced != 1:
                raise RuntimeError(f"one-frame advance failed: {response!r}")
            if relative == 1:
                m.write_memory(
                    "snesMemory", redirect_address, redirect_original.hex()
                )
                restored = bytes(
                    m.read_memory("snesMemory", redirect_address, len(redirect_original))
                )
                if restored != redirect_original:
                    raise RuntimeError(
                        f"5A22 boundary restore failed at ${redirect_address:06X}: "
                        f"{restored.hex()}"
                    )
                interventions.append(
                    {
                        "reason": "restore the one-shot 5A22 redirect before the next frame executes",
                        "region": (
                            f"snesMemory ${redirect_address:06X}-"
                            f"${redirect_address + len(redirect_original) - 1:06X}"
                        ),
                        "bytes": redirect_original.hex(),
                    }
                )
            row = capture.snapshot(m)
            row["relative_frame"] = relative
            if row["tick"] != frozen_tick:
                raise RuntimeError(
                    f"SA-1 producer freeze failed: tick {frozen_tick}->{row['tick']}"
                )
            if relative % args.checkpoint_step == 0:
                row["checkpoint"] = capture.save_checkpoint(
                    m, output / f"frame-{relative:06d}.mss"
                )
                row["screenshot"] = capture.take_screenshot(
                    m, output / f"frame-{relative:06d}.png"
                )
            samples.append(row)
            if coherent_idle(row):
                idle_streak += 1
            else:
                idle_streak = 0
            if idle_streak > args.coherent_idle_settle_frames:
                row["checkpoint"] = capture.save_checkpoint(
                    m, output / "coherent-idle.mss"
                )
                row["screenshot"] = capture.take_screenshot(
                    m, output / "coherent-idle.png"
                )
                settled = True
                break

    report = {
        "schema": 1,
        "scope": (
            "intervened legacy-Mesen reconstruction of a serialized wedged renderer; "
            "SA-1 producer frozen; not same-lineage, fresh-boot, performance, pixel-oracle, "
            "or gameplay acceptance evidence"
        ),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "emulator": str(args.emulator.resolve()),
        "start": start,
        "runtime_interventions": interventions,
        "coherent_idle_reached": settled,
        "final_coherent_idle_streak": idle_streak,
        "samples": samples,
    }
    target = output / "results.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "coherent_idle_reached": settled,
                "frames": samples[-1]["relative_frame"],
                "result": str(target),
            },
            sort_keys=True,
        )
    )
    return 0 if settled else 1


if __name__ == "__main__":
    raise SystemExit(main())
