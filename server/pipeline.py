"""
Headless driver for the bdo-empire optimizer.

This reproduces exactly what bdo_empire.main.EmpireOptimizerApp._optimize_worker
does, but driven by a plain dict of inputs instead of the tkinter GUI + files.
None of the tkinter / customtkinter code is imported, so it runs on a server.

The constants below (optimize_config, solver_config, lodging_specifications) are
copied verbatim from bdo_empire/main.py. If you bump the bdo-empire version,
re-check them against upstream main.py.
"""

from __future__ import annotations

import copy
import json
from math import inf
from pathlib import Path
from typing import Any, Callable, Optional

from bdo_empire.api_common import FARMING_WORKER_SILVER_PER_DAY_KEY
from bdo_empire.generate_reference_data import generate_reference_data
from bdo_empire.generate_graph_data import generate_graph_data
from bdo_empire.optimize_highspy import optimize as optimize_highspy
from bdo_empire.solver_highspy import SolverController
from bdo_empire.generate_workerman_data import generate_workerman_data

HERE = Path(__file__).resolve().parent
_STATIC_DATA = HERE / "static" / "data"

# --- constants copied from bdo_empire/main.py ---------------------------------

OPTIMIZE_CONFIG: dict[str, Any] = {
    "name": "Empire",
    "budget": 0,
    "top_n": 6,
    "nearest_n": 7,
    "max_waypoint_ub": 30,
    "solver_config": {},
}

SOLVER_CONFIG: dict[str, Any] = {
    "mip_rel_gap": 1e-4,
    "mip_feasibility_tolerance": 1e-4,
    "primal_feasibility_tolerance": 1e-4,
    "random_seed": 123456789,
    "time_limit": inf,
    "mip_improvement_timeout": inf,
    "mip_heuristic_run_root_reduced_cost": True,
    "parallel": "on",
    "threads": 0,
    "log_to_console": True,
    "mip_min_logging_interval": 30,
}

# Default (all-zero) purchased-lodging table. Same keys as main.py.
_TOWNS_BONUS_UB = {
    "Velia": 7, "Heidel": 7, "Glish": 6, "Calpheon City": 7, "Olvia": 6,
    "Keplan": 6, "Port Epheria": 5, "Trent": 6, "Iliya Island": 0, "Altinova": 8,
    "Tarif": 6, "Valencia City": 7, "Shakatu": 6, "Sand Grain Bazaar": 5,
    "Ancado Inner Harbor": 0, "Arehaza": 5, "Old Wisdom Tree": 6, "Grána": 7,
    "Duvencrune": 7, "O'draxxia": 9, "Eilton": 6, "Dalbeol Village": 6,
    "Nampo's Moodle Village": 6, "Nopsae's Byeot County": 6, "Asparkan": 5,
    "Muzgar": 5, "Yukjo Street": 5, "Godu Village": 6, "Bukpo": 6,
    "Hakinza Sanctuary": 7,
}


def default_lodging_specifications() -> dict[str, dict[str, int]]:
    return {
        town: {"bonus": 0, "reserved": 0, "prepaid": 0, "bonus_ub": ub}
        for town, ub in _TOWNS_BONUS_UB.items()
    }


# --- base-empire worker carry-forward -------------------------------------------
# bdo-empire's own extract_base_empire() only understands active plantzone-job
# workers (it pins their (plantzone, town) as a solved constraint) and either
# errors on or drops everything else: idle workers (job is None), and
# workshop/custom/farming-job workers, whose `job` dict has no `pzk` key at all.
# The empire -> Workerman export is also rebuilt entirely from the solved graph,
# so even a carried-over worker's real stats/skills/label get replaced by a
# generic profile. See docs/optimizer-feature-proposals.md for the full writeup
# (this mirrors bdo-empire issue #9's proposed fix). Both are fixed here, in our
# own code, without needing any change to the bdo_empire package itself: workers
# bdo-empire can't handle are kept out of what it's given and reattached to the
# result unchanged, with their occupied lodging folded into the town's
# `reserved` count so the solver's own capacity accounting still reflects them.

_tnk_to_town_name_cache: Optional[dict[int, str]] = None


def _tnk_to_town_name() -> dict[int, str]:
    """Map a worker's `tnk` (Workerman's own town-node key) to the English town
    name lodging_specifications is keyed by. Sourced from Workerman's own game
    data (server/static/data/regioninfo.json's waypoint/key pair gives
    tnk -> tk; loc.json's en.town gives tk -> name) since `tnk` is a
    Workerman-domain concept, not something bdo-empire's own reference data
    indexes. Loaded once and cached; these files only change via a rebuild,
    which requires a server restart anyway."""
    global _tnk_to_town_name_cache
    if _tnk_to_town_name_cache is not None:
        return _tnk_to_town_name_cache
    try:
        regioninfo = json.loads((_STATIC_DATA / "regioninfo.json").read_text(encoding="utf-8"))
        town_names = json.loads((_STATIC_DATA / "loc.json").read_text(encoding="utf-8"))["en"]["town"]
    except FileNotFoundError:
        _tnk_to_town_name_cache = {}
        return _tnk_to_town_name_cache
    mapping: dict[int, str] = {}
    for info in regioninfo.values():
        tnk = info.get("waypoint", 0)
        if tnk:
            name = town_names.get(str(info["key"]))
            if name:
                mapping[tnk] = name
    _tnk_to_town_name_cache = mapping
    return mapping


def _split_base_empire(
    base_empire: Optional[dict],
) -> tuple[Optional[dict], list[dict], dict[str, int]]:
    """Split base_empire's userWorkers into what bdo-empire can pin (active
    plantzone jobs) vs everything else, which it silently drops or errors on
    today. Returns (solver_base_empire, carry_forward_workers, reserved_beds)."""
    if not base_empire or not base_empire.get("userWorkers"):
        return base_empire, [], {}

    tnk_to_name = _tnk_to_town_name()
    plantzone_workers: list[dict] = []
    carry_forward: list[dict] = []
    reserved_beds: dict[str, int] = {}
    for worker in base_empire["userWorkers"]:
        job = worker.get("job")
        if isinstance(job, dict) and job.get("kind") == "plantzone" and job.get("pzk") is not None:
            plantzone_workers.append(worker)
        else:
            carry_forward.append(worker)
            town = tnk_to_name.get(worker.get("tnk"))
            if town:
                reserved_beds[town] = reserved_beds.get(town, 0) + 1

    solver_base_empire = {**base_empire, "userWorkers": plantzone_workers}
    return solver_base_empire, carry_forward, reserved_beds


# --- the actual run -----------------------------------------------------------

def run_optimization(
    *,
    budget: int,
    effective_prices: dict[str, float],
    farming_worker_silver_per_day: float,
    modifiers: Optional[dict] = None,
    base_empire: Optional[dict] = None,
    lodging: Optional[dict] = None,
    forced_taken: Optional[list[int]] = None,
    solver_overrides: Optional[dict] = None,
    controller: Optional[SolverController] = None,
    on_start: Optional[Callable[[], None]] = None,
) -> dict:
    """Run the HiGHS empire optimization and return a Workerman-importable dict.

    `effective_prices` and `farming_worker_silver_per_day` come straight from
    Workerman's price export ({"effectivePrices": ..., "farmingWorkerSilverPerDay": ...}).
    `modifiers` is Workerman's regionResources object (may be {}).
    `base_empire` is a Workerman empire export (or None to build from scratch).
    """
    controller = controller or SolverController()

    config = copy.deepcopy(OPTIMIZE_CONFIG)
    config["budget"] = int(budget)
    solver_cfg = copy.deepcopy(SOLVER_CONFIG)
    if solver_overrides:
        solver_cfg.update(solver_overrides)
    config["solver"] = solver_cfg

    # bdo-empire mutates the prices dict; copy so we never corrupt the caller's.
    prices = dict(effective_prices)
    prices[FARMING_WORKER_SILVER_PER_DAY_KEY] = farming_worker_silver_per_day

    modifiers = modifiers or {}
    solver_base_empire, carry_forward, reserved_beds = _split_base_empire(base_empire)

    lodging_specs = lodging or default_lodging_specifications()
    if reserved_beds:
        lodging_specs = copy.deepcopy(lodging_specs)
        for town, count in reserved_beds.items():
            if town in lodging_specs:
                lodging_specs[town]["reserved"] += count
    forced = forced_taken or []

    if on_start:
        on_start()

    data = generate_reference_data(config, prices, modifiers, lodging_specs, forced)
    data = generate_graph_data(data)
    data["base_empire"] = solver_base_empire  # None is valid (from-scratch)

    highs_results = optimize_highspy(data, controller)
    workerman_json = generate_workerman_data(highs_results, lodging_specs, data)
    if carry_forward:
        workerman_json["userWorkers"] = workerman_json.get("userWorkers", []) + carry_forward
    return workerman_json
