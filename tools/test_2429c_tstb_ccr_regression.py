#!/usr/bin/env python3
"""Guard the `$02429C`/`$0259CA` terminal-TST.B native repair evidence."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/escbank5.pasm"
PACKER = ROOT / "tools/build_interp_rom.py"
VALIDATOR = ROOT / "tools/validate_2429c_native.py"
CONTROLLED = ROOT / "build/validate-2429c-distinct-arm-candidate-b758-pinned-v2.jsonl"
ORGANIC = ROOT / "build/validate-2429c-organic3-candidate-b758-pinned-v1.jsonl"
PROMPT = ROOT / "build/validate-fresh-one-credit-prompt-candidate-b758-v1/summary.json"
ROM_SHA256 = "b7584c6fbac001dc3ec30e4684443c1965c122e50bbddc7b2e41fff8958caf57"
ISOLATED_CONTROLLED = ROOT / "build/validate-2429c-distinct-arm-isolated-a976-pinned-v1.jsonl"
ISOLATED_CAMPAIGN = ROOT / "build/fresh-candidate-2429c-tstb-ccr-isolated-a976-to10000-v1/summary.json"
ISOLATED_PROMPT = ROOT / "build/validate-fresh-one-credit-prompt-isolated-a976-v1/summary.json"
ISOLATED_ROM_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"


def summary(path: Path) -> dict:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return next(event for event in events if event.get("event") == "summary")


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    for required in (
        "jmp h2429c_tst_byte19_branch",
        "jmp h259ca_tst_byte_branch",
        "h2429c_tst_byte19_branch:",
        "h259ca_tst_byte_branch:",
        "TST.B NZVC",
    ):
        assert required in source, f"missing terminal TST.B CCR repair: {required}"
    packer = PACKER.read_text(encoding="utf-8")
    for required in (
        'task2429c_tst_byte = esc5_off("h2429c_tst_byte19_branch")',
        'task259ca_tst_byte = esc5_off("h259ca_tst_byte_branch")',
        "$02429C inactive-record TST.B terminal-CCR bridge",
        "$0259CA inactive-record TST.B terminal-CCR bridge",
    ):
        assert required in packer, f"missing packed-byte guard: {required}"
    validator = VALIDATOR.read_text(encoding="utf-8")
    assert '("scan_indirect_jsr", 0x0259FC, "br259ca_1")' in validator

    controlled = summary(CONTROLLED)
    assert (
        controlled["green"] == 9
        and controlled["red"] == 0
        and controlled["total"] == 9
        and controlled["result"] == "green"
    )
    organic = summary(ORGANIC)
    assert organic["green"] == 9 and organic["red"] == 0 and organic["result"] == "green"
    prompt = json.loads(PROMPT.read_text(encoding="utf-8"))
    assert prompt["rom_sha256"] == ROM_SHA256
    assert prompt["result"] == "green" and all(prompt["checks"].values())
    isolated_controlled = summary(ISOLATED_CONTROLLED)
    assert (
        isolated_controlled["green"] == 9
        and isolated_controlled["red"] == 0
        and isolated_controlled["total"] == 9
        and isolated_controlled["result"] == "green"
    )
    isolated_campaign = json.loads(ISOLATED_CAMPAIGN.read_text(encoding="utf-8"))
    assert isolated_campaign["rom_sha256"] == ISOLATED_ROM_SHA256
    assert isolated_campaign["result"] == "green"
    assert isolated_campaign["mame_end_tick"] == 10000
    assert isolated_campaign["player_reference_green"] == 2062
    assert isolated_campaign["player_reference_red"] == 0
    assert set(isolated_campaign["actions_observed"]) == {0, 1, 2, 3, 4, 5, 7, 8, 9, 10}
    isolated_prompt = json.loads(ISOLATED_PROMPT.read_text(encoding="utf-8"))
    assert isolated_prompt["rom_sha256"] == ISOLATED_ROM_SHA256
    assert isolated_prompt["result"] == "green" and all(isolated_prompt["checks"].values())
    print("$02429C/$0259CA TST.B CCR candidate regressions: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
