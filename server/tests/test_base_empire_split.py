"""Tests for pipeline.py's base-empire worker carry-forward (see
docs/optimizer-feature-proposals.md item 1 / bdo-empire issue #9): idle and
non-plantzone workers (workshop/custom/farming) used to vanish from a solve's
result because bdo-empire's own extract_base_empire() can't handle them.
"""
import pipeline


def test_tnk_to_town_name_covers_all_known_towns():
    # Verified against the real game data files (server/static/data/
    # regioninfo.json + loc.json), not a mock - this is the exact chain
    # (tnk -> tk via regioninfo's waypoint/key, tk -> name via loc.json's
    # en.town) the fix depends on actually resolving correctly.
    mapping = pipeline._tnk_to_town_name()
    names = set(mapping.values())
    missing = set(pipeline._TOWNS_BONUS_UB.keys()) - names
    assert not missing, f"town names in _TOWNS_BONUS_UB with no tnk mapping: {missing}"


def test_split_keeps_only_plantzone_workers_for_the_solver(monkeypatch):
    monkeypatch.setattr(pipeline, "_tnk_to_town_name", lambda: {1: "Velia", 2: "Heidel"})

    base_empire = {
        "userWorkers": [
            {"tnk": 1, "job": {"kind": "plantzone", "pzk": 100, "storage": 1}},
            {"tnk": 1, "job": None},                                              # idle
            {"tnk": 2, "job": {"kind": "workshop", "hk": 5, "recipe": "x"}},       # workshop
            {"tnk": 2, "job": {"kind": "custom", "profit": 1, "cp": 1}},           # custom
            {"tnk": 1, "job": "farming"},                                         # string job, not a dict
        ],
    }

    solver_be, carry_forward, reserved = pipeline._split_base_empire(base_empire)

    assert len(solver_be["userWorkers"]) == 1
    assert solver_be["userWorkers"][0]["job"]["kind"] == "plantzone"
    assert len(carry_forward) == 4
    assert reserved == {"Velia": 2, "Heidel": 2}   # 1 idle + 1 farming at tnk=1, 1 workshop + 1 custom at tnk=2


def test_split_with_no_base_empire_is_a_noop():
    assert pipeline._split_base_empire(None) == (None, [], {})
    assert pipeline._split_base_empire({}) == ({}, [], {})
    assert pipeline._split_base_empire({"userWorkers": []}) == ({"userWorkers": []}, [], {})


def test_split_unmapped_tnk_still_carries_worker_forward_without_reserving_a_bed(monkeypatch):
    monkeypatch.setattr(pipeline, "_tnk_to_town_name", lambda: {})   # nothing maps

    base_empire = {"userWorkers": [{"tnk": 999, "job": None}]}
    solver_be, carry_forward, reserved = pipeline._split_base_empire(base_empire)

    assert carry_forward == [{"tnk": 999, "job": None}]
    assert reserved == {}
