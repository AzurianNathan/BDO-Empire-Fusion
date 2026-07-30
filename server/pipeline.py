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
from math import inf
from typing import Any, Callable, Optional

from bdo_empire.api_common import FARMING_WORKER_SILVER_PER_DAY_KEY
from bdo_empire.generate_reference_data import generate_reference_data
from bdo_empire.generate_graph_data import generate_graph_data
from bdo_empire.optimize_highspy import optimize as optimize_highspy
from bdo_empire.solver_highspy import SolverController
from bdo_empire.generate_workerman_data import generate_workerman_data

import jsondata

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


def _normalize_lodging_specs(lodging: Optional[dict]) -> dict[str, dict[str, int]]:
    """Merge a caller-supplied `lodging` (OptimizeRequest.lodging is an
    unvalidated Optional[dict]) over the full default table, town by town and
    field by field, rather than trusting its shape. A caller sending a partial
    town or one missing a field (e.g. {"Velia": {"bonus": 2}}) would otherwise
    either silently drop reserved-bed accounting for towns it omits, or raise
    KeyError on `["reserved"] +=` for a town missing that field."""
    specs = default_lodging_specifications()
    if not lodging:
        return specs
    for town, spec in lodging.items():
        if town in specs and isinstance(spec, dict):
            specs[town] = {**specs[town], **spec}
    return specs


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
#
# `_split_base_empire`'s classification condition mirrors extract_base_empire's
# own undocumented parsing rule (a dict job with a `pzk` key is pinnable,
# anything else is skipped/errored) rather than an official copied constant, so
# it carries the same "re-check on bump" risk as OPTIMIZE_CONFIG/SOLVER_CONFIG
# above: if a bdo-empire version bump changes what extract_base_empire() accepts,
# this condition goes stale silently. Re-check it against api_common.py's
# extract_base_empire() whenever bdo-empire is bumped, same as the constants.

_tnk_to_town_name_cache: Optional[dict[int, str]] = None


def _tnk_to_town_name() -> dict[int, str]:
    """Map a worker's `tnk` (Workerman's own town-node key) to the English town
    name lodging_specifications is keyed by. Sourced from Workerman's own game
    data (server/static/data/regioninfo.json's waypoint/key pair gives
    tnk -> tk; loc.json's en.town gives tk -> name) since `tnk` is a
    Workerman-domain concept, not something bdo-empire's own reference data
    indexes. Loaded once and cached; these files only change via a rebuild,
    which requires a server restart anyway. Not cached on failure (e.g. server
    started before build.py finished populating server/static/data), so a
    later call can retry once the files exist."""
    global _tnk_to_town_name_cache
    if _tnk_to_town_name_cache is not None:
        return _tnk_to_town_name_cache
    regioninfo = jsondata.load_static_json("regioninfo.json")
    town_names = jsondata.load_static_json("loc.json").get("en", {}).get("town", {})
    if not regioninfo or not town_names:
        return {}
    mapping: dict[int, str] = {}
    for info in regioninfo.values():
        tnk = info.get("waypoint", 0)
        if tnk:
            name = town_names.get(str(info["key"]))
            if name:
                mapping[tnk] = name
    _tnk_to_town_name_cache = mapping
    return mapping


def _normalize_worker_job(worker: dict) -> dict:
    """Normalize the legacy pre-migration job shape (a bare plantzone id
    number, per Workerman's own jobIsPz()/migrate() in src/stores/game.js and
    user.js) into the {kind, pzk, storage} dict shape both bdo-empire and the
    rest of this module expect. The live Vue UI always runs userStore.migrate()
    before a solve is reachable, so this only matters for a direct API caller
    or an unmigrated snapshot - but base_empire has no schema enforcing it, so
    without this a legacy-shaped worker silently loses its solver pin instead
    of being recognized as an active plantzone job."""
    job = worker.get("job")
    if isinstance(job, (int, float)) and not isinstance(job, bool):
        return {**worker, "job": {"kind": "plantzone", "pzk": int(job), "storage": worker.get("tnk")}}
    return worker


def _split_base_empire(
    base_empire: Optional[dict],
) -> tuple[Optional[dict], list[dict], dict[str, int]]:
    """Split base_empire's userWorkers into what bdo-empire can pin (active
    plantzone jobs) vs everything else, which it silently drops or errors on
    today. Returns (solver_base_empire, carry_forward_workers, reserved_beds)."""
    if not base_empire:
        return base_empire, [], {}
    if not base_empire.get("userWorkers"):
        # A truthy base_empire lacking "userWorkers" entirely (as opposed to an
        # empty list) would otherwise reach bdo_empire's extract_base_empire(),
        # which does an unguarded base_empire["userWorkers"] and KeyErrors.
        return {**base_empire, "userWorkers": []}, [], {}

    tnk_to_name = _tnk_to_town_name()
    plantzone_workers: list[dict] = []
    carry_forward: list[dict] = []
    reserved_beds: dict[str, int] = {}
    for raw_worker in base_empire["userWorkers"]:
        worker = _normalize_worker_job(raw_worker)
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


# --- available-workers post-hoc matching -----------------------------------------
# See docs/optimizer-feature-proposals.md item 2. The solver's objective is
# built entirely from an idealized median-worker profile per (plantzone,
# region); base_empire only pins topology, never reaches the objective. So
# once the solver has decided which (terminal, root) slots to fill, this
# substitutes a real idle carry-forward worker's stats into an already-decided
# slot when one of the exact same town + archetype (tnk, charkey) is
# available. It deliberately does NOT change which nodes were picked, the
# lodging/capacity accounting, or the profit calculation - only which worker
# (real vs. synthesized median) is shown filling that slot. Matching on exact
# (tnk, charkey) rather than a looser "same species" notion is a deliberate
# simplification: charkey already encodes a per-region worker archetype (see
# bdo_empire's region_workers.json / makeMedianChar()), so an idle worker's
# charkey only ever equals a solved slot's charkey when they're genuinely
# interchangeable, without needing to load bdo-empire's internal worker-type
# tables here.

_WORKER_PROFILE_FIELDS = ("label", "level", "wspdSheet", "mspdSheet", "luckSheet", "skills")


def _match_available_workers(
    solved_workers: list[dict],
    available_workers: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Returns (solved_workers_with_substitutions, leftover_available_workers)."""
    pool: dict[tuple, list[dict]] = {}
    for worker in available_workers:
        pool.setdefault((worker.get("tnk"), worker.get("charkey")), []).append(worker)

    matched: list[dict] = []
    for slot in solved_workers:
        bucket = pool.get((slot.get("tnk"), slot.get("charkey")))
        if bucket:
            real = bucket.pop()
            matched.append({**slot, **{f: real[f] for f in _WORKER_PROFILE_FIELDS if f in real}})
        else:
            matched.append(slot)

    leftover = [worker for bucket in pool.values() for worker in bucket]
    return matched, leftover


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
    match_available_workers: bool = False,
    controller: Optional[SolverController] = None,
    on_start: Optional[Callable[[], None]] = None,
) -> dict:
    """Run the HiGHS empire optimization and return a Workerman-importable dict.

    `effective_prices` and `farming_worker_silver_per_day` come straight from
    Workerman's price export ({"effectivePrices": ..., "farmingWorkerSilverPerDay": ...}).
    `modifiers` is Workerman's regionResources object (may be {}).
    `base_empire` is a Workerman empire export (or None to build from scratch).
    `match_available_workers` opts into substituting real idle base-empire
    workers into newly-solved slots where a compatible one is available - see
    docs/optimizer-feature-proposals.md item 2 / `_match_available_workers`.
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

    lodging_specs = _normalize_lodging_specs(lodging)
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

    if match_available_workers and carry_forward:
        idle = [w for w in carry_forward if w.get("job") is None]
        busy = [w for w in carry_forward if w.get("job") is not None]
        matched_workers, leftover_idle = _match_available_workers(
            workerman_json.get("userWorkers", []), idle
        )
        workerman_json["userWorkers"] = matched_workers
        carry_forward = leftover_idle + busy

    if carry_forward:
        workerman_json["userWorkers"] = workerman_json.get("userWorkers", []) + carry_forward
    return workerman_json
