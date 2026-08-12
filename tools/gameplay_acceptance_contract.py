#!/usr/bin/env python3
"""Shared machine-enforced gameplay acceptance contract.

Only the aggregate gate may issue a gameplay-level green result.  Diagnostic
tools and individual oracles may describe their bounded result, but missing
state, exact-MAME pixels, or intervening-frame conservation is UNKNOWN.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = 1
REQUIRED_GATES = (
    "state_oracle",
    "aligned_pixel_oracle",
    "temporal_conservation",
)
STATUSES = {"green", "red", "unknown"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def tick_coverage(start: int, end: int, complete: bool) -> dict[str, Any]:
    return {
        "game_tick_start": int(start),
        "game_tick_end": int(end),
        "complete": bool(complete),
    }


def gate(
    kind: str,
    status: str,
    rom_sha256: str | None,
    coverage: dict[str, Any] | None,
    *,
    authority: str,
    reason: str | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"invalid acceptance status: {status}")
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": kind,
        "status": status,
        "authority": authority,
        "rom_sha256": rom_sha256,
        "coverage": coverage,
    }
    if reason is not None:
        result["reason"] = reason
    return result


def unknown_diagnostic_gate(kind: str, reason: str) -> dict[str, Any]:
    return gate(
        kind,
        "unknown",
        None,
        None,
        authority="diagnostic_only",
        reason=reason,
    )


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("report root must be an object")
    return value


def validate_requested_coverage(
    value: Any, *, require_complete: bool = True
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(value, dict):
        return ["coverage_missing"]
    start = value.get("game_tick_start")
    end = value.get("game_tick_end")
    if not isinstance(start, int) or not isinstance(end, int) or start > end:
        reasons.append("coverage_tick_range_invalid")
    if require_complete and value.get("complete") is not True:
        reasons.append("coverage_not_complete")
    return reasons


def validate_gate(
    value: Any,
    expected_kind: str,
    rom_sha256: str,
    coverage: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(value, dict):
        return ["acceptance_gate_missing"]
    if value.get("schema") != SCHEMA:
        reasons.append("acceptance_gate_schema_invalid")
    if value.get("kind") != expected_kind:
        reasons.append("acceptance_gate_kind_mismatch")
    if value.get("status") not in STATUSES:
        reasons.append("acceptance_gate_status_invalid")
    if value.get("rom_sha256") != rom_sha256:
        reasons.append("acceptance_gate_rom_mismatch")
    gate_coverage = value.get("coverage")
    status = value.get("status")
    reasons.extend(
        validate_requested_coverage(
            gate_coverage, require_complete=(status == "green")
        )
    )
    if isinstance(gate_coverage, dict):
        for field in ("game_tick_start", "game_tick_end"):
            if gate_coverage.get(field) != coverage.get(field):
                reasons.append(f"acceptance_gate_{field}_mismatch")
    return sorted(set(reasons))
