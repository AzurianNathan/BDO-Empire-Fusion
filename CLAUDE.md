# CLAUDE.md

Context for working on this repository. Read before changing anything.

## What this is

A local server that fuses two upstream projects into one app:

- **Workerman** (`shrddr/workermanjs`) - the BDO worker-empire planner map, Vue 3 + Vite.
- **bdo-empire** (`Thell/bdo-empire`) - a HiGHS MIP optimizer that picks the best
  empire for a CP budget, Python.

The server hosts the Workerman map, adds an **Optimize** page to it, serves market
prices, runs the solver in-process, and loads the solved empire back onto the map.

**No upstream source is vendored.** `build.py` clones workermanjs onto the machine
and patches it locally; bdo-empire is installed from PyPI. This is deliberate:
workermanjs has no LICENSE file, so it is not ours to redistribute. Keep it that
way. Never commit `workermanjs/`.

## Commands

```bash
python build.py            # clone + patch + build map, install backend
python build.py --backend  # backend + game data only, skips the Node build
./run.sh                   # or run.bat / run.ps1 on Windows
node tests/router_test.mjs # node router against the real game graph
```

Server runs at http://127.0.0.1:8000. Requires Python >= 3.12, Node >= 18.

## Architecture

```
browser ── Workerman map (patched) ──┐
                                     ├─ GET  /api/prices/{lang}/{region}   map's own price store
                                     ├─ POST /api/effective-prices         panel + Optimize page
                                     ├─ POST /api/optimize                 starts a solver job
                                     ├─ GET  /api/optimize/{id}?since=N    status + progress lines
                                     └─ GET  /api/price-status             coverage of last fetch
                        one FastAPI process (server/app.py)
```

- `server/app.py` - everything HTTP: static hosting, prices, jobs, progress capture.
- `server/pipeline.py` - headless driver around bdo-empire's solver. Constants here
  (budget search depth, solver tolerances, lodging table) are copied from upstream
  `bdo_empire/main.py`. **Re-check them when bumping bdo-empire.** So does
  `_split_base_empire`'s worker-classification condition, which mirrors
  `bdo_empire.api_common.extract_base_empire()`'s own undocumented job-shape
  parsing rule rather than a copied constant, and `_match_available_workers`,
  the opt-in post-hoc substitution of real idle workers into newly-solved
  slots (`docs/optimizer-feature-proposals.md` item 2) - re-check both against
  `api_common.py` on a bump too.
- `server/jsondata.py` - tiny cached loader for `server/static/data/*.json`,
  shared by `app.py` and `pipeline.py` so the multi-MB `loc.json` is only ever
  parsed once per process. A separate module because `app.py` imports
  `pipeline.run_optimization` at module load, so `pipeline` importing from
  `app.py` would be circular.
- `patches/apply_patches.py` - rewrites a clean workermanjs checkout. Every edit is
  anchored on an exact string and fails loudly if upstream changed.
- `patches/noderouter.js` - see below, this one matters.
- `server/fallback.html` - standalone panel served at `/` when the map is not built.

## Gotchas that cost real time

Read this section before debugging anything.

### 1. `from __future__ import annotations` masks Pydantic errors as 422

`server/app.py` uses postponed annotations. If a request model class is missing or
misnamed, FastAPI cannot resolve the annotation, silently treats the parameter as a
**query param**, and returns `422 Field required` instead of failing at import.
This bit twice. If an endpoint suddenly 422s on a body it used to accept, check the
model class still exists before anything else.

### 2. The node router: real WASM now, but a validating adapter in front of it

`patches/noderouter.js` replaces `pkg/noderouter.js`, a wasm-pack module upstream
imports but does not ship. It solves a node-weighted Steiner forest (connect each
terminal to its town, paying each node's CP once), which is NP-hard - `99999` as a
destination means "any base town".

It used to be a hand-written pure-JS heuristic (no WASM toolchain needed to build).
As of the router-swap, it wraps a real vendored WASM build of
[Thell/bdo-noderouter](https://github.com/Thell/bdo-noderouter) (Unlicense; a
published Node-Weighted Primal-Dual approximation, not a guess) - see
`patches/pkg-real/`. Rebuild it from source with:
`wasm-pack build --release --target web --features wasm` in a clone of that repo,
then copy `pkg/noderouter.js` and `pkg/noderouter_bg.wasm` into `patches/pkg-real/`.

**Why the adapter exists, not just the raw WASM module:** confirmed by building it
and running it against a real user's empire export whose plantzone keys had
drifted from current game data - the real WASM build **panics (aborts the whole
instance, unrecoverable) on any terminal/root key the graph doesn't know about**.
That's Thell's deliberate design ("fail loud, the caller validates input"), not a
bug he owes a fix for. `patches/noderouter.js` is where that validation has to
live: it filters every pair against the known node set before ever calling into
the WASM. **Do not remove that filtering** - it is the only thing standing between
a stale saved empire and a crashed router.

`game.js` does `new Set(filteredNodes)` and tests membership against `link_list`
entries, which are **Numbers**. `tests/router_test.mjs` asserts this still holds
(the adapter is the layer responsible for it, not the vendored WASM).

### 3. Unpriced items poison crafted prices and used to block solves entirely

Workerman computes crafted prices as `ret[component] * qty`. One unpriced component
makes that `NaN`, `JSON.stringify` sends `null`, and a strict `dict[str, float]`
rejected the **whole** request with a 422. Now: both clients sanitise before
sending, the server drops non-finite values, and the count is reported. Do not
tighten those validators back up without keeping the sanitising.

An unpriced item is valued at **0** by the solver, so coverage is surfaced in
`/api/price-status` and the Optimize page rather than swallowed.

### 4. Price sources: several were tried and rejected before landing on bdolytics

The active source is **bdolytics.com** (`fetch_bdolytics` in `app.py`), an
undocumented internal endpoint (`/api/trpc/market.getMarket`) its own frontend
calls, found by inspecting its network traffic. One request returns the entire
market catalog (thousands of items, all enhancement levels), so pricing our
~250 ids costs a single call, cached 10 minutes. Plain server-side requests get
a normal `200`; CORS is wide open. Verified 2026-07-29: 0 non-vendor items
unpriced against the real ~250-item set.

This was cleared directly with bdolytics's own owner/creator (posting as
"warflash") in the Workerman/BDO tools Discord's `#suggest-a-feature` channel
on 2026-07-29 (asked explicitly: "Are you okay with the application pulling
data off bdolytics as a source, as every other source threw errors or blocked
outright" - confirmed "yeah of course"), so the "undocumented API" caveat is a
technical note, not an open permissions question - this has explicit sign-off
from the source itself, not just a bystander.

Everything else was ruled out, in order:

- **arsha.io** - reachable, but only serves items already warm in its own
  30-minute cache. A fresh lookup for an ordinary material gets `"blocked by
  Imperva"` from PA's own WAF. Verified 2026-07-29: 4/4 base-level material ids
  failed; only a famous, frequently-queried weapon succeeded.
- **Official Pearl Abyss trade API** - removed deliberately. Pricing ~250 items
  means ~250 requests per refresh straight at PA, which risks an IP or account
  ban. **Do not add it back**, even though its `GetWorldMarketSearchList`
  endpoint can batch ids (documented at developers.veliainn.com) - batching
  changes the request-count math but not the "hitting PA directly" risk this
  rule exists to avoid.
- **garmoth.com** - has real, current market data (`/api/trpc/market.getInfo`),
  but it's behind a Cloudflare JS challenge: plain requests get `403`. Getting
  past that is bot-detection bypass and a likely ToS violation. Not worth it.
- **blackdesertmarket** (`api.blackdesertmarket.com`) - was the sole source for
  a while, but died: unreachable (connection refused/timeout) as of 2026-07-29
  from multiple independent networks, not just this dev sandbox. `fetch_bdm`
  is kept in `PROVIDERS` for manual selection/testing but dropped from
  `PROVIDER_ORDER` - its per-item retry math means a dead TCP connection stalls
  a refresh for over an hour if it's ever reached in the auto chain.

If bdolytics ever goes the way of the others: re-run the same triage (`curl` it
directly before touching code, a browser DevTools Network tab on the target
site's own market page usually reveals its internal API even when undocumented,
and always test with a plain `curl`/`httpx` request, not just a browser, since
Cloudflare-gated endpoints look fine in a browser and fail server-side).

### 5. Theming relies on load order

`patches/theme.css` re-themes every page by redefining Workerman's semantic CSS
variables. `base.css` re-defines those same variables inside a
`prefers-color-scheme: dark` block, so the theme **must** be imported after
`main.css` or OS dark mode silently overrides it. `App.vue` uses `<style scoped>`,
which raises specificity via `[data-v-*]`, so nav rules are prefixed `#app` rather
than using `!important`.

## Invariants

- `/api/prices` is what the **patched map** calls. Deleting or breaking it makes the
  map lose prices while the Optimize page still works, which looks like a data bug.
- All price paths go through `fetch_prices()` so the map and optimizer cannot end up
  on different sources.
- The effective-price maths in `compute_effective_prices()` is a direct port of
  Workerman's `prices` getter: custom > api > vendor, then tax (skipped for Keep
  items and vendor items), then crafted items valued from components. Verified
  against the real data files. Change it only with a matching test.

## Verified vs unverified

Verified: the map builds and serves; the router passes against the real 929-node
graph; effective-price maths matches upstream semantics and has a real test suite
(`server/tests/`, run with `pytest` after `pip install -r requirements-dev.txt`);
job progress streams and survives page navigation; `fetch_prices()`'s dispatcher
(named provider, auto-chain, custom-URL validation) and `fetch_bdolytics()`
(region mapping, caching, coverage reporting) are covered by tests with a mocked
HTTP transport, not real network calls.

What the mocked tests *can't* catch: bdolytics.com itself going down or changing
response shape. That only shows up live - check `/api/price-status` after a
reload rather than assuming, and see gotcha #4 above for the full evaluation
trail if it ever needs re-doing.

## Conventions

- Prefer running the code over reasoning about it. Every real bug this project has
  had was caught by executing, not by reading.
- Patch edits are anchored on exact strings and must fail loudly, never silently
  skip, so upstream drift is obvious.
- Docs in this repo avoid em dashes; use commas, colons or separate sentences.
