#!/usr/bin/env python3
"""Validate compact production OBJ/BG snapshots at the 5A22 capture boundary.

This is a checkpointed representation-equivalence gate, not an end-to-end
performance measurement.  It pauses at the common direct/queued capture join,
while the SA-1 still owns a stable game boundary.  The bit-15 tag, byte length,
packed Y/code/X records, and the two control words displaced from the former
raw-plane DMA must match both the source planes and the selected private capture
exactly.
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
# $7F:8E7B is ptw_snapshot_busy, the first common instruction after a direct
# snapshot, primary queue capture, secondary queue capture, or explicit full-
# queue drop.  The old $7F:A665 compact-DMA return stopped firing after the
# production renderer gained compressed busy-frame queues.
SNAPSHOT_DECISION_HOOK = 0x7F8E7B
PRODUCER_BG_DONE_HOOK = 0x9EDDF6
VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000
CAPTURE_LAYOUTS = {
    "direct": {
        "sequence": 0x7E89B8,
        "obj_length": 0x7E89BA,
        "obj_records": 0x7EBC00,
        "bg_length": 0x7E89BC,
        "bg_list": 0x7E8C00,
        "bg_payload": 0x7E2000,
        "prepared_payload": 0x7E9000,
        "prep_length": 0x7E89C4,
        "scroll": 0x7E3408,
        "column_kind": 0x7E3604,
        "column_map": 0x7E3606,
        "state": None,
    },
    "primary_queue": {
        "sequence": 0x7ED180,
        "obj_length": 0x7ED182,
        "obj_records": 0x7ED5A0,
        "bg_length": 0x7ED184,
        "bg_list": 0x7EE0A0,
        "bg_payload": 0x7ED8A0,
        "prepared_payload": 0x7ED8A0,
        "prep_length": 0x7ED188,
        "scroll": 0x7ED18C,
        "column_kind": 0x7ED18E,
        "column_map": 0x7ED190,
        "state": 0x7E89D2,
    },
    "secondary_queue": {
        "sequence": 0x7EB000,
        "obj_length": 0x7EB002,
        "obj_records": 0x7EB420,
        "bg_length": 0x7EB004,
        "bg_list": 0x7EB720,
        "bg_payload": None,
        "prepared_payload": None,
        "prep_length": 0x7EB008,
        "scroll": 0x7EB00C,
        "column_kind": 0x7EB00E,
        "column_map": 0x7EB010,
        "state": 0x7E89D6,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument(
        "--max-frames-per-sample",
        type=int,
        default=60,
        help="Maximum emulator frames to wait for each selected boundary.",
    )
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


def packed_x_word(
    sy: int,
    x_color: int,
    code_word: int,
    source_offset: int | None = None,
) -> int | None:
    """Apply the production crop and its exact HUD-only translations."""
    sx = x_color & 0x01FF
    code = code_word & 0x3FFF
    if source_offset is not None:
        if sy == 0x0A and (
            source_offset == 0x0004
            or 0x0048 <= source_offset < 0x0072
        ):
            # Slot 2 and slot 36 are solid-black CREDIT-digit spacers which
            # erase live art in the centered crop.  Slots 37-56 hold the
            # adjacent bottom-status allocations.  Suppress only those exact
            # records on their proven row.
            return None
        if sy == 0x1A and 0x006A <= source_offset < 0x0072:
            # The adjacent ROUND field begins at raw X=$138.  Its first
            # 16x16 record otherwise leaks half an "R" at the right edge.
            return None
    if sy in (0xE2, 0xF2) and code == 0x0020:
        # The source uses a completely transparent tile as a HUD spacer.
        # Keeping it as an OBJ can exceed the SNES 34-tile scanline limit.
        return None
    if sy in (0xE2, 0xF2):
        if sx < 0x0040:
            return (x_color + 0x0030) & 0xFFFF
        if 0x0120 <= sx < 0x0170:
            return (x_color - 0x0030) & 0xFFFF
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
    title_overlay = bool(le16(m.read_memory("snesMemory", 0x410150, 2)))
    records = bytearray()
    offsets: list[int] = []
    for offset in range(0, 0x0400, 2):
        # The arcade coordinate maps $F0-$F2 to visible SNES rows 2..0.
        # $F3 would map above the top edge; $FA remains the hidden sentinel.
        if not 0 < raw_y[offset + 1] < 0xF3:
            continue
        if (
            title_overlay
            and 0x1A <= raw_y[offset + 1] < 0x70
            and raw_y[offset + 1] & 0x0F == 0x0A
        ):
            continue
        x_color = int.from_bytes(raw_x[offset : offset + 2], "big")
        code = int.from_bytes(raw_code[offset : offset + 2], "big")
        # Centered 384->256 crop begins at arcade X=64. A 16px OBJ first
        # overlaps at raw X=49. X1-001 interprets bit 8 as sign and draws a
        # second 512px-wrapped copy, so raw $100-$13F covers arcade
        # X=256..319 and is the crop's visible right side.
        packed_x = packed_x_word(
            raw_y[offset + 1], x_color, code, source_offset=offset
        )
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


def packed_record_words(records: bytes) -> list[dict[str, int]]:
    """Retain the logical contents of each six-byte packed OBJ record."""
    if len(records) % 6:
        raise ValueError("packed OBJ records are not six-byte aligned")
    result: list[dict[str, int]] = []
    for offset in range(0, len(records), 6):
        code_word = int.from_bytes(
            records[offset + 2 : offset + 4], "big"
        )
        result.append(
            {
                "y_word": int.from_bytes(
                    records[offset : offset + 2], "big"
                ),
                "sy": records[offset + 1],
                "code_word": code_word,
                "code": code_word & 0x3FFF,
                "x_color_word": int.from_bytes(
                    records[offset + 4 : offset + 6], "big"
                ),
            }
        )
    return result


def expected_packed_scroll(m: McpSession) -> bytes:
    """Reproduce capture_bg_vscroll's packed VOFS/scroll-X control word."""
    scroll_x_low = m.read_memory("snesMemory", 0x413409, 1)[0]
    representative_vscroll = m.read_memory(
        "snesMemory", 0x413481, 1
    )[0]
    return bytes(((representative_vscroll + 7) & 0xFF, scroll_x_low))


def derive_bg_column_capture(
    raw: bytes, bg_code: bytes | None = None
) -> tuple[int, bytes]:
    """Rebuild capture_bg_upper_full's layout kind and 16-byte column map."""
    if len(raw) != 0x0208:
        raise ValueError(f"expected $0208 X1 control bytes, got {len(raw):#x}")
    if bg_code is not None and len(bg_code) != 0x0400:
        raise ValueError(f"expected $0400 BG code bytes, got {len(bg_code):#x}")

    upper_mask = raw[0x0205] | (raw[0x0207] << 8)
    shifted_mask = upper_mask
    column_map = bytearray()
    for column in range(16):
        slot = raw[0x0009 + column * 0x20] >> 5
        if shifted_mask & 1:
            slot |= 0x08
        column_map.append(slot)
        shifted_mask >>= 1

    full_columns = raw[0x0201] & 0x03 == 0 and raw[0x0203] & 0x0F == 1
    regular = full_columns
    if regular and upper_mask & 0xC000 != 0xC000:
        low = upper_mask & 0xFF
        high = upper_mask >> 8
        regular = high == ((~low) & 0xFF)
    if regular and upper_mask & 0xC000 != 0xC000:
        expected_x = raw[0x0009]
        for column in range(1, 16):
            expected_x = (expected_x + 0x20) & 0xFF
            if raw[0x0009 + column * 0x20] != expected_x:
                regular = False
                break

    # A non-sequential full-column layout is still exact when every true X
    # shares one sub-32-pixel phase.  The SNES offset table can then reproduce
    # the captured physical-slot ordering (and source-order overlaps) while a
    # single BG1HOFS supplies the common fine phase.  Only genuinely
    # phase-irregular compositions require the legacy identity approximation.
    occupied = list(range(16))
    if bg_code is not None:
        occupied = []
        for column in range(16):
            start = column * 0x40
            words = (
                int.from_bytes(bg_code[offset : offset + 2], "big")
                for offset in range(start, start + 0x40, 2)
            )
            if any(word & 0x3FFF for word in words):
                occupied.append(column)
    aligned_permutation = full_columns and (
        not occupied
        or len(
            {
                raw[0x0009 + column * 0x20] & 0x1F
                for column in occupied
            }
        ) == 1
    )
    exact = regular or aligned_permutation
    kind = upper_mask if exact else 0xFFFE | (upper_mask & 1)
    return kind, bytes(column_map)


def prepared_requires_remap(
    bg_length: int,
    column_kind: int,
    column_map: bytes,
) -> bool:
    """Return whether an identity-order prepared map needs X1 placement."""
    if len(column_map) != 16:
        raise ValueError(f"expected 16 column slots, got {len(column_map)}")
    return bool(
        bg_length == 0xFFFE
        and column_kind < 0xFFFE
        and column_map != bytes(range(16))
    )


def bg_layout_requires_rebuild(
    previous_kind: int,
    previous_map: bytes,
    current_kind: int,
    current_map: bytes,
) -> bool:
    """Mirror the renderer's geometry-change decision.

    The kind retains the X1 upper-position mask for live scroll handling, but
    the sixteen physical slots are the complete tile-placement contract.
    Therefore a kind-only change must not force a full tilemap reconstruction.
    """
    if not 0 <= previous_kind <= 0xFFFF:
        raise ValueError(f"invalid previous layout kind: {previous_kind:#x}")
    if not 0 <= current_kind <= 0xFFFF:
        raise ValueError(f"invalid current layout kind: {current_kind:#x}")
    if len(previous_map) != 16 or len(current_map) != 16:
        raise ValueError("expected two 16-byte column maps")
    return previous_map != current_map


def remap_prepared_tilemap(
    payload: bytes,
    column_map: bytes,
) -> bytes:
    """Mirror the private 64x32 prepared-map source-order remap."""
    if len(payload) != 0x1000:
        raise ValueError(
            f"expected a 4096-byte prepared map, got {len(payload)}"
        )
    if len(column_map) != 16:
        raise ValueError(f"expected 16 column slots, got {len(column_map)}")
    output = bytearray(0x1000)
    for row in range(32):
        for source in range(16):
            source_offset = (
                row * 0x40
                + (source & 7) * 8
                + (0x0800 if source & 8 else 0)
            )
            destination = column_map[source]
            destination_offset = (
                row * 0x40
                + (destination & 7) * 8
                + (0x0800 if destination & 8 else 0)
            )
            for byte_offset in range(0, 8, 2):
                word = payload[
                    source_offset + byte_offset:
                    source_offset + byte_offset + 2
                ]
                # X1 tile word zero is transparent.  A later empty source
                # sharing the same physical column must not erase an earlier
                # nonempty tile.
                if word != b"\x00\x00":
                    output[
                        destination_offset + byte_offset:
                        destination_offset + byte_offset + 2
                    ] = word
    return bytes(output)


def validate_bg_snapshot(
    m: McpSession,
    *,
    require_consumer: bool = True,
    consumer_bg_length_address: int = 0x7E89BC,
    consumer_list_address: int = 0x7E8C00,
    consumer_payload_address: int | None = 0x7E2000,
    consumer_prepared_payload_address: int | None = 0x7E9000,
    consumer_prep_length_address: int | None = 0x7E89C4,
    consumer_column_kind: int | None = None,
    consumer_column_map: bytes | None = None,
) -> dict[str, object]:
    """Prove the producer candidate/list and private 5A22 capture are coherent.

    A $FFFE prepared payload is captured in producer source-column order.
    Geometry remapping happens later, after foreground promotion, so this
    capture-boundary gate must not compare against the remapped display image.
    """
    bg_length = le16(m.read_memory("snesMemory", 0x41013A, 2))
    consumer_bg_length = le16(
        m.read_memory("snesMemory", consumer_bg_length_address, 2)
    )
    promotable = le16(m.read_memory("snesMemory", 0x410142, 2)) == 1
    baseline_sequence = le16(m.read_memory("snesMemory", 0x410136, 2))
    producer_prep_length = le16(
        m.read_memory("snesMemory", 0x410146, 2)
    )
    producer_c0bc_provenance = le16(
        m.read_memory("snesMemory", 0x41014A, 2)
    )

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
        bytes(m.read_memory("snesMemory", consumer_list_address, bg_length))
        if ordinary_length and require_consumer
        else b""
    )
    expected_result = mismatch_summary(bytes(expected_list), producer_list)
    consumer_result = mismatch_summary(producer_list, consumer_list)
    prep_length = (
        None
        if not require_consumer or consumer_prep_length_address is None
        else le16(
            m.read_memory(
                "snesMemory", consumer_prep_length_address, 2
            )
        )
    )
    foreground_remap_required = bool(
        require_consumer
        and consumer_column_kind is not None
        and consumer_column_map is not None
        and prepared_requires_remap(
            bg_length,
            consumer_column_kind,
            consumer_column_map,
        )
    )
    length_match = bool(bg_length == consumer_bg_length)

    private_payload_result: dict[str, object] | None = None
    private_payload_match = True
    if require_consumer and consumer_bg_length == 0xFFFF:
        if consumer_payload_address is None:
            private_payload_match = False
        else:
            expected_payload = live_code + live_color
            observed_payload = bytes(
                m.read_memory(
                    "snesMemory", consumer_payload_address, 0x0800
                )
            )
            private_payload_result = mismatch_summary(
                expected_payload, observed_payload
            )
            private_payload_match = bool(
                private_payload_result["mismatch_count"] == 0
            )
    elif require_consumer and consumer_bg_length == 0xFFFE:
        if consumer_prepared_payload_address is None:
            private_payload_match = False
        else:
            # Direct and queued captures both retain the producer's canonical
            # source-column order. bg_column_map_update remaps only after the
            # selected capture reaches the foreground renderer.
            expected_payload = bytes(
                m.read_memory("snesMemory", 0x418000, 0x1000)
            )
            observed_payload = bytes(
                m.read_memory(
                    "snesMemory",
                    consumer_prepared_payload_address,
                    0x1000,
                )
            )
            private_payload_result = mismatch_summary(
                expected_payload,
                observed_payload,
            )
            private_payload_match = bool(
                private_payload_result["mismatch_count"] == 0
            )

    prepared_metadata_green = bool(
        producer_prep_length <= 0x0180
        and producer_prep_length % 2 == 0
        and (
            producer_c0bc_provenance != 0xC0BC
            or producer_prep_length == 0x005A
        )
    )
    prepared_length_match = bool(
        not require_consumer
        or consumer_bg_length != 0xFFFE
        or prep_length == producer_prep_length
    )

    if promotable:
        representation_green = candidate_matches_live
        if bg_length == 0xFFFF:
            representation_green &= baseline_sequence == 0
        elif bg_length == 0xFFFE:
            representation_green &= bool(
                len(expected_list) >= 0x0100
                and prepared_metadata_green
            )
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
        "length_match": length_match,
        "consumer_required": require_consumer,
        "prepared_capture_order": "producer-source-columns",
        "prepared_foreground_remap_required": foreground_remap_required,
        # Retain the old field names for result readers while making their
        # capture-boundary meaning explicit: remapping is pending, not failed.
        "prepared_remap_expected": foreground_remap_required,
        "prepared_remap_applied": False,
        "producer_prep_length": producer_prep_length,
        "producer_c0bc_provenance": producer_c0bc_provenance,
        "consumer_prep_length": prep_length,
        "prepared_length_match": prepared_length_match,
        "prepared_metadata_green": prepared_metadata_green,
        "private_payload": private_payload_result,
        "private_payload_match": private_payload_match,
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
        and (
            not require_consumer
            or (
                result["length_match"]
                and prepared_length_match
                and private_payload_match
            )
        )
    )
    return result


def select_capture_layout(
    m: McpSession,
) -> tuple[str, dict[str, int | None]] | None:
    """Identify which complete private image represents the current candidate."""
    producer_sequence = le16(m.read_memory("snesMemory", 0x410132, 2))
    for name in ("primary_queue", "secondary_queue"):
        layout = CAPTURE_LAYOUTS[name]
        state_address = layout["state"]
        assert state_address is not None
        if (
            le16(m.read_memory("snesMemory", state_address, 2)) == 1
            and le16(m.read_memory("snesMemory", layout["sequence"], 2))
            == producer_sequence
        ):
            return name, layout

    direct = CAPTURE_LAYOUTS["direct"]
    if (
        le16(m.read_memory("snesMemory", direct["sequence"], 2))
        == producer_sequence
    ):
        return "direct", direct
    return None


def dropped_candidate(m: McpSession, attempt: int) -> dict[str, object]:
    """Retain an explicit full-queue decision without treating it as a sample."""
    return {
        "attempt": attempt,
        "tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
        "arm": le16(m.read_memory("snesMemory", 0x410122, 2)),
        "renderer_busy": le16(m.read_memory("snesMemory", 0x7E899C, 2)),
        "producer_sequence": le16(
            m.read_memory("snesMemory", 0x410132, 2)
        ),
        "accepted_sequence": le16(
            m.read_memory("snesMemory", 0x410134, 2)
        ),
        "direct_sequence": le16(
            m.read_memory("snesMemory", 0x7E89B8, 2)
        ),
        "primary": {
            "state": le16(m.read_memory("snesMemory", 0x7E89D2, 2)),
            "sequence": le16(m.read_memory("snesMemory", 0x7ED180, 2)),
        },
        "secondary": {
            "state": le16(m.read_memory("snesMemory", 0x7E89D6, 2)),
            "sequence": le16(m.read_memory("snesMemory", 0x7EB000, 2)),
        },
        "queue_drop_counter": le16(
            m.read_memory("snesMemory", 0x7E89D4, 2)
        ),
    }


def validate_sample(
    m: McpSession,
    index: int,
    *,
    bg_producer_only: bool = False,
    capture_name: str | None = None,
    capture_layout: dict[str, int | None] | None = None,
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

    if capture_name is None or capture_layout is None:
        raise ValueError("snapshot sample requires a selected capture layout")

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
    consumer_encoded_length = le16(
        m.read_memory(
            "snesMemory",
            int(capture_layout["obj_length"]),
            2,
        )
    )
    consumer_packed_length = consumer_encoded_length & 0x7FFF
    consumer_length_valid = (
        bool(consumer_encoded_length & 0x8000)
        and consumer_packed_length <= 0x0300
        and consumer_packed_length % 6 == 0
    )
    consumer_records = (
        bytes(
            m.read_memory(
                "snesMemory",
                int(capture_layout["obj_records"]),
                consumer_packed_length,
            )
        )
        if consumer_length_valid
        else b""
    )
    record_result = mismatch_summary(producer_records, consumer_records)

    expected_scroll = expected_packed_scroll(m)
    observed_scroll = bytes(
        m.read_memory("snesMemory", int(capture_layout["scroll"]), 2)
    )
    raw_x1 = bytes(m.read_memory("snesMemory", 0x413400, 0x0208))
    bg_code = bytes(m.read_memory("snesMemory", 0x414800, 0x0400))
    expected_column_kind, expected_column_map = derive_bg_column_capture(
        raw_x1, bg_code
    )
    observed_column_kind = le16(
        m.read_memory(
            "snesMemory",
            int(capture_layout["column_kind"]),
            2,
        )
    )
    observed_column_map = bytes(
        m.read_memory(
            "snesMemory",
            int(capture_layout["column_map"]),
            16,
        )
    )
    controls = {
        "scroll": {
            "expected": expected_scroll.hex(),
            "observed": observed_scroll.hex(),
            "match": expected_scroll == observed_scroll,
        },
        "bg_columns": {
            "expected_kind": expected_column_kind,
            "observed_kind": observed_column_kind,
            "kind_match": expected_column_kind == observed_column_kind,
            "expected_map": expected_column_map.hex(),
            "observed_map": observed_column_map.hex(),
            "map_match": expected_column_map == observed_column_map,
            "match": bool(
                expected_column_kind == observed_column_kind
                and expected_column_map == observed_column_map
            ),
        },
    }

    producer_sequence = le16(m.read_memory("snesMemory", 0x410132, 2))
    consumer_sequence = le16(
        m.read_memory(
            "snesMemory",
            int(capture_layout["sequence"]),
            2,
        )
    )
    bg_snapshot = validate_bg_snapshot(
        m,
        consumer_bg_length_address=int(capture_layout["bg_length"]),
        consumer_list_address=int(capture_layout["bg_list"]),
        consumer_payload_address=(
            None
            if capture_layout["bg_payload"] is None
            else int(capture_layout["bg_payload"])
        ),
        consumer_prepared_payload_address=(
            None
            if capture_layout["prepared_payload"] is None
            else int(capture_layout["prepared_payload"])
        ),
        consumer_prep_length_address=(
            None
            if capture_layout["prep_length"] is None
            else int(capture_layout["prep_length"])
        ),
        consumer_column_kind=observed_column_kind,
        consumer_column_map=observed_column_map,
    )
    sample = {
        "index": index,
        "capture_kind": capture_name,
        "capture_state": (
            None
            if capture_layout["state"] is None
            else le16(
                m.read_memory(
                    "snesMemory",
                    int(capture_layout["state"]),
                    2,
                )
            )
        ),
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
        "record_words": packed_record_words(producer_records),
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
    if args.max_frames_per_sample <= 0:
        raise SystemExit("--max-frames-per-sample must be positive")
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
    executable_name = nexen.name.lower()
    exact_mesen = "mesen" in executable_name
    if exact_mesen:
        runtime = "/home/chad/.dotnet8"
        alternate = "/home/chad/.dotnet10"
    else:
        runtime = "/home/chad/.dotnet10"
        alternate = "/home/chad/.dotnet8"
    os.environ["DOTNET_ROOT"] = runtime
    current_path = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (runtime, alternate)
    ]
    os.environ["PATH"] = ":".join([runtime, alternate, *current_path])

    samples: list[dict[str, object]] = []
    skipped_candidates: list[dict[str, object]] = []
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
        if exact_mesen:
            if args.input_buttons:
                raise RuntimeError(
                    "exact-Mesen checkpoint equivalence currently supports "
                    "only neutral input"
                )
        else:
            m.tool(
                "set_input",
                {"port": 0, "buttons": args.input_buttons, "hold": True},
            )
        hook_address = (
            PRODUCER_BG_DONE_HOOK
            if args.bg_producer_only
            else SNAPSHOT_DECISION_HOOK
        )
        hook_cpu = "Sa1" if args.bg_producer_only else "Snes"
        hook = m.add_exec_hook(hook_address, cpu_type=hook_cpu)
        m.drain_notifications(timeout=0.05)
        attempts = 0
        max_attempts = max(args.samples * 64, 64)
        while len(samples) < args.samples:
            attempts += 1
            if attempts > max_attempts:
                raise RuntimeError(
                    "too many full-queue decisions while waiting for "
                    f"{args.samples} complete captures"
                )
            hit = m.run_until(
                max_frames=args.max_frames_per_sample,
                hook_handle=hook,
            )
            m.pause()
            if (hit or {}).get("reason") != "hookFired":
                raise RuntimeError(
                    f"attempt {attempts}: snapshot boundary did not fire: {hit!r}"
                )
            capture_name = None
            capture_layout = None
            if not args.bg_producer_only:
                selected = select_capture_layout(m)
                if selected is None:
                    skipped = dropped_candidate(m, attempts)
                    skipped_candidates.append(skipped)
                    print(
                        json.dumps(
                            {"event": "full_queue_drop", **skipped},
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                    continue
                capture_name, capture_layout = selected
            index = len(samples)
            sample = validate_sample(
                m,
                index,
                bg_producer_only=args.bg_producer_only,
                capture_name=capture_name,
                capture_layout=capture_layout,
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
        "input_transport": (
            "exact_mesen_default_neutral"
            if exact_mesen
            else "nexen_port0_manual_4016"
        ),
        "mirror_intervention": mirror_intervention,
        "sample_count": len(samples),
        "green_count": sum(bool(sample["green"]) for sample in samples),
        "capture_counts": {
            name: sum(sample.get("capture_kind") == name for sample in samples)
            for name in CAPTURE_LAYOUTS
        },
        "full_queue_drop_count": len(skipped_candidates),
        "full_queue_drops": skipped_candidates,
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
