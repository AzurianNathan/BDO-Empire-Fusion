"""Tests for the empire storehouse endpoints (/api/empires*)."""
import app as app_module


def _snapshot(name="Test Empire"):
    return {
        "name": name,
        "notes": "some notes",
        "empire": {"userWorkers": [{"tnk": 1, "job": None}]},
        "meta": {"valuePerDay": 100, "cpUsed": 10, "efficiency": 10, "region": "EU", "workerCount": 1},
    }


def test_save_then_list_returns_summary_without_empire_payload(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "EMPIRES_FILE", tmp_path / "empires.json")

    r = client.post("/api/empires", json=_snapshot())
    assert r.status_code == 200
    empire_id = r.json()["id"]

    listed = client.get("/api/empires").json()
    assert len(listed) == 1
    assert listed[0]["id"] == empire_id
    assert listed[0]["name"] == "Test Empire"
    assert listed[0]["meta"]["cpUsed"] == 10
    assert "empire" not in listed[0]   # list is deliberately cheap


def test_get_single_empire_returns_full_payload(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "EMPIRES_FILE", tmp_path / "empires.json")

    empire_id = client.post("/api/empires", json=_snapshot()).json()["id"]

    got = client.get(f"/api/empires/{empire_id}").json()
    assert got["empire"]["userWorkers"] == [{"tnk": 1, "job": None}]


def test_delete_empire(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "EMPIRES_FILE", tmp_path / "empires.json")

    empire_id = client.post("/api/empires", json=_snapshot()).json()["id"]
    assert client.delete(f"/api/empires/{empire_id}").status_code == 200
    assert client.get("/api/empires").json() == []


def test_unknown_empire_id_is_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "EMPIRES_FILE", tmp_path / "empires.json")

    assert client.get("/api/empires/does-not-exist").status_code == 404
    assert client.delete("/api/empires/does-not-exist").status_code == 404


def test_multiple_empires_persist_independently(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "EMPIRES_FILE", tmp_path / "empires.json")

    id_a = client.post("/api/empires", json=_snapshot("Empire A")).json()["id"]
    id_b = client.post("/api/empires", json=_snapshot("Empire B")).json()["id"]

    names = {e["name"] for e in client.get("/api/empires").json()}
    assert names == {"Empire A", "Empire B"}

    client.delete(f"/api/empires/{id_a}")
    remaining = client.get("/api/empires").json()
    assert len(remaining) == 1
    assert remaining[0]["id"] == id_b
