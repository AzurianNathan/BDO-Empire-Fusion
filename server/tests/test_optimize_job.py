"""Tests for the /api/optimize job lifecycle: creation, status polling with
since/cursor, and stop - with the real (multi-minute) solver replaced by a
fast fake so these run in well under a second.
"""
import time

import app as app_module


def _wait_for_terminal_status(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/optimize/{job_id}").json()
        if status["status"] in ("done", "stopped", "error"):
            return status
        time.sleep(0.02)
    raise AssertionError(f"job never reached a terminal status: {status}")


def test_optimize_job_runs_to_completion(client, monkeypatch):
    monkeypatch.setattr(app_module, "run_optimization",
                        lambda **kwargs: {"empire": "fake-result", "value": 12345})

    r = client.post("/api/optimize", json={"budget": 100})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    status = _wait_for_terminal_status(client, job_id)

    assert status["status"] == "done"
    assert status["result"] == {"empire": "fake-result", "value": 12345}
    assert any("budget 100" in line for line in status["lines"])


def test_optimize_since_cursor_returns_only_new_lines(client, monkeypatch):
    monkeypatch.setattr(app_module, "run_optimization", lambda **kwargs: {"ok": True})

    job_id = client.post("/api/optimize", json={"budget": 50}).json()["job_id"]
    first = _wait_for_terminal_status(client, job_id)

    # Re-polling with since=cursor from the already-finished job should come
    # back with no new lines and the same cursor - this is exactly the
    # contract the frontend's optimizeJob store relies on to resync after
    # navigating away and back mid-solve.
    second = client.get(f"/api/optimize/{job_id}", params={"since": first["cursor"]}).json()

    assert second["lines"] == []
    assert second["cursor"] == first["cursor"]


def test_optimize_reports_dropped_price_count(client, monkeypatch):
    monkeypatch.setattr(app_module, "run_optimization", lambda **kwargs: {"ok": True})

    job_id = client.post("/api/optimize", json={
        "budget": 10, "droppedPrices": 3,
    }).json()["job_id"]
    status = _wait_for_terminal_status(client, job_id)

    assert any("3 price(s) were not numbers" in line for line in status["lines"])


def test_optimize_job_error_is_reported_not_raised(client, monkeypatch):
    def boom(**kwargs):
        raise ValueError("solver exploded")
    monkeypatch.setattr(app_module, "run_optimization", boom)

    job_id = client.post("/api/optimize", json={"budget": 10}).json()["job_id"]
    status = _wait_for_terminal_status(client, job_id)

    assert status["status"] == "error"
    assert "solver exploded" in status["error"]


def test_optimize_unknown_job_id_is_404(client):
    assert client.get("/api/optimize/does-not-exist").status_code == 404
    assert client.post("/api/optimize/does-not-exist/stop").status_code == 404


def test_optimize_requires_budget(client):
    r = client.post("/api/optimize", json={})
    assert r.status_code == 422
