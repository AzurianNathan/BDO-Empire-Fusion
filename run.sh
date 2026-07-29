# BDO Empire Fusion

Fusing [bdo-empire](https://github.com/Thell/bdo-empire) and
[Workerman](https://github.com/shrddr/workermanjs) into a single purpose engine.

Workerman is the worker-empire planner; bdo-empire is a HiGHS-based optimizer that
finds the best empire for a given CP budget. Normally you export prices from one,
run the other as a desktop app, then import the result back. This fuses them: one
local server hosts the Workerman map with an added **Optimize** page, feeds it live
market prices, runs the solver in place, and drops the solved empire straight onto
the map.

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
- **[blackdesertmarket](https://github.com/sobekcore/blackdesertmarket)** for the
  market API this reads prices from.

## Licence and a note on Workerman

This repository is MIT (see `LICENSE`). That covers the server, the node router,
the theme, the Optimize page and the patch scripts.

Workerman itself has **no licence file**, which means all rights are reserved by
its author. That is why this project is built as a patch tool rather than a fork:
nothing of shrddr's is redistributed here, and the build clones directly from the
original repository. If you plan to promote or host this publicly, it is worth
asking shrddr first as a courtesy.

## Architecture

The solving is HiGHS running in Python (solves take minutes to over an hour), so
it can't live in the browser. One local FastAPI process:

1. serves the patched Workerman UI,
2. exposes `/api/prices` (fetched server-side from arsha.io), and
3. exposes `/api/optimize`, calling bdo-empire's solver pipeline directly.

The new **Optimize** page (`/optimize`) reads the map's live prices/modifiers
from its Pinia stores, sends them to the backend, and loads the result back with
the same `migrate()` call the app uses for a saved empire.

## Requirements

- Python >= 3.12
- Node.js >= 18  (only for building the map UI)

## Setup & run

```
python build.py        # sets up the backend, then tries to build the map UI
./run.sh               # macOS/Linux
run.bat                # Windows  (or:  .\run.ps1)
```

Then open http://127.0.0.1:8000/ and click **Optimize** in the top nav.

`python build.py --backend` sets up only the backend (skips the map build).
The backend is always set up first and independently, so `run` works even if the
map build can't complete.

## Two ways to run

**With the map (default).** Optimize is a page in the Workerman map; results
load straight onto it. This now builds with no WASM toolchain, see the node
router section below.

**Without the map (works today, no WASM, no Node build).** If the map isn't
built, `/` serves a self-contained control panel instead. It talks to the same
backend: pull live prices for your region (arsha.io, with Workerman's tax and
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

Verified here:
- Backend venv builds and installs; server boots; all `/api` routes live. ✅
- The standalone panel is served at `/`; `/data/*` files serve; upstream price
  failures return a clean 502. ✅
- Effective-price math ported from Workerman's `prices` getter and unit-tested
  against the real data files (tax, vendor, crafted-from-components). ✅
- Optimizer pipeline runs headlessly; job model runs it to a terminal state. ✅
- **The map UI builds and is served.** `python build.py` completes, the bundle
  contains the router and the Optimize route, the price URLs are rewired, and no
  bdolytics references remain. ✅
- **The JS node router** returns genuinely connected subgraphs on the real map
  (verified independently of the router's own code), reports exact CP, and
  matched proven-optimal MIP solutions on every instance HiGHS solved to
  completion. Edge cases (empty/null input, unknown keys, duplicate sources,
  string keys, unknown options) all handled. See `tests/`. ✅

Confirm on your machine:
- **arsha endpoint**: still not live-tested (the sandbox blocks arsha.io), but the
  fetch now tries four known URL shapes in order and reports which one served the
  prices in the activity log, so first run tells you the answer. Region slugs and
  the versioned path shape were verified against the `bdomarket` package's source.
  Legacy note on the exact call
  (`/v2/{region}/item?id=…`, base level, `basePrice` with `pricePerOne`/
  `lastSoldPrice` fallbacks) couldn't be live-tested. **To verify:** start the
  app, open the panel, click **Fetch live prices**. Success shows an item count;
  failure now prints arsha's actual error in the activity log. If the field
  names differ, adjust the one function `server/app.py` → `_fetch_arsha_base`
  (and `_row_price`). The price-export upload path works regardless.
- **A full solve** with your real prices (the sandbox had no price data and
  solves are slow). Plumbing is proven; only a real end-to-end run isn't.
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
```


## Note on the `bdomarket` PyPI package

`bdomarket` is a maintained Python client for the same arsha.io API. It is **not**
used as a dependency here, for three reasons:

1. **It never sends the region.** `ArshaMarket` stores `_api_region` from its
   `MarketRegion` argument but no request in that class uses it, so every call
   hits `https://api.arsha.io/<endpoint>?lang=..` with no region. On EU you would
   silently get default-region prices.
2. **Licensing.** It is GPL-3.0 (copyleft). `bdo-empire` is Unlicense and
   Workerman is permissive, so adding it would pull the whole fused app into
   GPL-3.0 on distribution.
3. **Weight.** It pulls aiohttp, beautifulsoup4, pillow, tqdm, requests and
   mkdocstrings for what is one HTTP GET here.

What it *was* useful for: its `MarketRegion` enum confirmed the region slugs used
in `REGION_MAP` (na/eu/sea/mena/kr/ru/jp/th/tw/sa/console_*), and its `ApiVersion`
enum (v1/v2) confirmed the versioned path shape. Both now feed the candidate list
in `server/app.py` -> `ARSHA_CANDIDATES`.


## Price sources

Two sources were removed on purpose:

- **arsha.io** - responds, but serves stale (2025-era) data. Stale prices are worse
  than none: the solver optimises happily against them and returns a confidently
  wrong empire.
- **Pearl Abyss' own trade endpoint** - it works, but pricing ~250 items means ~250
  requests per refresh straight at PA. That is the kind of traffic that gets an IP
  or account flagged, and no price data is worth that risk.

That leaves **`blackdesertmarket`** (`api.blackdesertmarket.com`), which fronts the
official market, plus **`custom`** if you want to point at your own endpoint.

Because it is one request per item against a community-run service, the client is
deliberately polite:

- concurrency capped at 5,
- backoff and retry on 429 / 5xx (a rate-limited item is retried, not dropped),
- a 10-minute cache, so opening a page or reloading prices does not re-issue
  hundreds of requests,
- and **coverage is reported honestly**: the source line reads
  `blackdesertmarket (248/248)`, or names the shortfall, e.g.
  `(246/248) - 2 unpriced, valued at 0: 9492, 5205`.

That last point matters. An item that fails to price is valued at **0** by the
solver, which quietly distorts the result, so it is surfaced rather than swallowed.
If you see a shortfall, reload once the cache expires; transient rate limiting
usually clears.

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
progress output is streamed into the panel's Activity log as well as the console:

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
