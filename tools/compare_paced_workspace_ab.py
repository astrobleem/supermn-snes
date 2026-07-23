#!/usr/bin/env python3
"""Compare producer state at identical production pacing boundaries.

This is a checkpointed A/B semantic and local-cycle test, not FPS evidence.
Both ROMs load the same production checkpoint, receive the same real port-0
input, and stop at successive ``lhp_wai`` hooks after the game tick has
published its renderer manifest.  The comparison deliberately gates only
game/producer-owned BW-RAM; renderer handshake bytes can legitimately differ
because a faster producer reaches the boundary at a different 5A22 cycle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import validate_gameplay_controls as controls


WAI_HOOK = 0x99FB51
CHUNK = 0x4000

# These ranges are owned by the 68K/SA-1 producer at lhp_wai.  They cover the
# complete emulated game RAM, manifest metadata, accepted/candidate BG images,
# compact BG/OBJ lists, renderer source shadow, prepared full-map products, and
# the hash tables used to construct those products.
GATED_RANGES = (
    ("game_ram", 0x400000, 0x10000),
    ("manifest_metadata", 0x410132, 0x0016),
    ("bg_baseline_candidate", 0x410200, 0x1000),
    ("bg_obj_lists", 0x411A00, 0x0600),
    ("renderer_source_shadow", 0x412000, 0x3000),
    ("prepared_tilemap", 0x418000, 0x1000),
    ("prepared_unique_codes", 0x419000, 0x0180),
    ("prepared_palette_map", 0x419200, 0x0020),
    ("prepare_hash_tables", 0x41A000, 0x0800),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-rom", type=Path, required=True)
    parser.add_argument("--candidate-rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=controls.DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--boundaries", type=int, default=6)
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument(
        "--prepared-only",
        action="store_true",
        help=(
            "Compare the first $FFFE prepared-full manifest observed in each "
            "run instead of pairing coarse run_until samples by index."
        ),
    )
    parser.add_argument(
        "--buttons",
        type=lambda value: int(value, 0),
        default=controls.McpSession.BTN_RIGHT | controls.McpSession.BTN_B,
    )
    return parser.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def read_chunks(session: controls.McpSession, address: int, length: int) -> bytes:
    result = bytearray()
    for offset in range(0, length, CHUNK):
        size = min(CHUNK, length - offset)
        result.extend(session.read_memory("snesMemory", address + offset, size))
    return bytes(result)


def capture_variant(
    *,
    name: str,
    rom: Path,
    state: Path,
    nexen: Path,
    output: Path,
    port: int,
    boundaries: int,
    buttons: int,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    stderr_log = output / f"{name}-nexen.stderr.log"
    with controls.McpSession(
        rom=rom,
        mesen=nexen,
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=stderr_log,
    ) as session:
        session.pause()
        session.load_state(state)
        session.pause()
        session.tool("set_input", {"port": 0, "buttons": buttons, "hold": True})
        initial = controls.snapshot(session, f"{name}/initial")
        controls.require_healthy(f"{name}/initial", initial)

        previous_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
        for index in range(boundaries):
            hook = session.add_exec_hook(WAI_HOOK, cpu_type="Sa1")
            session.drain_notifications(timeout=0.05)
            hit = session.run_until(max_frames=30, hook_handle=hook)
            session.pause()
            session.remove_hook(hook)
            if (hit or {}).get("reason") != "hookFired":
                raise RuntimeError(f"{name} boundary {index}: hook failed: {hit!r}")

            snap = controls.snapshot(session, f"{name}/boundary-{index}")
            controls.require_healthy(f"{name}/boundary-{index}", snap)
            cycle_count = int(session.get_cpu_state("Sa1")["cycleCount"])
            ranges: dict[str, dict[str, Any]] = {}
            for range_name, address, length in GATED_RANGES:
                data = read_chunks(session, address, length)
                path = output / f"{name}-b{index:02d}-{range_name}.bin"
                path.write_bytes(data)
                ranges[range_name] = {
                    "address": f"{address:06X}",
                    "length": length,
                    "sha256": sha256_bytes(data),
                    "path": str(path),
                }
            samples.append(
                {
                    "index": index,
                    "tick": snap["tick"],
                    "frame": snap["frame"],
                    "sa1_cycles": cycle_count,
                    "sa1_cycle_delta": cycle_count - previous_cycles,
                    "frame_request": snap["frame_request"],
                    "frame_ack": snap["frame_ack"],
                    "pacing_catchup_debt": snap["pacing_catchup_debt"],
                    "bg_manifest_length": le16(
                        session.read_memory("snesMemory", 0x41013A, 2)
                    ),
                    "prepared_unique_length": le16(
                        session.read_memory("snesMemory", 0x410146, 2)
                    ),
                    "minimum_stack_margin": snap["stack"]["minimum_margin"],
                    "ranges": ranges,
                }
            )
            previous_cycles = cycle_count
    return samples


def mismatch_summary(left: bytes, right: bytes) -> dict[str, Any]:
    offsets = [
        index for index, (a, b) in enumerate(zip(left, right)) if a != b
    ]
    return {
        "mismatch_count": len(offsets),
        "first_mismatches": [
            {"offset": offset, "reference": left[offset], "candidate": right[offset]}
            for offset in offsets[:32]
        ],
        "reference_sha256": sha256_bytes(left),
        "candidate_sha256": sha256_bytes(right),
    }


def main() -> int:
    args = parse_args()
    if args.boundaries <= 0:
        raise SystemExit("--boundaries must be positive")
    if not 0 <= args.buttons <= 0x0FFF:
        raise SystemExit("--buttons must be a 12-bit Nexen controller mask")
    paths = (args.reference_rom, args.candidate_rom, args.state, args.nexen)
    for path in paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(path)
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    args.output.mkdir(parents=True)

    reference = capture_variant(
        name="reference",
        rom=args.reference_rom.resolve(),
        state=args.state.resolve(),
        nexen=args.nexen.resolve(),
        output=args.output,
        port=args.port,
        boundaries=args.boundaries,
        buttons=args.buttons,
    )
    candidate = capture_variant(
        name="candidate",
        rom=args.candidate_rom.resolve(),
        state=args.state.resolve(),
        nexen=args.nexen.resolve(),
        output=args.output,
        port=args.port + 1,
        boundaries=args.boundaries,
        buttons=args.buttons,
    )

    if args.prepared_only:
        reference_prepared = [
            sample for sample in reference if sample["bg_manifest_length"] == 0xFFFE
        ]
        candidate_prepared = [
            sample for sample in candidate if sample["bg_manifest_length"] == 0xFFFE
        ]
        if not reference_prepared or not candidate_prepared:
            raise RuntimeError(
                "prepared-only comparison did not observe $FFFE in both runs: "
                f"reference={len(reference_prepared)}, candidate={len(candidate_prepared)}"
            )
        pairs = [(reference_prepared[0], candidate_prepared[0])]
    else:
        pairs = list(zip(reference, candidate))

    comparisons: list[dict[str, Any]] = []
    total_mismatches = 0
    tick_mismatches = 0
    for ref_sample, cand_sample in pairs:
        tick_match = ref_sample["tick"] == cand_sample["tick"]
        tick_mismatches += int(not tick_match)
        ranges: dict[str, Any] = {}
        for name, _address, _length in GATED_RANGES:
            left = Path(ref_sample["ranges"][name]["path"]).read_bytes()
            right = Path(cand_sample["ranges"][name]["path"]).read_bytes()
            result = mismatch_summary(left, right)
            total_mismatches += int(result["mismatch_count"])
            ranges[name] = result
        comparisons.append(
            {
                "index": ref_sample["index"],
                "reference_index": ref_sample["index"],
                "candidate_index": cand_sample["index"],
                "tick_match": tick_match,
                "reference_tick": ref_sample["tick"],
                "candidate_tick": cand_sample["tick"],
                "reference_cycle_delta": ref_sample["sa1_cycle_delta"],
                "candidate_cycle_delta": cand_sample["sa1_cycle_delta"],
                "candidate_cycle_savings": (
                    ref_sample["sa1_cycle_delta"] - cand_sample["sa1_cycle_delta"]
                ),
                "reference_bg_manifest_length": ref_sample["bg_manifest_length"],
                "candidate_bg_manifest_length": cand_sample["bg_manifest_length"],
                "reference_prepared_unique_length": ref_sample["prepared_unique_length"],
                "candidate_prepared_unique_length": cand_sample["prepared_unique_length"],
                "ranges": ranges,
            }
        )

    result = "green" if total_mismatches == 0 and tick_mismatches == 0 else "red"
    summary = {
        "scope": (
            "checkpointed same-input prepared-full producer-state A/B; "
            "not FPS and cycle deltas are informational only"
            if args.prepared_only
            else "checkpointed same-input, same-lhp_wai-boundary producer-state A/B; "
            "local SA-1 cycle deltas only, not FPS"
        ),
        "result": result,
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--porcelain=v1").splitlines(),
        "reference_rom": str(args.reference_rom.resolve()),
        "reference_rom_sha256": sha256_file(args.reference_rom),
        "candidate_rom": str(args.candidate_rom.resolve()),
        "candidate_rom_sha256": sha256_file(args.candidate_rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256_file(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256_file(args.nexen),
        "hook": f"{WAI_HOOK:06X}",
        "buttons": args.buttons,
        "boundaries": args.boundaries,
        "prepared_only": args.prepared_only,
        "comparison_count": len(comparisons),
        "gated_bytes_per_boundary": sum(length for _, _, length in GATED_RANGES),
        "total_mismatches": total_mismatches,
        "tick_mismatches": tick_mismatches,
        "reference": reference,
        "candidate": candidate,
        "comparisons": comparisons,
    }
    summary_path = args.output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "event": "summary",
                "result": result,
                "boundaries": args.boundaries,
                "gated_bytes_per_boundary": summary["gated_bytes_per_boundary"],
                "total_mismatches": total_mismatches,
                "tick_mismatches": tick_mismatches,
                "cycle_savings": (
                    []
                    if args.prepared_only
                    else [
                        comparison["candidate_cycle_savings"]
                        for comparison in comparisons
                    ]
                ),
                "summary": str(summary_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if result == "green" else 2


if __name__ == "__main__":
    raise SystemExit(main())
