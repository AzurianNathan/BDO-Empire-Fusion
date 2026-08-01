"""Tests for pipeline.py's _label_workers_with_daily_value (shrddr's
suggestion, github.com/Thell/bdo-empire/issues/9): solved plantzone workers
get their solve-time silver/day value as their label instead of the wasted
upstream "default", both as a near-unique identifier and a staleness check.
"""
import pipeline


def _data(affiliated_town_region, plant_values):
    return {"affiliated_town_region": affiliated_town_region, "plant_values": plant_values}


def test_plantzone_worker_gets_value_as_label():
    workerman_json = {"userWorkers": [
        {"tnk": 1, "label": "default", "job": {"kind": "plantzone", "pzk": 100, "storage": 601}},
    ]}
    data = _data({5: 1}, {100: {5: {"value": 6900123.7}}})

    pipeline._label_workers_with_daily_value(workerman_json, data)

    assert workerman_json["userWorkers"][0]["label"] == "6900124"  # rounded


def test_farming_worker_is_left_untouched():
    workerman_json = {"userWorkers": [
        {"tnk": 1, "label": "default", "job": "farming"},
    ]}
    data = _data({5: 1}, {})

    pipeline._label_workers_with_daily_value(workerman_json, data)

    assert workerman_json["userWorkers"][0]["label"] == "default"


def test_idle_or_other_job_worker_is_left_untouched():
    workerman_json = {"userWorkers": [
        {"tnk": 1, "label": "Bob", "job": None},
        {"tnk": 1, "label": "Alice", "job": {"kind": "workshop", "hk": 5}},
    ]}
    data = _data({5: 1}, {})

    pipeline._label_workers_with_daily_value(workerman_json, data)

    assert workerman_json["userWorkers"][0]["label"] == "Bob"
    assert workerman_json["userWorkers"][1]["label"] == "Alice"


def test_missing_plant_value_leaves_default_label_and_warns(capsys):
    workerman_json = {"userWorkers": [
        {"tnk": 1, "label": "default", "job": {"kind": "plantzone", "pzk": 999, "storage": 601}},
    ]}
    data = _data({5: 1}, {})  # no plant_values entry for pzk 999

    pipeline._label_workers_with_daily_value(workerman_json, data)

    assert workerman_json["userWorkers"][0]["label"] == "default"
    assert "could not compute a daily-value label" in capsys.readouterr().out


def test_unmapped_town_leaves_default_label():
    workerman_json = {"userWorkers": [
        {"tnk": 999, "label": "default", "job": {"kind": "plantzone", "pzk": 100, "storage": 601}},
    ]}
    data = _data({5: 1}, {100: {5: {"value": 123}}})  # tnk 999 has no affiliated region

    pipeline._label_workers_with_daily_value(workerman_json, data)

    assert workerman_json["userWorkers"][0]["label"] == "default"


def test_multiple_towns_and_regions_resolve_independently():
    workerman_json = {"userWorkers": [
        {"tnk": 1, "label": "default", "job": {"kind": "plantzone", "pzk": 100, "storage": 601}},
        {"tnk": 2, "label": "default", "job": {"kind": "plantzone", "pzk": 100, "storage": 601}},
    ]}
    data = _data(
        {5: 1, 6: 2},
        {100: {5: {"value": 1000}, 6: {"value": 2000}}},
    )

    pipeline._label_workers_with_daily_value(workerman_json, data)

    assert workerman_json["userWorkers"][0]["label"] == "1000"
    assert workerman_json["userWorkers"][1]["label"] == "2000"


def test_run_optimization_labels_before_matching_so_real_worker_keeps_own_label(monkeypatch):
    """Ordering test: a value-label must not survive on a slot that
    _match_available_workers later fills with a real idle worker."""
    monkeypatch.setattr(pipeline, "generate_reference_data", lambda *a, **k: {})
    monkeypatch.setattr(pipeline, "generate_graph_data", lambda data: data)
    monkeypatch.setattr(pipeline, "optimize_highspy", lambda data, controller: ("model", "vars"))
    monkeypatch.setattr(
        pipeline, "generate_workerman_data",
        lambda highs_results, lodging_specs, data: {
            "userWorkers": [{
                "tnk": 1, "charkey": "7", "label": "default", "level": 40,
                "wspdSheet": 1.0, "mspdSheet": 1.0, "luckSheet": 0.0, "skills": [],
                "job": {"kind": "plantzone", "pzk": 100, "storage": 601},
            }],
        },
    )
    monkeypatch.setattr(pipeline, "_tnk_to_town_name", lambda: {1: "Velia"})

    base_empire = {"userWorkers": [{
        "tnk": 1, "charkey": "7", "label": "Bob", "level": 55,
        "wspdSheet": 3.3, "mspdSheet": 2.2, "luckSheet": 10.0, "skills": [1],
        "job": None,
    }]}

    result = pipeline.run_optimization(
        budget=100, effective_prices={}, farming_worker_silver_per_day=0,
        base_empire=base_empire, match_available_workers=True,
    )

    # matched slot keeps the real worker's own label, not a value-label -
    # generate_reference_data was stubbed to return {} so no plant_values
    # exist and the label pass would leave "default" anyway if matching
    # hadn't overwritten it to "Bob".
    assert result["userWorkers"][0]["label"] == "Bob"
