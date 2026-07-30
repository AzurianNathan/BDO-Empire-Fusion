# Proposed solutions: worker export gap, available-workers optimization, empire storehouse

Follow-up to the `#dev-talk` conversation with Thell and shrddr's issues on
`Thell/bdo-empire` (#9, #11). Covers concrete solutions for the worker-export
gap and available-workers optimization, plus a pointer to the separate
storehouse plan.

## Ordering matters: do the export fix first

The export fix (below) produces exactly the data available-workers
optimization needs (a list of the user's real idle workers). Building it
first isn't just lower-risk, it's a prerequisite for building the second
thing well.

## 1. Fix the worker-export gap (issue #9)

**Root cause, confirmed by reading `bdo_empire`'s actual source:**
- `api_common.py`'s `extract_base_empire()` skips (and logs an error for)
  any `base_empire["userWorkers"]` entry whose `job` is `None` — idle/reserved
  workers vanish before they can even be considered.
- `generate_workerman_data.py`'s `generate_workerman_workers()` rebuilds the
  *entire* output `userWorkers` list from the solved graph, using the
  idealized median-worker profile for every entry. It never copies forward
  an original `base_empire` worker object — so even a worker whose
  plantzone assignment carries over loses their real `label`/`level`/
  `skills`/stats to the generic profile on every re-export.

**Proposed fix — entirely in our own `server/pipeline.py`, no changes needed
to `bdo_empire` itself:**

Before calling into the solver, split `base_empire["userWorkers"]` into two
groups:

- **Plantzone-job workers** (`job.kind == "plantzone"`) — pass to
  `bdo_empire` exactly as today; this is the only case its topology-pinning
  logic understands.
- **Everything else** (`job is None`, or `job.kind` is `workshop`/`custom`/
  `farming`) — `bdo_empire` has no way to reason about these. Instead of
  handing them in and having them silently dropped, keep them out entirely
  and reattach them to the *final* result's `userWorkers` list, unchanged,
  after the solve completes. This is exactly shrddr's proposed behavior in
  issue #9: "these do not need to be parsed, but just piped without changes
  to the output json."

The one thing this needs to get right: **lodging accounting.** These workers
still occupy beds. `bdo_empire` already has the machinery for this —
`lodging_specifications[town]["reserved"]` subtracts a per-town count from
the solver's own capacity ceiling before it solves, and it's already wired
end-to-end from `OptimizeRequest.lodging` through to
`generate_reference_data()`. So: before solving, count how many carried-
through workers occupy beds in each town and fold that into the `reserved`
count for that town, using the exact schema `bdo_empire` already expects
(`{"bonus": 0, "reserved": N, "prepaid": 0, "bonus_ub": ...}`). No new
capacity-accounting logic needed — just correctly populating a field that
already exists and already works, but that this project's UI has never
actually sent.

```
run_optimization(..., base_empire, lodging, ...):
    plantzone_workers, carry_forward = split(base_empire.userWorkers)
    lodging = add_reserved_beds(lodging, carry_forward)   # per town, by tnk
    result = <existing solve, using only plantzone_workers as base_empire>
    result.userWorkers += carry_forward                    # unchanged, real stats intact
    return result
```

**Known unknown, needs verifying before implementing:** `bdo_empire`'s
`lodging_specifications` appears to be keyed by town *name* (e.g.
`"Calpheon"`), while a worker's `tnk` is a numeric town-node key. Need to
confirm the exact mapping available in `server/pipeline.py` (there's
precedent — `_TOWNS_BONUS_UB` already keys by some town identifier) before
this is a clean drop-in rather than a guess.

**Nice-to-have, not required for the fix:** issue #9 also points out the
`label` field is wasted (`"default"` on every worker) and could carry a
short job description, skill shorthand, or the M$/day value at solve time.
Worth doing in the same pass since it touches the same code, but it's
cosmetic — separable if time is short.

**Scope/effort:** small. A self-contained addition to `server/pipeline.py`
(rough estimate: 30-60 lines), reusing already-tested upstream machinery
rather than adding new capacity math. Ships immediately, doesn't wait on a
`bdo-empire` release.

## 2. Available-workers optimization (issue discussed in `#dev-talk`)

**What's actually true today, confirmed by reading `optimize_highspy.py` and
`generate_value_data.py`:** the solver's objective is built entirely from a
precomputed *idealized median worker* per (plantzone, region) — averaged
stat-growth ranges, cached, computed once, with zero connection to any real
worker a user has hired. `base_empire` only pins *topology* (which
plantzone/town pairs were already occupied) as hard constraints; it never
reaches the objective.

**The honest scope split:**

- **What we can build in this project alone:** a post-hoc matching step.
  Once the solver has decided which `(terminal, root)` pairs to fill, check
  whether the user has a real idle worker (the same "carry-forward" bucket
  from the export fix above) of a compatible type sitting available, and
  substitute their real record in place of the synthesized median-worker
  record for that slot. This uses real stats/skills where possible, but
  **does not change which nodes get picked or the profit calculation** —
  the solver still decides the empire's shape using idealized numbers. It
  only affects *which worker* (yours vs. a fresh hire) ends up filling an
  already-decided slot. Proposed as opt-in (a checkbox, matching the
  existing "Extend current empire" pattern), since a substitution could
  come with a small profit difference the user should knowingly accept.
- **What genuinely requires changing `bdo_empire` itself:** having the
  solver *choose* nodes differently because of which real workers you have
  is a structural change to the MIP - the assignment model is currently
  anonymous (no worker-identity dimension at all), and the objective's
  per-node values are precomputed offline for generic archetypes, not
  available per-instance during a live solve. The profit-calculation
  building blocks for a real worker already exist and are reusable
  (`worker_stats()`/`profit()` in `generate_value_data.py`), which helps,
  but wiring them into live per-solve decisions is `bdo_empire`'s own
  architecture to change, not something patchable from outside the package.

**Recommendation:** build the post-hoc matching step (small, ships now,
directly reuses the export fix's data), and raise the deeper "solver
actually reasons about your real workers" version with Thell as a
`bdo_empire` issue/PR conversation rather than attempting to reimplement his
MIP from the fused-app side. Worth running the post-hoc matching heuristic
by Thell/shrddr before building, too - neither of us has their depth on
whether "prefer an existing idle worker over a fresh hire when close enough"
is actually sound given real game economics, or has sharp edges we're not
seeing.

**Scope/effort:** small-to-medium for the post-hoc matching step (server-side
matching logic plus one new checkbox on the Optimize page); the deeper fix
is out of scope for this project and belongs upstream.

## 3. Empire storehouse

Already fully scoped in a separate document:
[`docs/empire-storehouse-plan.md`](./empire-storehouse-plan.md). Short
recap: a saved list of empire snapshots (name, date, CP, value/day, region,
notes) with save/list/load/delete, recommended as server-backed (flat JSON
on the local server, not just browser localStorage) since the actual
complaint was about durability/juggling files across environments, not just
"it gets overwritten." That document also has its own open questions for
Thell (two ambiguous fields in the data-model split) worth resolving
alongside these two.

## Suggested order

1. Worker-export fix (#1 above) - smallest, self-contained, no upstream
   dependency, and produces the data the next item needs.
2. Empire storehouse - independent of the other two, can happen in parallel.
3. Available-workers post-hoc matching - builds directly on the export fix's
   carry-forward worker list.
4. Raise the deeper available-workers MIP change with Thell as its own
   `bdo_empire` conversation, once 1 and 3 are live and battle-tested.
