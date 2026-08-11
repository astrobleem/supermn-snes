#!/usr/bin/env python3
"""Regression for signed-word player death/respawn classification."""

from __future__ import annotations

from replay_mame_controller_campaign import player_health_alive


def transitions(values: list[int]) -> list[str]:
    result: list[str] = []
    previous = values[0]
    for current in values[1:]:
        before_alive = player_health_alive(previous)
        after_alive = player_health_alive(current)
        if before_alive and not after_alive:
            result.append("death")
        elif not before_alive and after_alive:
            result.append("respawn")
        previous = current
    return result


def main() -> None:
    assert player_health_alive(20)
    assert player_health_alive(1)
    assert not player_health_alive(0)
    assert not player_health_alive(0xFFFC)
    assert not player_health_alive(0xFFFA)
    assert transitions([2, 0, 20]) == ["death", "respawn"]
    assert transitions([6, 0xFFFC, 20]) == ["death", "respawn"]
    assert transitions([2, 0xFFFA, 0xFFFA, 20]) == [
        "death",
        "respawn",
    ]
    print("campaign signed-health transition regression: PASS")


if __name__ == "__main__":
    main()
