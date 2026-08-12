#!/usr/bin/env python3
"""Regression tests for the mandatory three-oracle aggregate gate."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from gameplay_acceptance_contract import gate, tick_coverage


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/validate_gameplay_acceptance.py"
ROM_SHA = "1" * 64


def run(manifest: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(TOOL), "--manifest", str(manifest), "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def write_gate(path: Path, kind: str, status: str, rom: str = ROM_SHA) -> None:
    path.write_text(
        json.dumps(
            {
                "acceptance_gate": gate(
                    kind,
                    status,
                    rom,
                    tick_coverage(10, 12, complete=(status == "green")),
                    authority="test",
                )
            }
        ),
        encoding="utf-8",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="gameplay-acceptance-test-") as raw:
        temp = Path(raw)
        reports = {
            kind: temp / f"{kind}.json"
            for kind in (
                "state_oracle",
                "aligned_pixel_oracle",
                "temporal_conservation",
            )
        }
        for kind, path in reports.items():
            write_gate(path, kind, "green")
        manifest = temp / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "rom_sha256": ROM_SHA,
                    "coverage": tick_coverage(10, 12, complete=True),
                    "gates": {kind: str(path) for kind, path in reports.items()},
                }
            ),
            encoding="utf-8",
        )
        green_output = temp / "green.json"
        green = run(manifest, green_output)
        assert green.returncode == 0, green.stderr or green.stdout
        green_report = json.loads(green_output.read_text(encoding="utf-8"))
        assert green_report["acceptance_status"] == "green"
        assert green_report["claim_authority"] == "bounded_gameplay_acceptance"

        write_gate(
            reports["state_oracle"], "state_oracle", "green", rom="9" * 64
        )
        wrong_rom_output = temp / "wrong-rom.json"
        wrong_rom = run(manifest, wrong_rom_output)
        assert wrong_rom.returncode == 2, wrong_rom.stderr or wrong_rom.stdout
        wrong_rom_report = json.loads(
            wrong_rom_output.read_text(encoding="utf-8")
        )
        assert wrong_rom_report["acceptance_status"] == "unknown"
        assert "acceptance_gate_rom_mismatch" in wrong_rom_report["gates"][
            "state_oracle"
        ]["reasons"]
        write_gate(reports["state_oracle"], "state_oracle", "green")

        reports["temporal_conservation"].write_text(
            json.dumps(
                {
                    "acceptance_gate": gate(
                        "repetition_heuristic",
                        "unknown",
                        None,
                        None,
                        authority="diagnostic_only",
                    )
                }
            ),
            encoding="utf-8",
        )
        diagnostic_output = temp / "diagnostic-cannot-fill-gate.json"
        diagnostic = run(manifest, diagnostic_output)
        assert diagnostic.returncode == 2, diagnostic.stderr or diagnostic.stdout
        diagnostic_report = json.loads(
            diagnostic_output.read_text(encoding="utf-8")
        )
        assert diagnostic_report["acceptance_status"] == "unknown"
        assert "acceptance_gate_kind_mismatch" in diagnostic_report["gates"][
            "temporal_conservation"
        ]["reasons"]
        write_gate(
            reports["temporal_conservation"], "temporal_conservation", "green"
        )

        write_gate(reports["aligned_pixel_oracle"], "aligned_pixel_oracle", "red")
        red_output = temp / "red.json"
        red = run(manifest, red_output)
        assert red.returncode == 1, red.stderr or red.stdout
        assert json.loads(red_output.read_text(encoding="utf-8"))[
            "acceptance_status"
        ] == "red"

        write_gate(
            reports["aligned_pixel_oracle"], "aligned_pixel_oracle", "green"
        )
        reports["temporal_conservation"].unlink()
        unknown_output = temp / "unknown.json"
        unknown = run(manifest, unknown_output)
        assert unknown.returncode == 2, unknown.stderr or unknown.stdout
        unknown_report = json.loads(unknown_output.read_text(encoding="utf-8"))
        assert unknown_report["acceptance_status"] == "unknown"
        assert unknown_report["claim_authority"] == "none"

    print("gameplay three-oracle acceptance contract: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
