#!/usr/bin/env python3
"""Guard active-ROM gameplay evidence from the current validation campaign."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "build/interp.sfc"
DAMAGE = ROOT / "build/validate-gameplay-damage-current-a976-v1"
BOSS = ROOT / "build/validate-boss-health-current-a976-v1.json"
CRATE = ROOT / "build/validate-organic-crate-current-a976-v1/summary.json"
FLIGHT = ROOT / "build/validate-organic-crate-flight-current-a976-v1/summary.json"
HUD_NEXEN = ROOT / "build/validate-fresh-one-credit-prompt-isolated-a976-v1/summary.json"
HUD_MESEN = ROOT / "build/validate-fresh-one-credit-prompt-isolated-a976-mesen211-v1/summary.json"
NATIVE_OFF_PREFIX = ROOT / "build/fresh-campaign-current-a976-native-off-first-entry-v6"
NATIVE_OFF_SUMMARY = NATIVE_OFF_PREFIX / "summary.json"
NATIVE_OFF_EVENTS = NATIVE_OFF_PREFIX / "events.jsonl"
NATIVE_OFF_MOVEMENT = ROOT / "build/fresh-campaign-current-a976-native-off-first-movement-v1"
NATIVE_OFF_MOVEMENT_SUMMARY = NATIVE_OFF_MOVEMENT / "summary.json"
NATIVE_OFF_MOVEMENT_EVENTS = NATIVE_OFF_MOVEMENT / "events.jsonl"
NATIVE_ON_EVENTS = ROOT / "build/fresh-campaign-current-a976-to14746-native-on-v1/events.jsonl"
MAME_TIMELINE = (
    ROOT
    / "build/playtest-investigation-20260725/full-playback-timeline-v1/timeline.jsonl"
)
ROM_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def assert_green_configurations(summary: dict, expected: int) -> None:
    configurations = summary["configurations"]
    assert len(configurations) == expected
    for configuration in configurations:
        assert configuration["result"] == "green"
        assert all(configuration["checks"].values())
        assert configuration["first_failure_prestate"] is None


def main() -> int:
    assert hashlib.sha256(ROM.read_bytes()).hexdigest() == ROM_SHA256

    for hud in (HUD_NEXEN, HUD_MESEN):
        hud_summary = json.loads(hud.read_text(encoding="utf-8"))
        assert hud_summary["rom_sha256"] == ROM_SHA256
        assert hud_summary["result"] == "green"
        assert all(hud_summary["checks"].values())

    damage_rows = read_jsonl(DAMAGE)
    damage_summary = next(
        row for row in damage_rows if row.get("event") == "summary"
    )
    assert damage_summary["result"] == "green"
    assert (damage_summary["green"], damage_summary["red"], damage_summary["total"]) == (4, 0, 4)
    damage_cases = [row for row in damage_rows if row.get("event") == "case"]
    assert {
        row["label"]: row["damage"]
        for row in damage_cases
    } == {
        "normal attack": 1,
        "kick attack (Button 2)": 2,
        "body/contact class; retained metadata does not prove carry/flight": 4,
        "charged projectile": 4,
    }
    assert all(row["result"] == "green" for row in damage_cases)

    boss_rows = read_jsonl(BOSS)
    boss_summaries = [
        row for row in boss_rows if row.get("event") == "stage_summary"
    ]
    assert sum(int(row["differential_case_count"]) for row in boss_summaries) == 118
    assert [
        (row["stage"], row["initial_health"], row["arcade_hit_count"])
        for row in boss_summaries
    ] == [(1, 40, 13), (2, 40, 37), (3, 20, 6)]
    assert all(row["result"] == "green" for row in boss_summaries)

    crate = json.loads(CRATE.read_text(encoding="utf-8"))
    assert crate["rom_sha256"] == ROM_SHA256
    assert crate["result"] == "green"
    assert crate["checkpoint_lineage"]["kind"] == "fresh_boot_root_checkpoint_continuation"
    assert crate["checkpoint_lineage"]["rom_migration"] is None
    assert all(crate["mame_checks"].values())
    assert all(crate["cross_configuration_checks"].values())
    assert_green_configurations(crate, expected=4)
    crate_branches = {
        (row["branch"], row["configuration"]): row
        for row in crate["configurations"]
    }
    expected_damage = [
        {
            "tick": 3274,
            "previous_tick": 3273,
            "slot": 0,
            "health_address": "F02BB7",
            "before": 1,
            "after": 0,
        },
        {
            "tick": 3283,
            "previous_tick": 3282,
            "slot": 1,
            "health_address": "F02C61",
            "before": 1,
            "after": 0,
        },
    ]
    for configuration in (
        "snes-gameplay-root-off-scheduler-pacing-preserved",
        "snes-native-on",
    ):
        held = crate_branches[("held_contact", configuration)]
        thrown = crate_branches[("legitimate_throw", configuration)]
        assert held["snes_contact_ticks"] == list(range(3253, 3270))
        assert held["snes_active_enemy_health_transitions"] == []
        assert thrown["snes_active_enemy_health_transitions"] == expected_damage

    flight = json.loads(FLIGHT.read_text(encoding="utf-8"))
    assert flight["rom_sha256"] == ROM_SHA256
    assert flight["result"] == "green"
    assert (flight["held_mask"], flight["switch_tick"], flight["switch_mask"]) == (
        0xA0,
        3253,
        0x90,
    )
    assert all(flight["mame_checks"].values())
    assert all(flight["cross_configuration_checks"].values())
    assert_green_configurations(flight, expected=2)
    for configuration in flight["configurations"]:
        assert configuration["snes_contact_ticks"] == list(range(3253, 3270))
        assert configuration["snes_active_enemy_health_transitions"] == []

    # The original fresh native-off root attempts waited for the intentionally
    # unreachable native $92:DB82 entry and timed out.  This small fresh
    # prefix instead stops at the counted rising virtual-PC $003A92 edge
    # after gates $071A/$073A are deliberately cleared.  It is deliberately
    # partial coverage, so validate both its exact-edge contract and its
    # explicit non-claim rather than treating it as a gameplay completion.
    native_off = json.loads(NATIVE_OFF_SUMMARY.read_text(encoding="utf-8"))
    assert native_off["rom_sha256"] == ROM_SHA256
    assert native_off["result"] == "partial-green"
    assert native_off["failure"] is None
    assert native_off["lineage_kind"] == "fresh_power_on_root"
    assert native_off["testflag"] == 0
    assert native_off["cold_boot"]["origin_player_comparison"]["result"] == "green"
    assert native_off["end"]["mame_tick"] == 222
    assert native_off["end"]["pc68k"] == 0x003A92
    assert native_off["end"]["halt"] == 0
    assert native_off["end"]["gates"]["xlat_071a"] == 0
    assert native_off["end"]["gates"]["choke_073a"] == 0
    mame_tick_222 = next(
        row
        for row in read_jsonl(MAME_TIMELINE)
        if row.get("event") == "tick" and row.get("tick") == 222
    )
    assert {
        "action": native_off["end"]["player"]["action"],
        "health": native_off["end"]["player"]["health"],
        "x": native_off["end"]["player"]["x"],
        "y": native_off["end"]["player"]["y"],
        "scroll_x": native_off["end"]["player"]["x1_ctrl_3601"],
        "scroll_y": native_off["end"]["player"]["x1_ctrl_3603"],
    } == {
        "action": mame_tick_222["action"],
        "health": mame_tick_222["health"],
        "x": mame_tick_222["player_x"],
        "y": mame_tick_222["player_y"],
        "scroll_x": mame_tick_222["scroll_x"],
        "scroll_y": mame_tick_222["scroll_y"],
    }
    assert native_off["campaign_configuration"][
        "post_gate_exact_tick_boundary"
    ] == {
        "debugger_control_extension_only": True,
        "edge": "rising",
        "emulation_semantics_or_rom_modified": False,
        "iram_address": "0040",
        "logical_seam": "rising virtual-PC edge before interpreted $003A92 body",
        "tool": "run_to_exact_iram_exec_edge",
        "virtual_pc_value": "003A92",
        "why_not_native_sa1_address": (
            "$92:DB82 is intentionally unreachable after $071A/$073A are cleared"
        ),
    }
    assert native_off["coverage_gaps"]["missing_actions"] == [
        1,
        2,
        3,
        4,
        5,
        7,
        8,
        9,
        10,
    ]
    assert native_off["coverage_gaps"]["missing_buttons"] == [
        "a",
        "b",
        "down",
        "left",
        "right",
        "up",
    ]
    prefix_events = read_jsonl(NATIVE_OFF_EVENTS)
    edge_rows = [
        row
        for row in prefix_events
        if row.get("event") == "interpreted_game_update_boundary"
    ]
    assert len(edge_rows) == 1
    span = edge_rows[0]["spans"][0]
    assert (edge_rows[0]["mame_tick"], span["boundary"]) == (
        222,
        "interpreted_pc_003a92_rising_edge_pre_body",
    )
    assert (span["requested_entries"], span["observed_entries"]) == (1, 1)
    assert span["virtual_pc"] == "003A92"
    edge = span["chunk_runs"][0]
    assert all(edge["campaign_boundary_checks"].values())
    assert edge["iramAddress"] == 0x0040
    assert edge["observedValue"] == 0x003A92
    assert edge["edgeRequired"] is True
    assert edge["initialMatch"] is False

    # Extend the fresh root-off proof through the first genuine controller
    # transition.  Tick 1054 presses Left; at the response boundary tick 1056
    # both original MAME and the interpreted root move the player from x=64
    # to x=61.  The result remains deliberately partial--it does not stand in
    # for the focused attack/boss/death matrix above.
    movement = json.loads(
        NATIVE_OFF_MOVEMENT_SUMMARY.read_text(encoding="utf-8")
    )
    assert movement["rom_sha256"] == ROM_SHA256
    assert movement["result"] == "partial-green"
    assert movement["failure"] is None
    assert movement["lineage_kind"] == "fresh_power_on_root"
    assert movement["testflag"] == 0
    assert (movement["processed_input_transitions"], movement["player_reference_green"], movement["player_reference_red"]) == (1, 2, 0)
    assert movement["end"]["mame_tick"] == 1060
    assert movement["end"]["halt"] == 0
    assert movement["end"]["gates"]["xlat_071a"] == 0
    assert movement["end"]["gates"]["choke_073a"] == 0
    assert (NATIVE_OFF_MOVEMENT / "states/pre-input-latest.mss").is_file()
    movement_events = read_jsonl(NATIVE_OFF_MOVEMENT_EVENTS)
    applies = [row for row in movement_events if row.get("event") == "input_apply"]
    responses = [
        row
        for row in movement_events
        if row.get("event") == "input_response_compare"
    ]
    assert len(applies) == len(responses) == 1
    assert {
        key: applies[0][key]
        for key in ("mame_tick", "effective_mame_tick", "buttons", "label")
    } == {
        "mame_tick": 1054,
        "effective_mame_tick": 1054,
        "buttons": 0x40,
        "label": "left",
    }
    assert responses[0]["comparison"]["result"] == "green"
    assert responses[0]["mame_tick"] == 1056
    assert responses[0]["comparison"]["mame"]["x"] == 61
    assert responses[0]["comparison"]["snes"]["x"] == 61
    for row in movement_events:
        if row.get("event") == "interpreted_game_update_boundary":
            for chunk in row["spans"][0]["chunk_runs"]:
                assert all(chunk["campaign_boundary_checks"].values())
    native_on_response = next(
        row
        for row in read_jsonl(NATIVE_ON_EVENTS)
        if row.get("event") == "input_response_compare"
        and row.get("mame_tick") == 1056
        and row.get("source_input_tick") == 1054
    )
    assert native_on_response["comparison"]["result"] == "green"
    assert native_on_response["comparison"]["mame"] == responses[0]["comparison"]["mame"]
    assert native_on_response["comparison"]["snes"] == responses[0]["comparison"]["snes"]
    assert native_on_response["spans"][0]["boundary"] == "native_entry_003A92"

    print(
        "active a976 HUD, combat, crate, and fresh native-off edge/movement evidence: green"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
