# Empire Storehouse — design plan

## Problem

Right now there is exactly one "current empire." Every time a solve finishes or
a file is imported, `userStore.migrate()` patches the live Pinia store in
place. There is no history: solve a second empire and the first one is gone
unless you'd separately exported it. Comparing two candidate builds, or
finding "the one I liked from last week," isn't possible today.

This documents a plan for a **storehouse**: a saved list of empire snapshots,
each carrying metadata (name, date, CP budget, value/day, region, notes), that
you can save to, browse, reload, delete, and export/import individually.

## Current data model (as it actually is today, not as documented)

The `user` Pinia store (`workermanjs/src/stores/user.js`) has 32 top-level
state fields. For a storehouse to work, they split into two groups:

**Empire-specific** (output of a solve / manual build, should be captured in a
snapshot and restored on load): `userWorkers`, `lodgingP2W`, `lodgingTaken`,
`activateAncado`, `grindTakenList`, `farmingEnable`, `farmingProfit`,
`farmingBareProfit`, `farmingP2WShare`, `userWorkshops`, `palaceEnable`,
`palaceProfit`, `tradeDestinations`, `tradeRouteAlwaysOn`, `tradeInfraCp`,
`tradeRouteCp`.

**Global preference** (account/UI state, should survive a snapshot load
untouched): `selectedLang`, `selectedRegion`, `selectedTax`, `customPrices`,
`keepItems`, `regionResources`, `regionResources2`, `allowFloating`,
`useFloatingResources`, `storageVP`, `useDefaultWorker`, `defaultWorker`,
`defaultUserWorkshop`, all five `display*` toggles, `mapHideInactive`,
`mapIconSize`, `wasmRouting`, `linkOrder`, `wasm`, `tradingLevel`.

**Ambiguous — worth your call, Thell:** `storageP2W` and `storagePersonal`
represent purchased/personal storage capacity. They read more like an account
fact than a specific empire's output, and the existing export function agrees
(it doesn't include them either) — this plan treats them as global preference,
but flag it if your workflow treats storage capacity as something that varies
per build.

**Dead field:** `houseTaken` is declared in state but nothing reads or writes
it anywhere in the codebase (not in `migrate()`, not in any getter, not in the
existing export). Ignore it; it looks like leftover cruft distinct from the
actually-used `lodgingTaken`.

### The existing export is already stale

`HomeView.vue`'s `fileExport()` only serializes 8 fields: `activateAncado`,
`lodgingP2W`, `lodgingTaken`, `userWorkers`, `farmingEnable`, `farmingProfit`,
`farmingBareProfit`, `grindTakenList`. It predates workshops, palace, and
trade routes and was never updated — exporting today silently drops all of
that. The storehouse snapshot shape below is a superset that closes this gap;
worth fixing the existing export to match rather than leaving two diverging
definitions of "one empire" in the codebase.

### `migrate()` is a merge, not a replace — this works in our favor

`userStore.migrate(jsonString)` ends in `this.$patch(parsed)`. Pinia's
`$patch(obj)` only overwrites keys present in `obj`; global-preference fields
absent from a snapshot are left alone automatically. We don't need a separate
"restore only these keys" mechanism — a snapshot containing only the
empire-specific fields, patched in, already leaves preferences untouched.

**One real gotcha:** `migrate()` also contains one-off back-compat renames
(`townSlotsP2W` → `lodgingP2W`, `grindTaken` → `grindTakenList`, etc.), and if
any of those fire it does `localStorage.setItem('user', ...)` as a side
effect — silently overwriting the live current-empire localStorage key. If a
saved snapshot is old enough to contain any legacy field name, reusing
`migrate()` to load it would have this side effect. The storehouse's load
path should call `$patch()` directly rather than going through `migrate()`,
or explicitly guard against this.

### What the solver actually hands back

`server/pipeline.py`'s `run_optimization()` returns
`bdo_empire.generate_workerman_data`'s output directly — a purpose-built
dict already shaped like `{activateAncado, lodgingP2W, userWorkers,
farmingEnable, farmingProfit, farmingBareProfit, grindTakenList}`. It's not a
raw solver structure needing transformation; it's 7 of the same 8 fields the
existing export uses (missing only `lodgingTaken`, since the solver decides
bonus lodging *counts*, not which specific houses are bought). This is good:
the solver's result and a storehouse snapshot's empire-data are already the
same shape family.

### No existing storage infra to build on

Every persistence call in the app is `localStorage.setItem(key,
JSON.stringify(x))` — no IndexedDB anywhere, no compression, no quota
handling (zero `try/catch` around any of the 27 `setItem` call sites in the
codebase). A storehouse introduces the first "structured local database"
need this app has had.

**Rough size math:** one worker serializes to ~235 bytes. Total lodging
capacity across all towns tops out around 450-700 workers at absolute
maximum, so a maxed-out single empire is roughly 100-165 KB. Comfortably
inside a browser's localStorage quota (typically 5-10 MB) for a handful of
saves, but this is a real, known ceiling, not a hypothetical one — see
Limitations.

## Proposed snapshot shape

```js
{
  id: "uuid",
  name: "user-provided label",
  savedAt: "2026-07-30T18:00:00Z",
  meta: {
    budget: 500,           // CP budget it was solved for, if known
    region: "RU",
    valuePerDay: 73952100,
    workerCount: 13,
    cpUsed: 34,
    notes: "",              // free text
  },
  empire: {
    activateAncado, lodgingP2W, lodgingTaken, userWorkers,
    farmingEnable, farmingProfit, farmingBareProfit, farmingP2WShare,
    grindTakenList, userWorkshops, palaceEnable, palaceProfit,
    tradeDestinations, tradeRouteAlwaysOn, tradeInfraCp, tradeRouteCp,
  },
}
```

## The architectural fork: client-only vs. server-backed

This is the real decision, and it changes the rest of the design:

**A. Client-only (browser localStorage).** A new key (e.g.
`localStorage['empireStorehouse']`) holding an array of snapshots. No backend
changes at all — a new Pinia store plus UI. Simple, fast to build, consistent
with how everything else in this app already persists.
*Limitation:* tied to one browser profile on one machine. Clearing site data,
switching browsers, or moving to another PC loses the whole storehouse.
Doesn't address "juggling files across environments" if that's the actual
pain — it just stops the *overwriting*, not the *machine-boundness*.

**B. Server-backed (flat JSON on disk, new `/api/empires*` endpoints).** The
already-running local FastAPI server gains a small persistence layer — either
one `server/empires.json` holding a list, or one file per snapshot under a
new `server/empires/` directory. Durable independent of the browser; if the
server runs on a machine you always leave on, the storehouse is reachable
from any browser hitting it. No new dependency (still just `json.dump`/`json
.load`, matching how the rest of this project already treats data as flat
files — no SQLite, no ORM).
*Limitation:* it's still "your one local server," not multi-device/cloud
sync in any real sense — durability improves, but nothing here makes it
reachable outside your own network unless the server itself is already
exposed that way (which CLAUDE.md's own security notes argue against doing
casually).

**Recommendation: B.** Given the actual complaint was about juggling files
across a WSL-based setup, and given this project's own philosophy (server
holds the state of record; the browser is a client of it, matching how
prices already flow through the server, not the browser), a durable
server-side store fits the existing architecture and solves the actual
problem better than a browser-locked list would. It also composes with
export/import for free (a saved snapshot IS already the JSON shape the
existing file-import path expects).

## Sketch: server-backed design

**New backend (`server/app.py` or a new `server/empires.py`):**
- `GET /api/empires` → list of `{id, name, savedAt, meta}` (no `empire` payload,
  keeps the list cheap to load)
- `POST /api/empires` → body is the full snapshot (minus `id`/`savedAt`,
  server assigns both), appended to `server/empires.json`
- `GET /api/empires/{id}` → full snapshot including `empire` payload
- `DELETE /api/empires/{id}`
- `PATCH /api/empires/{id}` → rename / edit notes without resaving the whole
  empire

**Frontend:**
- A "Save empire" action wherever the empire is currently displayed (map
  page and/or Optimize page), prompting for a name, POSTing the current
  empire-specific fields (see split above) plus computed `meta` (from
  existing getters: `userStore.allJobsTotalDailyProfit`, `userStore.totalCP`,
  `userStore.userWorkers.length`, `userStore.selectedRegion`).
- A new page/section listing saved empires (name, date, value/day, CP,
  region, notes), each with **Load** (fetches the full snapshot, `$patch()`s
  `empire` onto the store — not `migrate()`, per the gotcha above), **Delete**,
  **Rename**, and **Export** (downloads that one snapshot's `empire` field as
  the same JSON shape the existing file-import already accepts, so nothing
  new is needed on that side).

## Limitations and open questions

- **No versioning story yet.** If the empire-specific field list changes in a
  future version of this app (a new feature adds a new field the way
  workshops/palace/trading did to the stale export), old snapshots simply
  won't have that field — which is fine going forward (`$patch()` just
  leaves it at whatever the current default is) but there's no migration
  path for reshaping *old saved snapshots* the way `migrate()` does for the
  single current-empire localStorage key. Worth deciding whether saved
  snapshots need their own lightweight version tag.
- **No dedup / cap.** Nothing stops someone from saving the same empire 50
  times, or saving until the flat file(s) get unwieldy. A sane starting cap
  (a warning past N saves, or "prune anything you haven't renamed past its
  default budget-name") is recommended rather than unbounded growth.
- **Single-user file, no locking.** `server/empires.json` written from a
  single local process is fine for one person; if this server is ever run
  multi-user/shared, concurrent writes need real locking, which doesn't
  exist today anywhere else in this codebase either (see `_JOBS`'s
  `threading.Lock` for the closest existing precedent).
- **The ambiguous fields above** (`storageP2W`/`storagePersonal`) are a
  judgment call this plan makes one way; flag if that's wrong for how you
  actually use them.
- **Doesn't fix the underlying per-mutation localStorage write** the rest of
  the app does today (every single userStore mutation re-serializes and
  writes the *entire* current-empire state) — that's pre-existing, unrelated
  debt, not something this feature needs to touch, but worth knowing it's
  there if performance ever becomes a question on very large empires.

## Phased plan

**Phase 1 (MVP):** server-backed storage exactly as sketched above — save
current, list, load, delete. No rename/export yet.

**Phase 2:** rename/notes editing, per-snapshot export (reusing the existing
import path on the other end), a size/count cap with a clear message when
hit.

**Phase 3 (only if wanted):** side-by-side comparison view (value/day, CP,
worker count across two or more saved snapshots) — this is genuinely useful
for "which of these builds is actually better" but is new UI, not just
plumbing, so it's scoped separately rather than bundled into the MVP.

## Effort estimate

Phase 1 is comparable in size to the Workers page built earlier in this
project (new backend endpoints + a new Pinia store + a new UI section) — a
similar-scoped, single implementation pass once the field classification
above is confirmed.
