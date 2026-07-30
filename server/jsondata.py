"""Shared cached loader for server/static/data/*.json files.

app.py's item_names() and pipeline.py's _tnk_to_town_name() both need
loc.json; without a shared cache the multi-MB file gets parsed twice per
process. This is a separate module (not folded into either) because app.py
imports pipeline.run_optimization at module load, so pipeline importing
anything from app.py would be circular.

A file that fails to load (e.g. the server started before build.py finished
populating server/static/data) is not cached, so the next call retries
instead of a startup race permanently disabling whatever depends on it.
"""
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STATIC_DATA = HERE / "static" / "data"

_cache: dict[str, Any] = {}


def load_static_json(name: str) -> Any:
    """Load and cache server/static/data/<name>. Returns {} if the file
    doesn't exist yet (without caching the failure, so a later call retries).

    Prints a warning on a miss rather than failing silently: a missing file
    degrades whatever calls this (e.g. _tnk_to_town_name()'s reserved-bed
    accounting going quietly empty) with no other visible symptom, so this is
    the only place that can flag it.
    """
    if name in _cache:
        return _cache[name]
    try:
        data = json.loads((STATIC_DATA / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"WARNING: {STATIC_DATA / name} not found; run build.py to populate server/static/data. "
              f"Anything depending on {name} will silently see no data until this exists.")
        return {}
    _cache[name] = data
    return data
