"""Tests for pipeline.py's available-workers post-hoc matching (see
docs/optimizer-feature-proposals.md item 2): substituting a real idle
carry-forward worker's stats into an already-decided solver slot when one of
the same town + archetype (tnk, charkey) is available, without changing which
plantzones were picked or the profit calculation.
"""
import pipeline


def _slot(tnk, charkey, **extra):
    return {
        "tnk": tnk, "charkey": charkey, "label": "default", "level": 40,
        "wspdSheet": 1.0, "mspdSheet": 1.0, "luckSheet": 0.0, "skills": [],
        "job": {"kind": "plantzone", "pzk": 1, "storage": 601},
        **extra,
    }


def _idle_worker(tnk, charkey, **extra):
    return {
        "tnk": tnk, "charkey": charkey, "label": "Bob", "level": 55,
        "wspdSheet": 3.3, "mspdSheet": 2.2, "luckSheet": 10.0, "skills": [123, 456],
        "job": None,
        **extra,
    }


class TestMatchAvailableWorkers:
    def test_matching_town_and_charkey_substitutes_real_stats(self):
        slot = _slot(tnk=1, charkey="7")
        idle = _idle_worker(tnk=1, charkey="7")

        matched, leftover = pipeline._match_available_workers([slot], [idle])

        assert leftover == []
        assert matched[0]["label"] == "Bob"
        assert matched[0]["level"] == 55
        assert matched[0]["wspdSheet"] == 3.3
        assert matched[0]["mspdSheet"] == 2.2
        assert matched[0]["luckSheet"] == 10.0
        assert matched[0]["skills"] == [123, 456]
        # job/tnk/charkey (the actual solved assignment) are untouched.
        assert matched[0]["job"] == slot["job"]
        assert matched[0]["tnk"] == 1
        assert matched[0]["charkey"] == "7"

    def test_different_charkey_at_same_town_does_not_match(self):
        slot = _slot(tnk=1, charkey="7")
        idle = _idle_worker(tnk=1, charkey="9")

        matched, leftover = pipeline._match_available_workers([slot], [idle])

        assert matched == [slot]
        assert leftover == [idle]

    def test_different_town_with_same_charkey_does_not_match(self):
        slot = _slot(tnk=1, charkey="7")
        idle = _idle_worker(tnk=2, charkey="7")

        matched, leftover = pipeline._match_available_workers([slot], [idle])

        assert matched == [slot]
        assert leftover == [idle]

    def test_only_one_idle_worker_available_for_two_matching_slots(self):
        slots = [_slot(tnk=1, charkey="7"), _slot(tnk=1, charkey="7")]
        idle = [_idle_worker(tnk=1, charkey="7", label="Bob")]

        matched, leftover = pipeline._match_available_workers(slots, idle)

        matched_labels = [w["label"] for w in matched]
        assert matched_labels.count("Bob") == 1
        assert matched_labels.count("default") == 1
        assert leftover == []

    def test_no_available_workers_leaves_slots_unchanged(self):
        slot = _slot(tnk=1, charkey="7")
        matched, leftover = pipeline._match_available_workers([slot], [])
        assert matched == [slot]
        assert leftover == []


class TestRunOptimizationMatchAvailableWorkers:
    def _run(self, monkeypatch, base_empire, match_available_workers):
        monkeypatch.setattr(pipeline, "generate_reference_data", lambda *a, **k: {})
        monkeypatch.setattr(pipeline, "generate_graph_data", lambda data: data)
        monkeypatch.setattr(pipeline, "optimize_highspy", lambda data, controller: ("model", "vars"))
        monkeypatch.setattr(
            pipeline, "generate_workerman_data",
            lambda highs_results, lodging_specs, data: {
                "userWorkers": [_slot(tnk=1, charkey="7")],
            },
        )
        monkeypatch.setattr(pipeline, "_tnk_to_town_name", lambda: {1: "Velia"})
        return pipeline.run_optimization(
            budget=100, effective_prices={}, farming_worker_silver_per_day=0,
            base_empire=base_empire, match_available_workers=match_available_workers,
        )

    def test_opt_in_substitutes_idle_worker_into_solved_slot(self, monkeypatch):
        base_empire = {"userWorkers": [
            {"tnk": 1, "job": {"kind": "plantzone", "pzk": 100}},   # solver-pinned, unaffected
            _idle_worker(tnk=1, charkey="7", label="Bob"),
        ]}

        result = self._run(monkeypatch, base_empire, match_available_workers=True)

        # exactly one worker: the solved slot, substituted - the idle worker
        # was consumed by matching, not also appended as carry-forward.
        assert len(result["userWorkers"]) == 1
        assert result["userWorkers"][0]["label"] == "Bob"

    def test_opt_out_leaves_solved_slot_as_median_and_appends_idle_worker_unchanged(self, monkeypatch):
        base_empire = {"userWorkers": [_idle_worker(tnk=1, charkey="7", label="Bob")]}

        result = self._run(monkeypatch, base_empire, match_available_workers=False)

        assert len(result["userWorkers"]) == 2
        labels = [w["label"] for w in result["userWorkers"]]
        assert labels == ["default", "Bob"]

    def test_busy_carry_forward_workers_are_never_matching_candidates(self, monkeypatch):
        # A workshop-job worker is not idle - matching must not pull it off
        # its current job to fill an unrelated plantzone slot.
        base_empire = {"userWorkers": [
            {"tnk": 1, "charkey": "7", "job": {"kind": "workshop", "hk": 5}, "label": "Busy"},
        ]}

        result = self._run(monkeypatch, base_empire, match_available_workers=True)

        labels = [w["label"] for w in result["userWorkers"]]
        assert "Busy" in labels
        assert "default" in labels   # the solved slot was NOT substituted
