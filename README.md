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
    lodging_specs = lodging or default_lodging_specifications()
    forced = forced_taken or []

    if on_start:
        on_start()

    data = generate_reference_data(config, prices, modifiers, lodging_specs, forced)
    data = generate_graph_data(data)
    data["base_empire"] = base_empire  # None is valid (from-scratch)

    highs_results = optimize_highspy(data, controller)
    workerman_json = generate_workerman_data(highs_results, lodging_specs, data)
    return workerman_json
