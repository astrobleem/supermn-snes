#!/usr/bin/env python3
"""Qualify source symbols used to hook an active production ROM.

The native-entry tracer installs hooks at addresses read from the current
``src/escbank*.sym`` files, but the authoritative production ROM is packed
separately.  In particular, bank $9F begins at $A100 rather than $8000 and
production removes validation-counter instructions.  This reducer proves the
addresses that actually fired in a retained trace still resolve to the source
payload, while treating those two counter removals as explicitly allowed
packing changes.  It is deliberately narrow: it does not claim the complete
ROM was rebuilt from this source, nor that unobserved symbols are aligned.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE = (
    ROOT
    / "build"
    / "trace-stage3-all-native-entries-current-a976-safe14743-v1"
    / "trace.json"
)
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_SOURCE = ROOT / "src"
ACTIVE_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"
ENTRY = re.compile(r"^(?P<label>.+)@(?P<address>[0-9A-F]{6})$")


@dataclass(frozen=True)
class PackedBank:
    source_name: str
    rom_bank_base: int
    source_origin: int


# ``rom_bank_base`` is the start of the full logical 32 KiB SA-1 bank.  The
# escbank9 binary itself starts at $A100, but is packed at the corresponding
# $2F:A100 address—not at byte zero of its source artifact.
PACKED_BANKS = {
    0x92: PackedBank("escbank.bin", 0x290000, 0x8000),
    0x94: PackedBank("escbank2.bin", 0x2A0000, 0x8000),
    0x95: PackedBank("escbank6.bin", 0x2A8000, 0x8000),
    0x97: PackedBank("escbank3.bin", 0x2B8000, 0x8000),
    0x98: PackedBank("escbank4.bin", 0x2C0000, 0x8000),
    0x99: PackedBank("escbank5.bin", 0x2C8000, 0x8000),
    0x9D: PackedBank("escbank7.bin", 0x2E0000, 0x8000),
    0x9E: PackedBank("escbank8.bin", 0x2F0000, 0x8000),
    0x9F: PackedBank("escbank9.bin", 0x2F8000, 0xA100),
}

# The ordinary production pack replaces these source-only counter updates with
# a same-size branch/NOP sequence.  Keep source and production byte sequences
# here so a different change cannot be accidentally blessed as a counter skip.
APPROVED_PRODUCTION_PATCHES = {
    0x94AB06: (bytes.fromhex("ad30071a8d3007"), bytes.fromhex("8005eaeaeaeaea")),
    0x978002: (bytes.fromhex("ad2a071a8d2a07"), bytes.fromhex("8005eaeaeaeaea")),
}


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.window < 4:
        parser.error("--window must be at least four bytes")
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    return args


def source_slice(
    source: bytes, bank: PackedBank, address: int, length: int
) -> bytes | None:
    offset = (address & 0xFFFF) - bank.source_origin
    if offset < 0 or offset + length > len(source):
        return None
    return source[offset : offset + length]


def rom_offset(bank: PackedBank, address: int) -> int:
    return bank.rom_bank_base + ((address & 0xFFFF) - 0x8000)


def production_expected(source: bytes, bank: PackedBank, address: int, length: int) -> tuple[bytes, list[str]] | None:
    expected = source_slice(source, bank, address, length)
    if expected is None:
        return None
    patched = bytearray(expected)
    applied: list[str] = []
    for patch_address, (source_bytes, production_bytes) in APPROVED_PRODUCTION_PATCHES.items():
        start = max(address, patch_address)
        end = min(address + length, patch_address + len(source_bytes))
        if start >= end:
            continue
        source_start = patch_address - address
        patch_start = start - patch_address
        patch_end = end - patch_address
        if expected[start - address : end - address] != source_bytes[patch_start:patch_end]:
            return None
        patched[start - address : end - address] = production_bytes[patch_start:patch_end]
        applied.append(f"${patch_address:06X}")
    return bytes(patched), applied


def main() -> int:
    args = parse_args()
    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    rom = args.rom.read_bytes()
    rom_sha256 = digest(args.rom)
    trace_sha256 = digest(args.trace)
    source_cache = {
        item.source_name: (args.source / item.source_name).read_bytes()
        for item in PACKED_BANKS.values()
    }
    rows: list[dict[str, Any]] = []
    ignored: list[str] = []
    for key, raw_count in sorted(trace.get("event_counts", {}).items()):
        count = int(raw_count)
        match = ENTRY.fullmatch(str(key))
        if count == 0 or match is None:
            if count:
                ignored.append(str(key))
            continue
        address = int(match.group("address"), 16)
        bank_number = address >> 16
        bank = PACKED_BANKS.get(bank_number)
        if bank is None or (address & 0xFFFF) < 0x8000:
            rows.append(
                {
                    "count": count,
                    "entry": key,
                    "address": f"${address:06X}",
                    "classification": "unmapped-source-bank",
                }
            )
            continue
        source = source_cache[bank.source_name]
        expected_result = production_expected(source, bank, address, args.window)
        active_start = rom_offset(bank, address)
        actual = rom[active_start : active_start + args.window]
        if expected_result is None or len(actual) != args.window:
            rows.append(
                {
                    "count": count,
                    "entry": key,
                    "address": f"${address:06X}",
                    "classification": "source-or-rom-window-unavailable",
                }
            )
            continue
        expected, approved_patches = expected_result
        direct = source_slice(source, bank, address, args.window)
        if actual == direct:
            classification = "exact-source-bytes"
        elif actual == expected and approved_patches:
            classification = "approved-production-counter-strip"
        else:
            classification = "unapproved-byte-mismatch"
        rows.append(
            {
                "count": count,
                "entry": key,
                "address": f"${address:06X}",
                "source": bank.source_name,
                "rom_offset": f"${active_start:06X}",
                "actual": actual.hex(),
                "source_bytes": direct.hex() if direct is not None else None,
                "expected_production_bytes": expected.hex(),
                "approved_patches": approved_patches,
                "classification": classification,
            }
        )

    classification_counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}
    for row in rows:
        kind = str(row["classification"])
        classification_counts[kind] = classification_counts.get(kind, 0) + 1
        event_counts[kind] = event_counts.get(kind, 0) + int(row["count"])
    checks = {
        "active_rom_is_accepted_a976": rom_sha256 == ACTIVE_SHA256,
        "trace_declares_this_active_rom": trace.get("rom_sha256") == rom_sha256,
        "all_observed_source_labels_resolve": set(ignored).issubset(
            {"player_x_high_write", "player_x_low_write"}
        )
        and all(
            row["classification"]
            in ("exact-source-bytes", "approved-production-counter-strip")
            for row in rows
        ),
        "observed_entry_event_count_is_retained": sum(int(row["count"]) for row in rows) == 240,
        "approved_counter_strips_are_exactly_the_two_known_sites": {
            row["address"]
            for row in rows
            if row["classification"] == "approved-production-counter-strip"
        } == {"$94AB04", "$978000"},
    }
    report = {
        "scope": (
            "one retained Stage-3 tick's non-pausing native-entry hook addresses "
            "against the active production-ROM pack; source-symbol alignment only, "
            "not a full-source rebuild, gameplay result, or timing repair"
        ),
        "trace": str(args.trace.resolve()),
        "trace_sha256": trace_sha256,
        "rom": str(args.rom.resolve()),
        "rom_sha256": rom_sha256,
        "source_directory": str(args.source.resolve()),
        "source_sha256": {
            name: digest(args.source / name)
            for name in sorted(source_cache)
        },
        "window_bytes": args.window,
        "entries": rows,
        "ignored_nonentry_events": ignored,
        "classification_labels": classification_counts,
        "classification_events": event_counts,
        "checks": checks,
        "not_proven": [
            "unobserved native symbols or complete source-to-ROM identity",
            "the independently packed $9D or $95 bank payloads",
            "scheduler basic-block timing or virtual IRQ repair",
            "Stage-3 rate, renderer alignment, or a full playthrough",
        ],
        "result": "green" if all(checks.values()) else "red",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"result": report["result"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
