/**
 * noderouter.js - drop-in replacement for shrddr's compiled WASM node
 * router (`pkg/noderouter.js`), which is not published as source.
 *
 * This wraps the REAL algorithm: Thell/bdo-noderouter
 * (https://github.com/Thell/bdo-noderouter, Unlicense), a published
 * Node-Weighted Primal-Dual Steiner Forest approximation plus GSSP and
 * Pulsing-Bridge Spanners refinement. Vendored as a compiled WASM build in
 * `pkg-real/` (built from source via `wasm-pack build --release --target web
 * --features wasm`; see that repo for how to rebuild it). This file is the
 * thin adapter layer, not the algorithm itself.
 *
 * Compared against the previous hand-written pure-JS heuristic (a
 * multi-start shortest-path + prune SPH, which has no approximation
 * guarantee) on both synthetic and real player empire data: consistently
 * cheaper by ~1-3% on real empires, at a real but small per-solve cost that
 * is negligible on realistic (geographically clustered) empires and only
 * shows up on adversarial/scattered inputs.
 *
 * IMPORTANT: bdo-noderouter's real WASM build panics (aborting the whole
 * WASM instance, unrecoverable) if `solveForTerminalPairs` is given a
 * terminal/root waypoint key that isn't in the graph it was constructed
 * with - confirmed by building it from source and running it against a
 * real user's empire export whose plantzone keys had drifted from current
 * game data. That's a deliberate design choice upstream (fail loud, the
 * caller validates input, not a bug to fix in bdo-noderouter itself) - so
 * the filtering below, which the previous pure-JS version also did, is
 * REQUIRED here, not optional defensive programming. Do not remove it.
 *
 *     import init, { WasmNodeRouter } from '../pkg/noderouter.js'
 *     await init()
 *     const r = new WasmNodeRouter(nodesLinks)
 *     r.setOption("max_frontier_rings", "4")
 *     const [activatedNodes, cost] = r.solveForTerminalPairs(terminalPairs)
 */
import initReal, { WasmNodeRouter as RealWasmNodeRouter } from './noderouter_real.js'

const WILDCARD = 99999;

/**
 * `module_or_path` is optional and forwarded as-is to the real wasm-bindgen
 * init: omitted, it fetches noderouter_bg.wasm relative to its own URL
 * (what the app does, served over real HTTP by Vite/the built static
 * server); explicit bytes/a Response/a URL also work (what
 * tests/router_test.mjs does, since plain Node's fetch() doesn't support
 * file:// URLs the way a browser's does).
 */
export default async function init(module_or_path) {
  await initReal(module_or_path);
}

export class WasmNodeRouter {
  /** @param {Object} nodesLinks keyed by node id -> {link_list, need_exploration_point, is_base_town} */
  constructor(nodesLinks) {
    // Real bdo-noderouter's own JSON parsing is what actually defines the
    // graph; this is a parallel, cheap membership set used only to filter
    // terminal pairs before they ever reach the WASM call.
    this._validKeys = new Set(Object.keys(nodesLinks).map(Number));

    // tests/router_test.mjs (and CLAUDE.md's documented "Commands") reads
    // these two properties directly; the real Rust WasmNodeRouter doesn't
    // expose them, so they're computed here from the same input instead.
    this.n = this._validKeys.size;
    this.townIndices = Object.entries(nodesLinks)
      .filter(([, v]) => v && v.is_base_town)
      .map(([k]) => Number(k));

    this._inner = new RealWasmNodeRouter(nodesLinks);
  }

  /** Matches the WASM API: string keys and values.
   *
   * Does NOT swallow a rejected option: the real setOption throws on an
   * unrecognized key, and the app only ever calls this with 3 known-good
   * names (max_removal_attempts, max_frontier_rings, ring_combo_cutoff). If
   * that ever throws it means the option contract drifted from what this
   * adapter (or the app) assumes, which is worth breaking loudly on rather
   * than silently leaving the solver running with an un-applied setting. */
  setOption(key, value) {
    this._inner.setOption(key, String(value));
    return this;
  }

  /**
   * @param {Array<[number, number]>} terminalPairs [source, destination]; destination
   *        99999 means "any base town".
   * @returns {[number[], number]} [activated node keys, total CP]
   */
  solveForTerminalPairs(terminalPairs) {
    const safePairs = (terminalPairs || []).filter(([t, r]) => {
      if (!this._validKeys.has(Number(t))) return false;
      if (Number(r) !== WILDCARD && !this._validKeys.has(Number(r))) return false;
      return true;
    });
    if (safePairs.length === 0) return [[], 0];
    // No try/catch here on purpose: the filtering above already removes the
    // one known cause of a panic (unrecognized node keys). Any other
    // failure is unexpected and should surface as a loud, visible error
    // instead of being caught and turned into a fabricated "0 CP, no nodes
    // needed" result - a wrong empire silently shown as correct is worse
    // than a broken page that's obviously broken.
    const [activated, cost] = this._inner.solveForTerminalPairs(safePairs);
    return [Array.from(activated), cost];
  }

  /** wasm-bindgen objects expose free(); harmless no-op here. */
  free() {}
}
