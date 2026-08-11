#!/usr/bin/env python3
"""Guard the current-hash paced-VTIME campaign, transport stop, and recovery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROM = (
    ROOT
    / "build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-"
    "paced-mvc-fallback-choke-gate-dbcc-stride-v1.sfc"
)
FAILED = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume3001-to5000-v1"
)
RECOVERY = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume4501-to5000-v1"
)
EXTENSION = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume5001-to6500-v1"
)
ZERO_ENTRY_FAILURE = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume6501-to8000-v1"
)
RUNNER_PREFLIGHT = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume6501-to8000-v2"
)
EXTENSION_8000 = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume6501-to8000-v3"
)
EXTENSION_9500 = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume8001-to9500-v1"
)
EXTENSION_11000 = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume9501-to11000-v1"
)
EXTENSION_12500 = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume11001-to12500-v1"
)
EXTENSION_14000 = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume12501-to14000-v1"
)
EXTENSION_15500 = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume14001-to15500-v1"
)
EXTENSION_17000 = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume15501-to17000-v1"
)
EXTENSION_18500 = (
    ROOT
    / "build/playback-watcher-20260811"
    / "vtime-interpreter-only-paced0818-dbcc-resume17001-to18500-v1"
)
EXTENSION_20000 = (
    ROOT
    / "build/playback-watcher-20260811"
    / "vtime-interpreter-only-paced0818-dbcc-resume18501-to20000-v1"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_checkpoint_bundle(
    directory: Path, tick: int, state_sha: str, iram_sha: str
) -> None:
    states = directory / "run/states"
    for suffix in ("", ".repeat-1", ".repeat-2"):
        stem = f"safe-checkpoint-{tick:05d}{suffix}.mss"
        assert sha256(states / stem) == state_sha
        assert sha256(states / f"{stem}.sa1-iram.bin") == iram_sha


def main() -> int:
    assert sha256(ROM) == (
        "14e920eb84a5ab44bff902b941f8926c42cab11f39e4537a88d2c4ad0e608750"
    )

    failed = json.loads(
        (FAILED / "watcher-report.json").read_text(encoding="utf-8")
    )
    divergence = failed["first_divergence"]
    assert divergence["kind"] == "runtime_transport_failure_after_last_green_boundary"
    assert divergence["last_completed_mame_tick"] == 4559
    assert divergence["exact_failure_tick"] is None
    assert divergence["harness_exit_status"] == 1
    assert failed["mismatch_ranges"] == []
    failed_symptoms = failed["specific_symptoms"]
    assert failed_symptoms["oracle_divergences"] == 0
    assert failed_symptoms["player_references"] == {"green": 763, "red": 0}
    assert failed_symptoms["last_structured_sample"]["halt"] == 0
    assert failed_symptoms["checkpoint_5000"] == "not produced"
    checkpoint_4500 = failed_symptoms["safe_checkpoints"]["4500"]
    assert checkpoint_4500["resumable"] is True
    assert_checkpoint_bundle(
        FAILED,
        4500,
        "fb53de19185f1893d9b2ce46910b089bc3bc68e38ba5d9c59792107ee65c7d13",
        "be81a79251f3d049a828bdabb19e7dd3bdec3818257a98e9534ab2677b4dc6ac",
    )

    recovery = json.loads(
        (RECOVERY / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert recovery["first_divergence"] is None
    assert recovery["mismatch_ranges"] == []
    symptoms = recovery["specific_symptoms"]
    assert symptoms["result"] == "partial-green"
    assert symptoms["harness_exit_status"] == 0
    assert symptoms["oracle_divergences"] == 0
    assert symptoms["segment_entries"] == {
        "requested": 499,
        "observed": 499,
        "first_boundary_tick": 4521,
        "last_boundary_tick": 5000,
    }
    assert symptoms["cumulative_lineage_entries_from_calibrated_tick250"] == {
        "requested": 4833,
        "observed": 4833,
    }
    assert symptoms["player_references"] == {"green": 921, "red": 0}
    assert symptoms["actions_observed"] == [0, 1, 2, 3, 4, 5, 7, 8, 9, 10]
    assert symptoms["end"]["halt"] == 0
    assert symptoms["end"]["mame_tick"] == 5000
    assert symptoms["end"]["minimum_task_stack_margin"] == 138
    assert_checkpoint_bundle(
        RECOVERY,
        4750,
        "7650ee3cddb40dba646a97128397974525f12615c9f0b43b0c406bbd554d8070",
        "48980b69b1ecb39a93351de9c426c0cd021223a7558fe207a09397f97513af7d",
    )
    assert_checkpoint_bundle(
        RECOVERY,
        5000,
        "0fd2e312a06c220fb4572e648efd5c59d93c5e6da8ddb3c586a95bb00a5d2fbd",
        "9e6e7605597e25a8e93ad526a0a49a8e9be75f63755928fcb46cc351961d3901",
    )

    extension = json.loads(
        (EXTENSION / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert extension["first_divergence"] is None
    assert extension["mismatch_ranges"] == []
    symptoms = extension["specific_symptoms"]
    assert symptoms["result"] == "partial-green"
    assert symptoms["harness_exit_status"] == 0
    assert symptoms["oracle_divergences"] == 0
    assert symptoms["resume_mame_tick"] == 5001
    assert symptoms["mame_end_tick_reached"] == 6500
    assert symptoms["segment_entries"] == {
        "requested": 1499,
        "observed": 1499,
        "boundary_events": 286,
        "first_boundary_tick": 5002,
        "last_boundary_tick": 6500,
    }
    assert symptoms["cumulative_lineage_entries_from_calibrated_tick250"] == {
        "requested": 6332,
        "observed": 6332,
    }
    assert symptoms["player_references"] == {"green": 1210, "red": 0}
    assert symptoms["actions_observed"] == [0, 1, 2, 3, 4, 5, 7, 8, 9, 10]
    assert symptoms["boss_events"] == {"total": 0, "green": 0, "red": 0}
    assert symptoms["end"]["halt"] == 0
    assert symptoms["end"]["mame_tick"] == 6500
    assert symptoms["end"]["minimum_task_stack_margin"] == 138
    assert_checkpoint_bundle(
        EXTENSION,
        5500,
        "6a34042a1e67bbe41db8b2aada996078b1c259c3c4df400172876132a375175e",
        "802c232117f6d8f3d7fd46b1689e60f79d34167d6e0849fd42793d3899077a3b",
    )
    assert_checkpoint_bundle(
        EXTENSION,
        6000,
        "8af44725c93f1c20158637bdf3a8cd98039e00038b0d772ae9888d711e42cc6b",
        "25893294dbafbf83cd765dbe1b2bca975fe32a31af7b179b158afa969bd01538",
    )
    assert_checkpoint_bundle(
        EXTENSION,
        6500,
        "fb9644dd343dc0e3fa1bf49bd61200a2e5eacceb84ffdff3c268a39b1bf5a245",
        "26c824b337bd76248ceb6a43c43dbc81f6794fdc8d8bfa613dafad5c460847e4",
    )

    failure = json.loads(
        (ZERO_ENTRY_FAILURE / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert failure["first_divergence"]["kind"] == (
        "bounded_continuation_harness_failure"
    )
    assert failure["first_divergence"]["mame_tick"] == 6501
    assert failure["first_divergence"]["oracle_divergence"] is False
    assert failure["mismatch_ranges"] == []
    failure_symptoms = failure["specific_symptoms"]
    assert failure_symptoms["completed_mame_tick"] == 6500
    assert failure_symptoms["new_checkpoints"].startswith("none")
    diagnostic = json.loads(
        (ZERO_ENTRY_FAILURE / "transport-diagnostic.json").read_text(
            encoding="utf-8"
        )
    )
    assert diagnostic["confirmed_root_cause"].startswith(
        "campaign harness zero-entry boundary bug"
    )
    assert diagnostic["rom_or_gameplay_implicated"] is False
    assert diagnostic["invalidated_evidence"].startswith(
        "Only this child continuation"
    )

    preflight = json.loads(
        (RUNNER_PREFLIGHT / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert preflight["first_divergence"]["kind"] == (
        "preflight_lineage_identity_mismatch"
    )
    assert preflight["mismatch_ranges"] == []
    preflight_symptoms = preflight["specific_symptoms"]
    assert preflight_symptoms["result"] == "preflight-blocked"
    assert preflight_symptoms["emulator_playback"] is False
    assert preflight_symptoms["checkpoints"] == "none"

    extension_8000 = json.loads(
        (EXTENSION_8000 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert extension_8000["first_divergence"] is None
    assert extension_8000["mismatch_ranges"] == []
    symptoms = extension_8000["specific_symptoms"]
    assert symptoms["result"] == "partial-green; exit 0; no oracle divergence"
    assert "segment entries 1499/1499 (6502-8000)" in symptoms["coverage"]
    assert "cumulative lineage 7831/7831" in symptoms["coverage"]
    assert "1585/0 cumulative" in symptoms["coverage"]
    assert "boss events 0" in symptoms["coverage"]
    assert "MAME tick 8000" in symptoms["end"]
    assert "halt 0" in symptoms["end"]
    assert "minimum margin 130" in symptoms["end"]
    assert_checkpoint_bundle(
        EXTENSION_8000,
        7000,
        "c8804f498bfe443553ff5655c7aec6cba718424ece1c7a2c6a7536a876662c14",
        "c86a878917bce12a4d59777d660af3051da3d05b46be11cae4669b1546d905bc",
    )
    assert_checkpoint_bundle(
        EXTENSION_8000,
        7500,
        "09097de10aa8fbfae694a3a7883e55f63b2da0288a3231de1882c2b2d2e2d489",
        "06b5749a43de7f288d7b80be1b05696f1d88363b61e603b71bb13ec5ddbd1657",
    )
    assert_checkpoint_bundle(
        EXTENSION_8000,
        8000,
        "aea7ce50e4c3fe4fe00ed6779d4291ba4696c92360125915aa66e5f16b06d263",
        "99bab411b54c3f4492fa4d2deee64b4e526edd3001cb1244174ac15d49e5746e",
    )

    extension_9500 = json.loads(
        (EXTENSION_9500 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert extension_9500["first_divergence"] is None
    assert extension_9500["mismatch_ranges"] == []
    symptoms = extension_9500["specific_symptoms"]
    assert symptoms["result"] == "partial-green; exit 0; no oracle divergence"
    assert "segment entries 1499/1499 (8002-9500)" in symptoms["coverage"]
    assert "cumulative lineage 9330/9330" in symptoms["coverage"]
    assert "1852/0 cumulative" in symptoms["coverage"]
    assert "boss events 0" in symptoms["coverage"]
    assert "MAME tick 9500" in symptoms["end"]
    assert "halt 0" in symptoms["end"]
    assert "minimum margin 138" in symptoms["end"]
    assert_checkpoint_bundle(
        EXTENSION_9500,
        8500,
        "accaea42dfaaa50636a4115ef7a904f77a69937f35bed9a74e26bc316008d27f",
        "48b0f3b3720fd1cf656d2148d070b9d4379f845867a5b019dd3dd85f446a6eb6",
    )
    assert_checkpoint_bundle(
        EXTENSION_9500,
        9000,
        "bd265e56519a007c61f8a852add39bf018f77f9b850c2077e6f27b788f54d846",
        "cb63e887b7e14dbc4b33f00f061ba0b8b2d40c150c9d2edbf8b0e98c79e2cb56",
    )
    assert_checkpoint_bundle(
        EXTENSION_9500,
        9500,
        "efd193b09317cf0ef2404956591a6d7f7b892b2a23e969838647e0a901b56106",
        "fabcd9191dc1c46135d978901eb729d9fa331f5b78559332bd9cc69b3c93b1b1",
    )

    extension_11000 = json.loads(
        (EXTENSION_11000 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert extension_11000["first_divergence"] is None
    assert extension_11000["mismatch_ranges"] == []
    symptoms = extension_11000["specific_symptoms"]
    assert symptoms["result"] == "partial-green; exit 0; no oracle divergence"
    assert "segment entries 1499/1499 (9502-11000)" in symptoms["coverage"]
    assert "cumulative lineage 10829/10829" in symptoms["coverage"]
    assert "2402/0 cumulative" in symptoms["coverage"]
    assert "boss events 0" in symptoms["coverage"]
    assert "MAME tick 11000" in symptoms["end"]
    assert "halt 0" in symptoms["end"]
    assert "minimum margin 138" in symptoms["end"]
    assert_checkpoint_bundle(
        EXTENSION_11000,
        10000,
        "eaa3c27f6440e76d1cdb4364693ae283128a2e6fdeacc31b204ee5fabca02f49",
        "522a3e6ca06e45030dc89f7447eb1e66db86f351c120981270a5dcc244db06d5",
    )
    assert_checkpoint_bundle(
        EXTENSION_11000,
        10500,
        "a4dca9624051ac4d9bad09e821458232711e802f0cf6f0e64a0c6bc394d3620d",
        "55ceb361822bef103d45483c0d6370ed3ee0ed388f32e26dc1b505023fe1029b",
    )
    assert_checkpoint_bundle(
        EXTENSION_11000,
        11000,
        "6fd495085a0653c49cb3018fe9aff1cbce618b4ce756c5abd74f81363f127024",
        "ef9a80338ec0d4d125a088e1f177c65f860a86d42408d1c64ffd7627dbfb5b62",
    )

    extension_12500 = json.loads(
        (EXTENSION_12500 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert extension_12500["first_divergence"] is None
    assert extension_12500["mismatch_ranges"] == []
    symptoms = extension_12500["specific_symptoms"]
    assert symptoms["result"] == (
        "partial-green; exit 0; oracle divergence count 0"
    )
    assert "segment entries 1499/1499 (11002-12500)" in symptoms["coverage"]
    assert "cumulative 12328/12328" in symptoms["coverage"]
    assert "2566/0 cumulative" in symptoms["coverage"]
    assert "boss events 0" in symptoms["coverage"]
    assert "MAME tick 12500" in symptoms["end"]
    assert "halt 0" in symptoms["end"]
    assert "minimum margin 92" in symptoms["end"]
    assert_checkpoint_bundle(
        EXTENSION_12500,
        11500,
        "4612ce8e4fa7c7c0e5eb228ba2b2594c0ddc871bd4dd4e8ac09f7ffdec3a3c87",
        "490f132c4c01bd6e1296ae13001cd4b82c7dafe08a15377a0bb95455f2c59662",
    )
    assert_checkpoint_bundle(
        EXTENSION_12500,
        12000,
        "aceb4565c8b2a58fc78d13f5bc916bf0465c1179bd0fb38f589a69a8f6bb65b0",
        "32f70f9967167622a515f1db41c92757eec5b046915a22c01bb7067d6ff4c10d",
    )
    assert_checkpoint_bundle(
        EXTENSION_12500,
        12500,
        "0ff1242f92e3e4b179233ecb628e5c6e4139006ba15b1e5eb6cfa55a761a746a",
        "83608462cf23ad1c9801fef72de5be7fa1f4495cfbf24e25399841e17e29480e",
    )

    extension_14000 = json.loads(
        (EXTENSION_14000 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert extension_14000["first_divergence"] is None
    assert extension_14000["mismatch_ranges"] == []
    symptoms = extension_14000["specific_symptoms"]
    assert symptoms["result"] == (
        "partial-green; exit 0; oracle divergence count 0"
    )
    assert "segment entries 1499/1499 (12502-14000)" in symptoms["coverage"]
    assert "cumulative 13827/13827" in symptoms["coverage"]
    assert "2650/0 cumulative" in symptoms["coverage"]
    assert "boss events 0" in symptoms["coverage"]
    assert "MAME tick 14000" in symptoms["end"]
    assert "halt 0" in symptoms["end"]
    assert "minimum margin 138" in symptoms["end"]
    assert_checkpoint_bundle(
        EXTENSION_14000,
        13000,
        "cd685b5476bdae3eb782824e552430fca55a93b900af03f8e5ecd9344956d967",
        "fe8d6630bf0821aa40b5b7c84ecc27757f38d720bb3ffeb3ea9abdae6c8e192a",
    )
    assert_checkpoint_bundle(
        EXTENSION_14000,
        13500,
        "2daae83a5444a52fa22ce48fee63923463fc10817351baa8a0aec23e52d0c503",
        "c3e788db93a1ad740aa2961053e949f1a3c19c448dd1bff43c07812805eacbdc",
    )
    assert_checkpoint_bundle(
        EXTENSION_14000,
        14000,
        "234ef4ade73d9c1df5fa653d1feedf332b454a3916b8168c1759161255675315",
        "a5d1d340a1144e8dd0c70ce60230dd1bc2a3e40671bf9e4a499a824cfffbed5c",
    )

    extension_15500 = json.loads(
        (EXTENSION_15500 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert extension_15500["first_divergence"].startswith(
        "MAME tick 14748 input_response_compare: player Y SNES=139"
    )
    assert extension_15500["mismatch_ranges"] == [
        "player.y-only oracle mismatches at ticks "
        "14748,14755,14757,14759,14761,14812,14814,14829,14831,14839,"
        "14841,14843,14846,14848,14850-14853,14855,14857,14859,14861,"
        "14864,14866 (27 records; 24 unique ticks)"
    ]
    symptoms = extension_15500["specific_symptoms"]
    assert symptoms["result"].startswith(
        "partial-with-oracle-divergences; exit 0; 27 oracle divergences"
    )
    assert "segment entries 1499/1499 (14002-15500)" in symptoms["coverage"]
    assert "cumulative 15326/15326" in symptoms["coverage"]
    assert "2785/27 cumulative" in symptoms["coverage"]
    assert "No boss-fixture events" in symptoms["stage_boss"]
    assert "MAME tick 15500" in symptoms["end"]
    assert "SNES game tick 15494" in symptoms["end"]
    assert "halt 0" in symptoms["end"]
    assert "minimum margin 138" in symptoms["end"]
    assert_checkpoint_bundle(
        EXTENSION_15500,
        14500,
        "36ca846dc380f922e81fb79850d9fa4c3e775c3fd9fde3353400befd72528e97",
        "b93d90351b083ebaa631348e75260c059de877536c6db94fb21c9176df49338c",
    )
    assert_checkpoint_bundle(
        EXTENSION_15500,
        15000,
        "9d0403e2327ea2db441f913462bac17900421a9961dbdfe75390fb61ef059b24",
        "e8e794909f06aa835db5be9fa1a385f3f2f07cecc406b3c36978015a42884516",
    )
    assert_checkpoint_bundle(
        EXTENSION_15500,
        15500,
        "43f9c07c04389a85783d4e5ac689e5039d3d9caf3fcf336680203c15ad916beb",
        "d5dff99d0810bf9a59444ca90ae9055a1daf0b415a0e17dfbe108cd4c5a7fba7",
    )

    extension_17000 = json.loads(
        (EXTENSION_17000 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert extension_17000["first_divergence"].startswith(
        "Inherited authoritative divergence at MAME tick 14748"
    )
    assert extension_17000["mismatch_ranges"] == [
        "Inherited player-Y-only range begins at tick 14748 and remains "
        "represented in later input-response comparisons.",
        "This segment: 38 oracle divergences total (input_compare 13, "
        "input_response_compare 14, boss 11); 11 boss mismatches are retained "
        "around the tick-16998 failure boundary. Full rows remain in "
        "run/events.jsonl.",
    ]
    symptoms = extension_17000["specific_symptoms"]
    assert symptoms["result"].startswith(
        "Exit 1/red due to boss_oracle_mismatch, not transport, renderer, or halt"
    )
    assert "cumulative processed transitions 1529" in symptoms["coverage"]
    assert "player references 3031 green/27 red" in symptoms["coverage"]
    assert "boss fixtures 0 green/11 red" in symptoms["coverage"]
    assert "halt 0" in symptoms["end_state"]
    assert "minimum margin 138" in symptoms["end_state"]
    assert symptoms["rebuild_required_now"] is False
    assert_checkpoint_bundle(
        EXTENSION_17000,
        16000,
        "3f03fa0f2415045a9d5a4fecebb3f0a78bfbcf9da6906a7766ba51ad112b5888",
        "e55128296a571b7b748d55794bde76b74171c7e36122e89ce0531d52a1c3466c",
    )
    assert_checkpoint_bundle(
        EXTENSION_17000,
        16500,
        "4a515ca0372dfa985bebb082f2237e55bba030f6139d221c0e0285d8c707deba",
        "681812d63195c1ffb4ff331f476b3b9adcfc7a4b34b0e1ef618bf5c8a342548a",
    )
    assert_checkpoint_bundle(
        EXTENSION_17000,
        17000,
        "a9826e63926461858b844dd861c8506d3bdb22d0c441d976e4b093774c268089",
        "cdf1a8c78b1744d7b34d437114fec61d2cdb6af731e9a53f96ff51a52b946387",
    )

    extension_18500 = json.loads(
        (EXTENSION_18500 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert extension_18500["first_divergence"].startswith(
        "Inherited authoritative divergence at MAME tick 14748"
    )
    assert extension_18500["mismatch_ranges"] == [
        "Inherited player-Y-only mismatch persists in input-response "
        "comparisons; cumulative classes are input_compare 13, "
        "input_response_compare 14, boss 14 (41 total).",
        "New segment boss rows: stage1-hit-11 at tick 17018 (expected health "
        "6, observed 9), stage1-hit-12 at 17560 (2, observed 6), and "
        "stage1-hit-13 at 17654 (65535, observed 2); all red.",
    ]
    symptoms = extension_18500["specific_symptoms"]
    assert symptoms["result"].startswith("Reached MAME tick 18500")
    assert "cumulative processed transitions 1581" in symptoms["coverage"]
    assert "player references 3135 green/27 red" in symptoms["coverage"]
    assert "14 cumulative boss rows red, 0 green" in symptoms["coverage"]
    assert "SNES game tick 18494 versus MAME 18500" in symptoms["end_state"]
    assert "halt 0" in symptoms["end_state"]
    assert "minimum margin 138" in symptoms["end_state"]
    assert "Rebuild_required_now=false" in symptoms["safety"]
    assert_checkpoint_bundle(
        EXTENSION_18500,
        17500,
        "87174e2d70a5907bf13310e90358e34d42cd1d39a1628ac0cb55426b72c41f21",
        "8a21cd947fc073a4223a7bc988b469b7f4bbb2921d42526af6277238a893f8a5",
    )
    assert_checkpoint_bundle(
        EXTENSION_18500,
        18000,
        "e6965f29cf394ff696a4fe0fb1c1a69a914471275002847e0f0df833b05c2550",
        "064c91253b984d540f4428ab32bea9bfa9026b34fef10e697c396d9463d2181e",
    )
    assert_checkpoint_bundle(
        EXTENSION_18500,
        18500,
        "718d3dd320187bd259f19a2dfe58f94f7410b26102f29314defac53381fd828e",
        "a14d74b781f42fb5e5756416091eba87f861a194dd1b01d7fd130f858b098d58",
    )

    extension_20000 = json.loads(
        (EXTENSION_20000 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert extension_20000["first_divergence"].startswith(
        "Inherited authoritative divergence at MAME tick 14748"
    )
    assert extension_20000["mismatch_ranges"] == [
        "Inherited player-Y-only mismatch remains the first mismatch; "
        "cumulative classes remain input_compare 13, input_response_compare "
        "14, boss 14 (41 total).",
        "New segment mismatch rows: none; no new boss fixture row was emitted "
        "in this segment.",
    ]
    symptoms = extension_20000["specific_symptoms"]
    assert symptoms["result"].startswith("Reached MAME tick 20000")
    assert "cumulative processed transitions 1742" in symptoms["coverage"]
    assert "player references 3456 green/27 red" in symptoms["coverage"]
    assert "14 cumulative boss rows red/0 green" in symptoms["coverage"]
    assert "SNES game tick 19994 versus MAME 20000" in symptoms["end_state"]
    assert "halt 0" in symptoms["end_state"]
    assert "minimum margin 136" in symptoms["end_state"]
    assert "Rebuild_required_now=false" in symptoms["safety"]
    assert_checkpoint_bundle(
        EXTENSION_20000,
        19000,
        "8981eb4d9adfe36577ba7a82eada8d242d7e0eb7df5fe174c368b49f840f2f95",
        "94fabc0a248c237cc7b78a56d6bcbcde3af75e5253c06031b84db56d9e05a5cc",
    )
    assert_checkpoint_bundle(
        EXTENSION_20000,
        19500,
        "71c44bba68bd16d7220c3aca0700723875fdf29c8e81e3847f3f4b77bded08a7",
        "7e0fcba37a090fa45b2e2c0899156c03dc73474746a555b2511e6ef2f4fc486c",
    )
    assert_checkpoint_bundle(
        EXTENSION_20000,
        20000,
        "caf9df722b039d7eaa05b79b60ed6f39d0ad41254eb3a4213680a5c51206fcd8",
        "f06ec2ad4c05a7d5ef5cecd8dc7631f07c1a99d1ad08031bf18be8b4ee52a704",
    )
    print("VTIME current-hash campaign transport/recovery regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
