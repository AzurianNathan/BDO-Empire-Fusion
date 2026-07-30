"""Tests for pipeline.py's base-empire worker carry-forward (see
docs/optimizer-feature-proposals.md item 1 / bdo-empire issue #9): idle and
non-plantzone workers (workshop/custom/farming) used to vanish from a solve's
result because bdo-empire's own extract_base_empire() can't handle them.
"""
import pytest

import jsondata
import pipeline


@pytest.fixture(autouse=True)
def _reset_tnk_cache():
    """_tnk_to_town_name_cache is a module global; without resetting it, a
    test that calls the real (unmocked) function would leak its result into
    a later test that expects a fresh load."""
    pipeline._tnk_to_town_name_cache = None
    yield
    pipeline._tnk_to_town_name_cache = None


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


def test_split_normalizes_legacy_numeric_job_shape_and_pins_it(monkeypatch):
    # Workerman's own jobIsPz() (src/stores/game.js) still treats a bare
    # number as a valid plantzone job pre-migration; without normalizing it
    # here, isinstance(job, dict) would misroute it to carry_forward and the
    # solver would lose the pin, letting it reassign that same plantzone.
    monkeypatch.setattr(pipeline, "_tnk_to_town_name", lambda: {1: "Velia"})

    base_empire = {"userWorkers": [{"tnk": 1, "job": 12345}]}
    solver_be, carry_forward, reserved = pipeline._split_base_empire(base_empire)

    assert carry_forward == []
    assert reserved == {}
    assert solver_be["userWorkers"] == [
        {"tnk": 1, "job": {"kind": "plantzone", "pzk": 12345, "storage": 1}}
    ]


def test_split_handles_base_empire_missing_userworkers_key():
    # A truthy base_empire that simply has no "userWorkers" key (as opposed
    # to an empty list) used to pass straight through unchanged and later
    # KeyError deep inside bdo_empire's extract_base_empire().
    base_empire = {"activateAncado": False}
    solver_be, carry_forward, reserved = pipeline._split_base_empire(base_empire)

    assert solver_be == {"activateAncado": False, "userWorkers": []}
    assert carry_forward == []
    assert reserved == {}


def test_tnk_to_town_name_retries_after_a_failed_load(monkeypatch):
    # item_names() in app.py never caches a failed load, so a later call can
    # retry once the file appears; _tnk_to_town_name() must not freeze to {}
    # forever on the first FileNotFoundError-shaped miss either.
    calls = {"n": 0}

    def flaky_load(name):
        calls["n"] += 1
        if calls["n"] == 1:
            return {}                                   # first call: file missing
        if name == "regioninfo.json":
            return {"1": {"waypoint": 1, "key": 5}}
        return {"en": {"town": {"5": "Velia"}}}

    monkeypatch.setattr(jsondata, "load_static_json", flaky_load)

    assert pipeline._tnk_to_town_name() == {}            # first call fails, not cached
    assert pipeline._tnk_to_town_name() == {1: "Velia"}  # retry succeeds


class TestNormalizeLodgingSpecs:
    def test_no_lodging_returns_full_defaults(self):
        specs = pipeline._normalize_lodging_specs(None)
        assert specs == pipeline.default_lodging_specifications()

    def test_partial_town_dict_is_merged_over_defaults_not_dropped(self):
        # Previously `if town in lodging_specs` silently skipped any town the
        # caller's dict omitted; now every town is always present.
        specs = pipeline._normalize_lodging_specs({"Velia": {"bonus": 2}})
        assert specs["Velia"] == {"bonus": 2, "reserved": 0, "prepaid": 0, "bonus_ub": 7}
        assert specs["Heidel"] == pipeline.default_lodging_specifications()["Heidel"]

    def test_town_missing_reserved_field_does_not_raise(self):
        # Previously lodging_specs[town]["reserved"] += count raised KeyError
        # if the caller's town entry omitted "reserved".
        specs = pipeline._normalize_lodging_specs({"Velia": {"bonus": 2}})
        specs["Velia"]["reserved"] += 1
        assert specs["Velia"]["reserved"] == 1

    def test_unknown_town_in_caller_dict_is_ignored(self):
        specs = pipeline._normalize_lodging_specs({"Not A Real Town": {"bonus": 9}})
        assert "Not A Real Town" not in specs


def test_run_optimization_passes_split_base_empire_and_appends_carry_forward(monkeypatch):
    """Exercises run_optimization's actual wiring (not just the pure helpers):
    the solver only ever sees the plantzone-filtered subset, and carry-forward
    workers are appended to the real result unchanged."""
    captured = {}

    monkeypatch.setattr(pipeline, "generate_reference_data", lambda *a, **k: {"budget": a[0]["budget"]})
    monkeypatch.setattr(pipeline, "generate_graph_data", lambda data: data)

    def fake_optimize_highspy(data, controller):
        captured["base_empire_seen_by_solver"] = data["base_empire"]
        return ("model", "vars")

    monkeypatch.setattr(pipeline, "optimize_highspy", fake_optimize_highspy)
    monkeypatch.setattr(
        pipeline, "generate_workerman_data",
        lambda highs_results, lodging_specs, data: {"userWorkers": [{"tnk": 1, "job": {"kind": "plantzone", "pzk": 1}}]},
    )
    monkeypatch.setattr(pipeline, "_tnk_to_town_name", lambda: {1: "Velia"})

    base_empire = {"userWorkers": [
        {"tnk": 1, "job": {"kind": "plantzone", "pzk": 100}},
        {"tnk": 1, "job": None, "charkey": "999", "label": "Bob"},
    ]}

    result = pipeline.run_optimization(
        budget=100, effective_prices={}, farming_worker_silver_per_day=0,
        base_empire=base_empire,
    )

    assert captured["base_empire_seen_by_solver"]["userWorkers"] == [base_empire["userWorkers"][0]]
    assert result["userWorkers"] == [
        {"tnk": 1, "job": {"kind": "plantzone", "pzk": 1}},
        base_empire["userWorkers"][1],
    ]
