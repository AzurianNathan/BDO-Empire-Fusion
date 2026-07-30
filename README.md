# BDO Empire Fusion

Fusing [bdo-empire](https://github.com/Thell/bdo-empire) and
[Workerman](https://github.com/shrddr/workermanjs) into a single purpose engine.

Workerman is the worker-empire planner; bdo-empire is a HiGHS-based optimizer that
finds the best empire for a given CP budget. Normally you export prices from one,
run the other as a desktop app, then import the result back. This fuses them: one
local server hosts the Workerman map with an added **Optimize** page and a new
**Workers** page, feeds it live market prices, runs the solver in place, and drops
the solved empire straight onto the map.

## What is in this repository

Only original work and patch tooling. **No upstream source is vendored here.**
`build.py` clones Workerman from shrddr's repository onto your machine and applies
the patches locally, and installs bdo-empire from PyPI.

```
build.py / build.bat      one-time setup (clone, patch, build, install)
run.sh / run.bat / run.ps1    start the local server
server/
  app.py                  FastAPI: serves the map, prices, optimizer jobs
  pipeline.py             headless driver around bdo-empire's solver
  fallback.html           standalone panel used if the map is not built
patches/
  apply_patches.py        rewires a clean workermanjs checkout
  OptimizeView.vue        the in-map Optimize page
  optimizeJob.js          Pinia store: optimize job state survives page navigation
  WorkersView.vue         the in-map Workers page (add/edit workers by town)
  noderouter.js           pure-JS replacement for the unshipped WASM router
  theme.css               global theme
tests/
  router_test.mjs         node router verified against the real game graph
```

## Credits

- **[shrddr](https://github.com/shrddr/workermanjs)** for Workerman, the map,
  the data pipeline and the planner this is built around.
- **[Thell](https://github.com/Thell/bdo-empire)** for bdo-empire, the optimizer
  doing the actual work.
- **[bdolytics](https://bdolytics.com)** for the market data this reads prices
  from, and for clearing its use here directly with us.

## Licence and a note on Workerman

This repository is MIT (see `LICENSE`). That covers the server, the node router,
the theme, the Optimize/Workers pages and the patch scripts.

Workerman itself has **no licence file**, which means all rights are reserved by
its author. That is why this project is built as a patch tool rather than a fork:
nothing of shrddr's is redistributed here, and the build clones directly from the
original repository. If you plan to promote or host this publicly, it is worth
asking shrddr first as a courtesy.

## Architecture

The solving is HiGHS running in Python (solves take minutes to over an hour), so
it can't live in the browser. One local FastAPI process:

1. serves the patched Workerman UI,
2. exposes `/api/prices` (fetched server-side from bdolytics.com), and
3. exposes `/api/optimize`, calling bdo-empire's solver pipeline directly.

The **Optimize** page (`/optimize`) reads the map's live prices/modifiers from its
Pinia stores, sends them to the backend, and loads the result back with the same
`migrate()` call the app uses for a saved empire. A running solve survives
navigating to another page - job state lives in its own store
(`patches/optimizeJob.js`), not the page component, and the Activity log streams
the solver's real progress lines rather than just start/stop messages.

The **Workers** page (`/workers`) is a standalone, town-by-town worker manager -
add, edit, hire, fire, and send workers for every town from one page instead of
going through the map. It reuses the map's own components and Pinia store, so
it's the same data either way.

## Requirements

- Python >= 3.12
- Node.js >= 18  (only for building the map UI)

## Setup & run

```
python build.py        # sets up the backend, then tries to build the map UI
./run.sh               # macOS/Linux
run.bat                # Windows  (or:  .\run.ps1)
```

Then open http://127.0.0.1:8000/ and use **Optimize** or **Workers** in the top nav.

`python build.py --backend` sets up only the backend (skips the map build).
The backend is always set up first and independently, so `run` works even if the
map build can't complete.

## Two ways to run

**With the map (default).** Optimize and Workers are pages in the Workerman map;
optimize results load straight onto it. This builds with no WASM toolchain, see
the node router section below.

**Without the map (works today, no WASM, no Node build).** If the map isn't
built, `/` serves a self-contained control panel instead. It talks to the same
backend: pull live prices for your region (bdolytics.com, with Workerman's tax and
crafted-value treatment applied server-side), set a CP budget, solve, and
download an `optimized_empire.json` to import into Workerman. You can also load a
Workerman price export for an exact match to your in-game tax/custom prices.
This path only needs `python build.py --backend` (it also fetches the game data)
and then `run`.

## The node router (the old WASM blocker, now solved)

workermanjs imports its node-routing solver from `../pkg/noderouter.js`, a
compiled WASM module shrddr does not publish. Without it the map cannot build:

```
Could not resolve '../pkg/noderouter.js' from src/stores/game.js
```

Because that import is a **JavaScript** wrapper (wasm-bindgen emits JS around the
binary), it can be satisfied by a plain JS module with the same surface, so no
Rust, emscripten, or WASM toolchain is needed. `patches/noderouter.js` is a
from-scratch implementation of `init` + `WasmNodeRouter`
(`setOption`, `solveForTerminalPairs`), installed into `src/pkg/` during patching.

It solves the same problem the original does: node-weighted Steiner forest, that
is, the cheapest set of nodes to activate so every worker reaches its town, with
overlapping routes sharing cost. Base towns are free, and destination `99999`
means "any base town". The method is a shortest-path heuristic with
multi-start ordering and a removal-based pruning pass; `max_frontier_rings`
scales search effort and `max_removal_attempts` bounds pruning, matching the
original's option semantics.

**Accuracy.** Measured against exact optima from a HiGHS multi-commodity-flow
MIP on the real map: on every instance HiGHS solved to proven optimality, this
router matched it exactly (0.0% gap), and on one instance HiGHS could not close
in time it found a 2.4% cheaper answer. Larger cases are heuristic, as the
original also is, so small CP differences from shrddr's build are possible.

**Performance.** ~70 ms for 149 worker/grind pairs, re-solved on every routing
change. Fine for the reactive getter that calls it.

If shrddr ever does publish the real `pkg/`, drop it into `workermanjs/src/pkg/`
and the patcher leaves it alone: a genuine module always wins.

## What was verified vs. what to confirm

Verified here, by actually running the app rather than just reading the code:

- Backend venv builds and installs; server boots; all `/api` routes live.
- The map UI builds and is served; the bundle contains the router and the
  Optimize/Workers routes, and the price URLs are rewired to the local backend.
- Live prices via bdolytics.com: confirmed end-to-end with a running server
  (full catalog fetched in a single request, real current prices, cached
  10 minutes), not just that the endpoint responds.
- A full solve, start to finish, with real prices - not just that the plumbing
  is wired up. Job progress streams into the Activity log, the result loads
  onto the map automatically, and the job survives navigating to another page
  mid-solve.
- The JS node router returns genuinely connected subgraphs on the real map
  (verified independently of the router's own code), reports exact CP, and
  matched proven-optimal MIP solutions on every instance HiGHS solved to
  completion. Edge cases (empty/null input, unknown keys, duplicate sources,
  string keys, unknown options) all handled. See `tests/`.

Confirm on your machine / known gaps:

- **There is no automated test suite for the server** (`server/app.py`) yet -
  price fetching, effective-price math, and the job lifecycle are all verified
  by hand against a live server, not by a `pytest` suite. This is a real gap
  worth closing; contributions welcome.
- **bdolytics.com is an undocumented API** (found by inspecting its own
  frontend's network traffic, not a published integration) - see `CLAUDE.md`
  for the full evaluation trail and what to do if it ever stops working.
- A running optimize job survives navigating to another page in the app, but
  **not a full browser refresh or tab close** - that would need job state
  persisted to `localStorage` and resumed on boot, which isn't built yet.
- At optimize time bdo-empire refreshes its game data from GitHub; needs normal
  internet, degrades gracefully offline.

## Layout

```
build.py / build.bat     one-time setup (cross-platform)
run.sh / run.bat / run.ps1   start the server
server/
  app.py                 FastAPI: static UI + /api/prices + /api/optimize jobs
  pipeline.py            headless driver around bdo-empire's solver
  requirements.txt
patches/
  noderouter.js          pure-JS replacement for the unpublished WASM router
  apply_patches.py       rewires a clean workermanjs checkout
  OptimizeView.vue       the integrated Optimize page
  optimizeJob.js         optimize job state, lives outside the page component
  WorkersView.vue        the integrated Workers page
```

## Price sources

The active source is **bdolytics.com**, an undocumented internal endpoint its own
frontend calls (found by inspecting its network traffic). One request returns the
entire market catalog, so pricing our ~250 tracked items costs a single call,
cached 10 minutes rather than one request per item. Cleared directly with
bdolytics's own owner/creator before shipping.

Several other sources were tried first and ruled out - see `CLAUDE.md` for the
full trail, in short:

- **arsha.io** - reachable, but only serves items already warm in its own cache;
  a fresh lookup for an ordinary material gets blocked by Pearl Abyss' own WAF.
- **Official Pearl Abyss trade API, direct** - works, but pricing ~250 items
  means ~250 requests per refresh straight at PA, which risks an IP or account
  flag. Not worth the risk for price data.
- **garmoth.com** - has real, current data, but sits behind a Cloudflare bot
  challenge that blocks non-browser requests; getting past that is bot-detection
  evasion, which this project won't do.
- **blackdesertmarket** (`api.blackdesertmarket.com`) - was the source for a
  while, but the service itself went down (confirmed unreachable from multiple
  independent networks), not something a patch can fix.

**Coverage is reported honestly** either way: the source line reads
`bdolytics (248/248)`, or names the shortfall, e.g.
`(246/248) - 2 unpriced, valued at 0: 9492, 5205`. An item that fails to price is
valued at **0** by the solver, which quietly distorts the result if swallowed, so
it's surfaced instead. Client-side, prices refresh automatically before each
optimize run only when they're more than 10 minutes stale, instead of on every
single run.

### Why the server log is not enough

A uvicorn access log line like `GET /api/prices/en/EU 200 OK` looks identical
whether 248 or 246 items came back, because a partial fetch is still a successful
response. Coverage is therefore reported separately:

- `GET /api/price-status` returns the source string, the expected item count, and
  the cache age.
- The Optimize page shows it under **Prices**, and turns it red with an explicit
  warning when items are missing.


## Watching a solve

Solves run in the background and can take minutes to over an hour, so the server's
progress output is streamed into the Activity log as well as the console:

```
Generating node weighted directed graph...
  generated graph with 982 nodes and 2190 edges.
  fetching content for plantzone_drops.json
Generating node values...
```

Both `print` output and bdo-empire's loguru messages are captured per job (loguru
needs its own sink because it binds to the original stderr at import). HiGHS itself
logs from C++ below Python's streams, so its iteration output stays in the console;
the stage messages above are what appear in the panel.

The job runs independently of any browser connection - navigate away and back
and the Activity log picks up exactly where it left off, backed by the server's
`GET /api/optimize/{job_id}?since=N` incremental log endpoint.

**Stop** remains available throughout and keeps the best solution found so far.


## Theme

`patches/theme.css` applies the Empire Optimizer look to **every page** of the map,
not just the Optimize view. `build.py` copies it to `src/assets/theme.css` and adds
the import to `src/main.js` after Workerman's own `main.css`.

How it works, in order of preference:

1. **Redefine Workerman's semantic variables** (`--color-background`, `--color-text`,
   `--color-border`, `--color-heading`, ...). `base.css` already drives body,
   headings and borders from these, so most of the app re-themes itself.
2. **Override the few hard-coded values**: the green link colour and the lightgray
   table borders.
3. **Restyle nav, tables and form controls directly.** `App.vue` uses
   `<style scoped>`, which adds a `[data-v-*]` attribute and raises specificity, so
   those rules are prefixed with `#app` to outrank it without `!important`.

Load order matters and is verified in the built bundle: the theme's `:root` lands
after `base.css`'s variables *and* after its `prefers-color-scheme: dark` block, so
the palette holds regardless of OS light/dark preference.

Design notes: serif headings (Iowan Old Style/Georgia), tabular monospace numerals
so figures line up in this table-heavy app, brass underline for the active nav tab,
tight table padding preserved for density, and visible keyboard focus throughout.
To restyle, edit the token block at the top of `theme.css`; everything else is
derived from it.


## The 422 on /api/optimize (fixed)

`POST /api/optimize` could fail validation and the solve would never start. Cause:

Workerman computes crafted-item prices as `ret[component] * qty`. If **any**
component is unpriced, that expression is `NaN`, `JSON.stringify` sends it as
`null`, and a strict `dict[str, float]` rejected the whole request. One bad entry
out of ~270 killed the entire solve, and the access log showed only
`422 Unprocessable Content`.

This is the same root cause as the "not loading everything" symptom: an item that
fails to price poisons every crafted price that depends on it.

Fixes:

- **Server tolerates it.** Non-finite / non-numeric prices are dropped rather than
  rejecting the request, and `farmingWorkerSilverPerDay` falls back to 0.
- **Client sanitises first** (both the map's Optimize page and the standalone
  panel), so bad values are counted before they are sent.
- **The count is reported**, not swallowed: the progress log opens with
  `WARNING: N price(s) were not numbers ... valued at 0 by the solver`.
- **Any future 422 explains itself.** A validation handler logs and returns the
  offending fields, e.g. `body.budget -> Field required`.

Dropped prices still mean those items are valued at 0, so treat a non-zero count as
a signal to reload prices, not as noise.

## Performance

- **Gzip compression** on every response (`server/app.py`). The map's JS bundle
  and its two largest data files (`loc.json`, `all_lodging_storage.json`) were
  being served completely uncompressed - together roughly 7.4 MB uncompressed
  down to about 1.1 MB gzipped.
- **Route-level code-splitting.** Every secondary page (Optimize, Workers,
  Plantzones, Settings, Workshops, ...) is a separately-fetched chunk, loaded
  only when you visit it, rather than all bundled into the page everyone loads
  first. Cuts the main bundle from ~2.3 MB to ~1.5 MB before compression.
