#!/usr/bin/env python3
"""Pin the boss write-frame -> MAME tick-start boundary.

The retained boss fixture records the health bus write during a frame.  The
campaign stops at the pre-body $003A92 boundary for that frame, then observes
the committed write at the following tick start.  This is deliberately a
fixture/timeline test; it does not launch MAME/Nexen or import the runner.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "boss-health-stage123-fixtures-v3/fixtures.json"
)
TIMELINE = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "full-playback-timeline-v1/timeline.jsonl"
)
RUNNER = ROOT / "tools/replay_mame_controller_campaign.py"


def fixture_frame_to_write_tick(frame: int) -> int:
    """Convert a write frame to its pre-body timeline tick start."""

    return frame - 74


def main() -> None:
    runner_tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    constants = {
        target.id: ast.literal_eval(node.value)
        for node in runner_tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and target.id in {
            "MAME_FRAME_TO_BOSS_WRITE_TICK",
            "BOSS_OBSERVATION_DELAY_TICKS",
        }
    }
    assert constants == {
        "MAME_FRAME_TO_BOSS_WRITE_TICK": 74,
        "BOSS_OBSERVATION_DELAY_TICKS": 1,
    }, constants
    observation_functions = [
        node
        for node in runner_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "boss_observation_tick"
    ]
    assert len(observation_functions) == 1
    observation_function = observation_functions[0]
    returns = [
        node for node in observation_function.body if isinstance(node, ast.Return)
    ]
    assert len(returns) == 1
    observation_expression = ast.Expression(returns[0].value)
    ast.fix_missing_locations(observation_expression)
    observation_code = compile(observation_expression, str(RUNNER), "eval")

    def observe(write_tick: int) -> int:
        return int(
            eval(  # noqa: S307 - expression is pinned to the local runner AST
                observation_code,
                {"BOSS_OBSERVATION_DELAY_TICKS": 1},
                {"write_tick": write_tick},
            )
        )

    observation_calls = [
        node
        for node in ast.walk(runner_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "boss_observation_tick"
    ]
    # One call bounds fixture loading by the observable endpoint; the other
    # schedules the comparison at that same post-write boundary.
    assert len(observation_calls) == 2

    manifest = json.loads(FIXTURES.read_text(encoding="utf-8"))
    cases = {str(row["name"]): row for row in manifest["cases"]}
    expected = {
        "stage1-init": (15981, 15907, 15908),
        "stage1-hit-01": (16063, 15989, 15990),
    }
    for name, (frame, write_tick, observation_tick) in expected.items():
        row = cases[name]
        assert int(row["frame"]) == frame, (name, row["frame"])
        assert fixture_frame_to_write_tick(frame) == write_tick
        assert observe(write_tick) == observation_tick
        assert frame - 75 != write_tick, "old frame-75 mapping must remain rejected"

    timeline_rows: dict[int, dict[str, object]] = {}
    tick_row_count = 0
    with TIMELINE.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("event") != "tick":
                continue
            tick = int(row.get("tick", -1))
            frame = int(row["frame"])
            assert frame - tick == 74, (tick, frame)
            tick_row_count += 1
            if tick in {15907, 15908, 15989, 15990}:
                timeline_rows[tick] = row

    assert tick_row_count == 139925, tick_row_count
    assert set(timeline_rows) == {15907, 15908, 15989, 15990}
    assert int(timeline_rows[15907]["boss_word"]) == 0
    assert int(timeline_rows[15908]["boss_word"]) == 40
    assert int(timeline_rows[15989]["boss_word"]) == 40
    assert int(timeline_rows[15990]["boss_word"]) == 36
    for tick, row in timeline_rows.items():
        frame = int(row["frame"])
        assert frame - tick == 74, (tick, frame)
        assert row.get("boundary_kind") in (None, "tick_start_3a92")

    print("boss fixture frame/tick boundary regression: green")


if __name__ == "__main__":
    main()
