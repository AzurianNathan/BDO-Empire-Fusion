#!/usr/bin/env python3
"""
Rewire a clean workermanjs checkout into the fused app.

Verified-exact edits (fail loudly if upstream changes):
  1. src/stores/market.js  - price fetch      -> local /api/prices
  2. src/stores/user.js    - marketUrl getter -> local /api/prices
  3. vite.config.js        - base '/workerman/' -> '/'
  4. src/router/index.js   - import + register the /optimize, /workers, /storehouse routes
  5. src/App.vue           - add the Optimize, Workers, and Storehouse nav links
  6. copy OptimizeView.vue into src/views/
  7. copy optimizeJob.js into src/stores/
  8. copy WorkersView.vue into src/views/
  9. copy empireStorehouse.js into src/stores/
  10. copy StorehouseView.vue into src/views/
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path("workermanjs")
PATCH_DIR = Path(__file__).resolve().parent


def edit(path: Path, old: str, new: str, marker: str | None = None) -> None:
    """Replace `old` with `new`. `marker` is the text that proves the edit was
    already applied; it defaults to `new`, but must be given whenever `old` is a
    substring of `new` (otherwise re-running would append a duplicate)."""
    text = path.read_text(encoding="utf-8")
    if (marker or new) in text:
        print(f"  = {path.name}: already patched")
        return
    if old not in text:
        raise SystemExit(
            f"Required patch failed in {path}:\n  anchor not found -> {old[:70]}\n"
            f"Upstream changed; update patches/apply_patches.py."
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"  + {path.name}: patched")


def main() -> None:
    print(f"Patching Workerman at: {ROOT}")

    # Upstream now calls bdolytics.com's own /api/trpc/market.getMarket
    # directly (it switched to the same source this project independently
    # adopted server-side - see CLAUDE.md's price-sources note). Redirect it
    # to our local proxy instead: server/app.py's /api/prices/{lang}/{region}
    # is shaped identically ({"result": {"data": [{"itemId", "price"}]}}), so
    # only the URL needs to change - the parsing below it is untouched.
    edit(
        ROOT / "src/stores/market.js",
        "const MARKETURL = `https://bdolytics.com/api/trpc/market.getMarket?input=${input}`",
        "const MARKETURL = `/api/prices/${lang}/${userStore.selectedRegion}`",
    )
    edit(
        ROOT / "src/stores/user.js",
        "marketUrl: (state) => `https://apiv2.bdolytics.com/${state.selectedLang}/${state.selectedRegion}/market/central-market-data`,",
        "marketUrl: (state) => `/api/prices/${state.selectedLang}/${state.selectedRegion}`,",
    )
    edit(ROOT / "vite.config.js", "base: '/workerman/',", "base: '/',")

    shutil.copy(PATCH_DIR / "OptimizeView.vue", ROOT / "src/views/OptimizeView.vue")
    print("  + copied OptimizeView.vue into src/views/")

    shutil.copy(PATCH_DIR / "optimizeJob.js", ROOT / "src/stores/optimizeJob.js")
    print("  + copied optimizeJob.js into src/stores/")

    shutil.copy(PATCH_DIR / "WorkersView.vue", ROOT / "src/views/WorkersView.vue")
    print("  + copied WorkersView.vue into src/views/")

    shutil.copy(PATCH_DIR / "empireStorehouse.js", ROOT / "src/stores/empireStorehouse.js")
    print("  + copied empireStorehouse.js into src/stores/")

    shutil.copy(PATCH_DIR / "StorehouseView.vue", ROOT / "src/views/StorehouseView.vue")
    print("  + copied StorehouseView.vue into src/views/")

    # Global Empire Optimizer theme, imported after Workerman's own main.css so
    # it wins on equal specificity.
    shutil.copy(PATCH_DIR / "theme.css", ROOT / "src/assets/theme.css")
    print("  + copied theme.css into src/assets/")
    edit(
        ROOT / "src/main.js",
        'import "./assets/main.css";',
        'import "./assets/main.css";\nimport "./assets/theme.css";',
        marker='import "./assets/theme.css";',
    )

    # The node router: workermanjs imports `../pkg/noderouter.js`, a compiled
    # WASM module shrddr does not publish. Because that import is a JS wrapper,
    # a pure-JS module with the same surface drops straight in. Only installed
    # if the real one isn't already present, so a genuine pkg/ always wins.
    # `src/stores/game.js` imports '../pkg/noderouter.js', so it resolves to src/pkg/.
    pkg_dir = ROOT / "src" / "pkg"
    pkg_dir.mkdir(exist_ok=True)
    router = pkg_dir / "noderouter.js"
    if router.exists():
        print("  = pkg/noderouter.js already present, leaving it alone")
    else:
        shutil.copy(PATCH_DIR / "noderouter.js", router)
        print("  + installed pure-JS pkg/noderouter.js (no WASM toolchain needed)")

    router = ROOT / "src/router/index.js"
    # Route-level code-splitting: our own routes are lazy from the start
    # (component: () => import(...) generates a separate chunk fetched only
    # when the route is visited), the same pattern upstream already uses for
    # /about. No static import needed since the identifier is never
    # referenced outside its own dynamic import().
    edit(
        router,
        '    {\n      path: "/",\n      name: "home",\n      component: HomeView,\n    },',
        '    {\n      path: "/",\n      name: "home",\n      component: HomeView,\n    },\n'
        '    {\n      path: "/optimize",\n      name: "optimize",\n      component: () => import("../views/OptimizeView.vue"),\n    },',
        marker='path: "/optimize"',
    )
    edit(
        router,
        '    {\n      path: "/optimize",\n      name: "optimize",\n      component: () => import("../views/OptimizeView.vue"),\n    },',
        '    {\n      path: "/optimize",\n      name: "optimize",\n      component: () => import("../views/OptimizeView.vue"),\n    },\n'
        '    {\n      path: "/workers",\n      name: "workers",\n      component: () => import("../views/WorkersView.vue"),\n    },',
        marker='path: "/workers"',
    )
    edit(
        router,
        '    {\n      path: "/workers",\n      name: "workers",\n      component: () => import("../views/WorkersView.vue"),\n    },',
        '    {\n      path: "/workers",\n      name: "workers",\n      component: () => import("../views/WorkersView.vue"),\n    },\n'
        '    {\n      path: "/storehouse",\n      name: "storehouse",\n      component: () => import("../views/StorehouseView.vue"),\n    },',
        marker='path: "/storehouse"',
    )
    # Same code-splitting for upstream's own secondary routes: they're all
    # statically imported today, which bundles every view (plantzones,
    # resources, settings, workshops, drop-rate calculators, etc.) into the
    # single main chunk even though a given visit only ever needs one. Home
    # stays eager (it's the landing page, needs to render immediately) and
    # About is untouched (upstream already lazy-loads it this same way).
    LAZY_VIEWS = [
        "PlantzonesView", "ResourcesView", "SettingsView", "OtherTownsView",
        "WorkshopsView", "HouseCraft", "DropratesView", "RouterTestsView",
        "RegionMapView", "FishsizeView", "LodgingView",
    ]
    for name in LAZY_VIEWS:
        edit(
            router,
            f'import {name} from "../views/{name}.vue";',
            f'// {name}: lazy-loaded via route-level code-splitting (see routes below)',
            marker=f'{name}: lazy-loaded via route-level code-splitting',
        )
        edit(
            router,
            f'component: {name}',
            f'component: () => import("../views/{name}.vue")',
        )
    # Upstream bug: solveForTerminalPairs returns [nodes, cost], but this call
    # site uses the tuple as if it were the node array (and can return it as
    # the solution). It throws whenever the workaround triggers, i.e. when node
    # 1152 is in grindTakenList. Destructure it like the other call sites do.
    edit(
        ROOT / "src/stores/routing.js",
        "          const altSolution = gameStore.wasmRouter.solveForTerminalPairs(altInput)",
        "          const [altSolution] = gameStore.wasmRouter.solveForTerminalPairs(altInput)",
        marker="const [altSolution] = gameStore.wasmRouter",
    )

    edit(
        ROOT / "src/App.vue",
        '<RouterLink to="/">Home</RouterLink>',
        '<RouterLink to="/">Home</RouterLink>\n        <RouterLink to="/optimize">Optimize</RouterLink>',
        marker='to="/optimize"',
    )
    edit(
        ROOT / "src/App.vue",
        '<RouterLink to="/optimize">Optimize</RouterLink>',
        '<RouterLink to="/optimize">Optimize</RouterLink>\n        <RouterLink to="/workers">Workers</RouterLink>',
        marker='to="/workers"',
    )
    edit(
        ROOT / "src/App.vue",
        '<RouterLink to="/workers">Workers</RouterLink>',
        '<RouterLink to="/workers">Workers</RouterLink>\n        <RouterLink to="/storehouse">Storehouse</RouterLink>',
        marker='to="/storehouse"',
    )
    print("Done.")


if __name__ == "__main__":
    main()
