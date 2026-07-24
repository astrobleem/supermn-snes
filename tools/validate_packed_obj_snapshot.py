#!/usr/bin/env python3
"""Validate compact production OBJ/BG snapshots at the 5A22 DMA boundary.

This is a checkpointed representation-equivalence gate, not an end-to-end
performance measurement.  It pauses on the compact-manifest DMA helper's RTS,
while the SA-1 still owns a stable game boundary.  The bit-15 tag, byte length,
packed Y/code/X records, and the two control words displaced from the former
raw-plane DMA must match both the source planes and producer image exactly.
The complete BG candidate must also match the coherent live planes, and every
ordinary BG offset list must be the exact delta from the accepted baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
MANIFEST_DONE_HOOK = 0x7FA665
PRODUCER_BG_DONE_HOOK = 0x9EDDF6
VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--port", type=int, default=7663)
    parser.add_argument(
        "--input-buttons",
        type=lambda value: int(value, 0),
        default=0,
        help="Hold this Nexen port-0 button mask while collecting samples.",
    )
    parser.add_argument(
        "--bg-producer-only",
        action="store_true",
        help=(
            "Sample every SA-1 manifest after BG construction, including "
            "candidates the busy 5A22 may drop; gate only producer BG invariants."
        ),
    )
    parser.add_argument(
        "--force-drop-sample",
        type=int,
        help=(
            "BG-producer lab only: force the 5A22 renderer busy across this "
            "candidate so the following candidate must reconcile a dropped image."
        ),
    )
    parser.add_argument(
        "--refresh-video-mirror",
        action="store_true",
        help=(
            "Lab only: replace the checkpoint's $7F:8000-$AFFF WRAM mirror "
            "with the selected ROM before resuming."
        ),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
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


def mismatch_summary(expected: bytes, observed: bytes) -> dict[str, object]:
    mismatches = [
        index
        for index, (left, right) in enumerate(zip(expected, observed))
        if left != right
    ]
    return {
        "expected_length": len(expected),
        "observed_length": len(observed),
        "length_match": len(expected) == len(observed),
        "mismatch_count": len(mismatches),
        "first_mismatches": [
            {
                "offset": index,
                "expected": expected[index],
                "observed": observed[index],
            }
            for index in mismatches[:16]
        ],
        "expected_sha256": hashlib.sha256(expected).hexdigest(),
        "observed_sha256": hashlib.sha256(observed).hexdigest(),
    }


def packed_x_word(sy: int, x_color: int, code_word: int) -> int | None:
    """Apply the production crop and its exact bottom credit-row translation."""
    sx = x_color & 0x01FF
    code = code_word & 0x3FFF
    credit_glyph = 0x007D <= code <= 0x0080 or code == 0x008B
    if sy == 0x0A and credit_glyph and 0x0120 <= sx < 0x0170:
        return (x_color - 0x0030) & 0xFFFF
    if 0x0031 <= sx < 0x0140:
        return x_color
    return None


def derive_source_records(m: McpSession) -> tuple[bytes, list[int]]:
    """Rebuild the exact ordered/capped producer result from coherent planes."""
    raw_y = bytes(m.read_memory("snesMemory", 0x413000, 0x0400))
    raw_code = bytes(m.read_memory("snesMemory", 0x414000, 0x0400))
    raw_x = bytes(m.read_memory("snesMemory", 0x414400, 0x0400))
    records = bytearray()
    offsets: list[int] = []
    for offset in range(0, 0x0400, 2):
        if not 0 < raw_y[offset + 1] < 0xF0:
            continue
        x_color = int.from_bytes(raw_x[offset : offset + 2], "big")
        code = int.from_bytes(raw_code[offset : offset + 2], "big")
        # Centered 384->256 crop begins at arcade X=64. A 16px OBJ first
        # overlaps at raw X=49. X1-001 interprets bit 8 as sign and draws a
        # second 512px-wrapped copy, so raw $100-$13F covers arcade
        # X=256..319 and is the crop's visible right side.
        packed_x = packed_x_word(raw_y[offset + 1], x_color, code)
        if packed_x is None:
            continue
        if code == 0xFFFF or code & 0x3FFF == 0:
            continue
        records.extend(raw_y[offset : offset + 2])
        records.extend(raw_code[offset : offset + 2])
        records.extend(packed_x.to_bytes(2, "big"))
        offsets.append(offset)
        if len(offsets) == 128:
            break
    return bytes(records), offsets


def validate_bg_snapshot(
    m: McpSession, *, require_consumer: bool = True
) -> dict[str, object]:
    """Prove the producer candidate/list and private 5A22 list are coherent."""
    bg_length = le16(m.read_memory("snesMemory", 0x41013A, 2))
    consumer_bg_length = le16(m.read_memory("snesMemory", 0x7E89BC, 2))
    promotable = le16(m.read_memory("snesMemory", 0x410142, 2)) == 1
    baseline_sequence = le16(m.read_memory("snesMemory", 0x410136, 2))

    live_code = bytes(m.read_memory("snesMemory", 0x414800, 0x0400))
    live_color = bytes(m.read_memory("snesMemory", 0x414C00, 0x0400))
    baseline_code = bytes(m.read_memory("snesMemory", 0x410200, 0x0400))
    baseline_color = bytes(m.read_memory("snesMemory", 0x410600, 0x0400))
    candidate_code = bytes(m.read_memory("snesMemory", 0x410A00, 0x0400))
    candidate_color = bytes(m.read_memory("snesMemory", 0x410E00, 0x0400))

    candidate_code_result = mismatch_summary(live_code, candidate_code)
    candidate_color_result = mismatch_summary(live_color, candidate_color)
    candidate_matches_live = bool(
        candidate_code_result["mismatch_count"] == 0
        and candidate_color_result["mismatch_count"] == 0
    )
    candidate_baseline_code_result = mismatch_summary(
        baseline_code, candidate_code
    )
    candidate_baseline_color_result = mismatch_summary(
        baseline_color, candidate_color
    )
    candidate_matches_baseline = bool(
        candidate_baseline_code_result["mismatch_count"] == 0
        and candidate_baseline_color_result["mismatch_count"] == 0
    )

    expected_offsets: list[int] = []
    expected_list = bytearray()
    if baseline_sequence:
        for offset in range(0, 0x0400, 2):
            if (
                live_code[offset : offset + 2]
                != baseline_code[offset : offset + 2]
                or live_color[offset : offset + 2]
                != baseline_color[offset : offset + 2]
            ):
                expected_offsets.append(offset)
                expected_list.extend(offset.to_bytes(2, "little"))

    ordinary_length = bg_length <= 0x0400 and bg_length % 2 == 0
    producer_list = (
        bytes(m.read_memory("snesMemory", 0x411A00, bg_length))
        if ordinary_length
        else b""
    )
    consumer_list = (
        bytes(m.read_memory("snesMemory", 0x7E8C00, bg_length))
        if ordinary_length and require_consumer
        else b""
    )
    expected_result = mismatch_summary(bytes(expected_list), producer_list)
    consumer_result = mismatch_summary(producer_list, consumer_list)

    if promotable:
        representation_green = candidate_matches_live
        if bg_length == 0xFFFF:
            representation_green &= baseline_sequence == 0
        elif bg_length == 0xFFFE:
            representation_green &= len(expected_list) >= 0x0100
        elif ordinary_length:
            representation_green &= bool(
                baseline_sequence != 0
                and bg_length == len(expected_list)
                and expected_result["mismatch_count"] == 0
                and (
                    not require_consumer
                    or consumer_result["mismatch_count"] == 0
                )
            )
        else:
            representation_green = False
    else:
        representation_green = bool(
            bg_length == 0
            and (baseline_sequence == 0 or candidate_matches_baseline)
        )

    result = {
        "producer_length": bg_length,
        "consumer_length": consumer_bg_length,
        "length_match": bg_length == consumer_bg_length,
        "consumer_required": require_consumer,
        "promotable": promotable,
        "baseline_sequence": baseline_sequence,
        "ordinary_length": ordinary_length,
        "expected_changed_cells": len(expected_offsets),
        "expected_offsets": expected_offsets,
        "candidate_code": candidate_code_result,
        "candidate_color": candidate_color_result,
        "candidate_matches_live": candidate_matches_live,
        "candidate_baseline_code": candidate_baseline_code_result,
        "candidate_baseline_color": candidate_baseline_color_result,
        "candidate_matches_baseline": candidate_matches_baseline,
        "producer_list": expected_result,
        "consumer_list": consumer_result,
    }
    result["green"] = bool(
        representation_green
        and (not require_consumer or result["length_match"])
    )
    return result


def validate_sample(
    m: McpSession, index: int, *, bg_producer_only: bool = False
) -> dict[str, object]:
    if bg_producer_only:
        bg_snapshot = validate_bg_snapshot(m, require_consumer=False)
        sample = {
            "index": index,
            "snes_cycles": int(m.get_cpu_state("Snes")["cycleCount"]),
            "sa1_cycles": int(m.get_cpu_state("Sa1")["cycleCount"]),
            "tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
            "halt": le16(m.read_memory("Sa1Memory", 0x004E, 2)),
            "sequence": le16(m.read_memory("snesMemory", 0x410132, 2)),
            "accepted_sequence": le16(
                m.read_memory("snesMemory", 0x410134, 2)
            ),
            "renderer_busy": le16(m.read_memory("snesWorkRam", 0x899C, 2)),
            "bg_snapshot": bg_snapshot,
        }
        sample["green"] = bool(bg_snapshot["green"] and sample["halt"] == 0)
        return sample

    encoded_length = le16(m.read_memory("snesMemory", 0x410138, 2))
    packed_length = encoded_length & 0x7FFF
    format_valid = bool(encoded_length & 0x8000)
    length_valid = packed_length <= 0x0300 and packed_length % 6 == 0
    producer_records = (
        bytes(m.read_memory("snesMemory", 0x411600, packed_length))
        if length_valid
        else b""
    )
    source_records, source_offsets = derive_source_records(m)
    source_result = mismatch_summary(source_records, producer_records)
    consumer_encoded_length = le16(m.read_memory("snesMemory", 0x7E89BA, 2))
    consumer_packed_length = consumer_encoded_length & 0x7FFF
    consumer_length_valid = (
        bool(consumer_encoded_length & 0x8000)
        and consumer_packed_length <= 0x0300
        and consumer_packed_length % 6 == 0
    )
    consumer_records = (
        bytes(m.read_memory("snesMemory", 0x7EBC00, consumer_packed_length))
        if consumer_length_valid
        else b""
    )
    record_result = mismatch_summary(producer_records, consumer_records)

    controls = {}
    for name, producer, consumer in (
        ("scroll", 0x413408, 0x7E3408),
        ("sprite", 0x413604, 0x7E3604),
    ):
        expected = bytes(m.read_memory("snesMemory", producer, 2))
        observed = bytes(m.read_memory("snesMemory", consumer, 2))
        controls[name] = {
            "expected": expected.hex(),
            "observed": observed.hex(),
            "match": expected == observed,
        }

    producer_sequence = le16(m.read_memory("snesMemory", 0x410132, 2))
    consumer_sequence = le16(m.read_memory("snesMemory", 0x7E89B8, 2))
    bg_snapshot = validate_bg_snapshot(m)
    sample = {
        "index": index,
        "snes_cycles": int(m.get_cpu_state("Snes")["cycleCount"]),
        "tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
        "halt": le16(m.read_memory("Sa1Memory", 0x0762, 2)),
        "arm": le16(m.read_memory("snesMemory", 0x410122, 2)),
        "capture_token": le16(m.read_memory("snesMemory", 0x410128, 2)),
        "encoded_length": encoded_length,
        "packed_length": packed_length,
        "consumer_encoded_length": consumer_encoded_length,
        "consumer_packed_length": consumer_packed_length,
        "record_count": len(producer_records) // 6,
        "source_record_count": len(source_offsets),
        "source_offsets": source_offsets,
        "format_valid": format_valid,
        "length_valid": length_valid,
        "consumer_length_valid": consumer_length_valid,
        "encoded_length_match": encoded_length == consumer_encoded_length,
        "sequence": {
            "producer": producer_sequence,
            "consumer": consumer_sequence,
            "match": producer_sequence == consumer_sequence,
        },
        "source_records": source_result,
        "packed_records": record_result,
        "bg_snapshot": bg_snapshot,
        "controls": controls,
    }
    sample["green"] = bool(
        format_valid
        and length_valid
        and consumer_length_valid
        and sample["encoded_length_match"]
        and source_result["length_match"]
        and source_result["mismatch_count"] == 0
        and record_result["length_match"]
        and record_result["mismatch_count"] == 0
        and all(bool(item["match"]) for item in controls.values())
        and sample["sequence"]["match"]
        and bg_snapshot["green"]
        and sample["halt"] == 0
    )
    return sample


def main() -> int:
    args = parse_args()
    if args.samples <= 0:
        raise SystemExit("--samples must be positive")
    if args.force_drop_sample is not None:
        if not args.bg_producer_only:
            raise SystemExit("--force-drop-sample requires --bg-producer-only")
        if not 1 <= args.force_drop_sample < args.samples - 1:
            raise SystemExit("--force-drop-sample must leave one sample on each side")
    rom = args.rom.resolve()
    state = args.state.resolve()
    nexen = args.nexen.resolve()
    output = args.output.resolve()
    for label, path in (("ROM", rom), ("state", state), ("Nexen", nexen)):
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"{label} missing or empty: {path}")
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")

    samples: list[dict[str, object]] = []
    interventions: list[dict[str, object]] = []
    mirror_intervention = None
    stderr_log = output / "nexen.stderr.log"
    with McpSession(
        rom=rom,
        mesen=nexen,
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=stderr_log,
    ) as m:
        m.pause()
        m.load_state(state)
        m.pause()
        if args.refresh_video_mirror:
            rom_mirror = rom.read_bytes()[
                VIDEO_FILE_BASE : VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH
            ]
            old_mirror = bytes(
                m.read_memory("snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH)
            )
            for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000):
                chunk = rom_mirror[offset : offset + 0x1000]
                m.write_memory(
                    "snesWorkRam", VIDEO_WRAM_OFFSET + offset, chunk.hex()
                )
            observed_mirror = bytes(
                m.read_memory("snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH)
            )
            if observed_mirror != rom_mirror:
                raise RuntimeError("production WRAM video mirror did not verify")
            old_ready_sequence = le16(
                m.read_memory("snesWorkRam", 0x1F1E, 2)
            )
            checkpoint_frame_ack = le16(
                m.read_memory("Sa1Memory", 0x3302, 2)
            )
            m.write_memory(
                "snesWorkRam",
                0x1F1E,
                checkpoint_frame_ack.to_bytes(2, "little").hex(),
            )
            if le16(m.read_memory("snesWorkRam", 0x1F1E, 2)) != checkpoint_frame_ack:
                raise RuntimeError("render-ready checkpoint migration did not verify")
            mirror_intervention = {
                "kind": "checkpoint_lab_wram_video_mirror_refresh",
                "length": VIDEO_WRAM_LENGTH,
                "differing_bytes": sum(
                    left != right for left, right in zip(old_mirror, rom_mirror)
                ),
                "sha256": hashlib.sha256(rom_mirror).hexdigest(),
                "render_ready_sequence": {
                    "address": "7E:1F1E",
                    "checkpoint": old_ready_sequence,
                    "normalized_to_frame_ack": checkpoint_frame_ack,
                },
            }
        m.tool(
            "set_input",
            {"port": 0, "buttons": args.input_buttons, "hold": True},
        )
        hook_address = (
            PRODUCER_BG_DONE_HOOK if args.bg_producer_only else MANIFEST_DONE_HOOK
        )
        hook_cpu = "Sa1" if args.bg_producer_only else "Snes"
        hook = m.add_exec_hook(hook_address, cpu_type=hook_cpu)
        m.drain_notifications(timeout=0.05)
        for index in range(args.samples):
            hit = m.run_until(max_frames=60, hook_handle=hook)
            m.pause()
            if (hit or {}).get("reason") != "hookFired":
                raise RuntimeError(
                    f"sample {index}: manifest DMA boundary did not fire: {hit!r}"
                )
            sample = validate_sample(
                m, index, bg_producer_only=args.bg_producer_only
            )
            samples.append(sample)
            print(json.dumps({"event": "sample", **sample}, sort_keys=True), flush=True)
            if (
                args.force_drop_sample is not None
                and index == args.force_drop_sample - 1
            ):
                old_busy = le16(m.read_memory("snesWorkRam", 0x899C, 2))
                if old_busy != 0:
                    raise RuntimeError(
                        f"renderer already busy before forced drop: {old_busy:#06x}"
                    )
                m.write_memory("snesWorkRam", 0x899C, "0100")
                interventions.append(
                    {
                        "after_sample": index,
                        "kind": "force_renderer_busy_for_one_candidate",
                        "address": "7E:899C",
                        "old": old_busy,
                        "new": 1,
                        "target_sample": args.force_drop_sample,
                    }
                )
            if (
                args.force_drop_sample is not None
                and index == args.force_drop_sample + 1
            ):
                old_busy = le16(m.read_memory("snesWorkRam", 0x899C, 2))
                if old_busy != 1:
                    raise RuntimeError(
                        f"forced renderer-busy marker changed early: {old_busy:#06x}"
                    )
                m.write_memory("snesWorkRam", 0x899C, "0000")
                interventions.append(
                    {
                        "after_sample": index,
                        "kind": "release_forced_renderer_busy",
                        "address": "7E:899C",
                        "old": old_busy,
                        "new": 0,
                        "target_sample": args.force_drop_sample,
                    }
                )

    all_green = all(bool(sample["green"]) for sample in samples)
    summary = {
        "scope": (
            "checkpointed every-candidate SA-1 BG producer invariants; not fps"
            if args.bg_producer_only
            else "checkpointed compact OBJ/BG DMA equivalence; not fps"
        ),
        "result": "green" if all_green else "red",
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--porcelain=v1").splitlines(),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(state),
        "state_sha256": sha256(state),
        "nexen": str(nexen),
        "nexen_sha256": sha256(nexen),
        "hook": f"{hook_address:06X}",
        "hook_cpu": hook_cpu,
        "bg_producer_only": args.bg_producer_only,
        "interventions": interventions,
        "input_buttons": args.input_buttons,
        "input_transport": "nexen_port0_manual_4016",
        "mirror_intervention": mirror_intervention,
        "sample_count": len(samples),
        "green_count": sum(bool(sample["green"]) for sample in samples),
        "samples": samples,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "event": "summary",
                "result": summary["result"],
                "samples": summary["sample_count"],
                "summary": str(output / "summary.json"),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if all_green else 2


if __name__ == "__main__":
    raise SystemExit(main())
