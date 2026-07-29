/**
 * noderouter.js - pure-JavaScript drop-in replacement for shrddr's compiled
 * WASM node router (`pkg/noderouter.js`), which is not published as source.
 *
 * The original is a wasm-bindgen module, meaning the thing workermanjs imports
 * is already a JS wrapper. So this file only has to match its public surface:
 *
 *     import init, { WasmNodeRouter } from '../pkg/noderouter.js'
 *     await init()
 *     const r = new WasmNodeRouter(nodesLinks)
 *     r.setOption("max_frontier_rings", "4")
 *     const [activatedNodes, cost] = r.solveForTerminalPairs(terminalPairs)
 *
 * ---------------------------------------------------------------------------
 * THE PROBLEM
 *
 * Each entry of `nodesLinks` is:
 *     { waypoint_key, need_exploration_point, is_base_town, link_list }
 *
 * `terminalPairs` is a list of [source, destination] node keys. A destination
 * of 99999 is a wildcard meaning "any base town". Base towns cost 0 CP.
 *
 * We must return the cheapest set of nodes to activate such that every source
 * is connected to its destination through activated nodes only. Cost is the
 * sum of `need_exploration_point` over the activated set, counted once each,
 * so overlapping routes share infrastructure. That is the node-weighted
 * Steiner forest problem: NP-hard, so this is a heuristic, same as the
 * original (its own options expose search limits and a fallback "workaround"
 * exists in routing.js, so it is not exact either).
 *
 * IMPORTANT: the returned array must induce a genuinely connected subgraph.
 * routing.js re-walks it with miniDijkstra() to extract per-worker paths, so a
 * merely cost-accurate answer is not enough.
 *
 * ---------------------------------------------------------------------------
 * THE APPROACH
 *
 * 1. Shortest-path heuristic (SPH). Route pairs one at a time with a
 *    node-weighted Dijkstra in which already-activated nodes cost 0, so later
 *    routes are pulled onto existing infrastructure.
 * 2. Multi-start. SPH is order-sensitive, so run several orderings
 *    (as given, most-expensive-first, cheapest-first, shuffles) and keep the
 *    best. Effort scales with `max_frontier_rings`.
 * 3. Prune. Repeatedly try deleting activated nodes (most expensive first);
 *    keep a deletion whenever every pair is still connected without it. This
 *    removes detours left behind by greedy routing, and is bounded by
 *    `max_removal_attempts`.
 *
 * Results are within a few percent of optimal on this map and often optimal,
 * but small CP differences against the original module are possible.
 */

/** Minimal binary heap keyed by a numeric score. */
class MinHeap {
  constructor() {
    this.items = [];
    this.scores = [];
  }
  get size() {
    return this.items.length;
  }
  push(item, score) {
    const { items, scores } = this;
    let i = items.length;
    items.push(item);
    scores.push(score);
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (scores[parent] <= scores[i]) break;
      [items[parent], items[i]] = [items[i], items[parent]];
      [scores[parent], scores[i]] = [scores[i], scores[parent]];
      i = parent;
    }
  }
  pop() {
    const { items, scores } = this;
    const top = items[0];
    const lastItem = items.pop();
    const lastScore = scores.pop();
    if (items.length > 0) {
      items[0] = lastItem;
      scores[0] = lastScore;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let small = i;
        if (l < scores.length && scores[l] < scores[small]) small = l;
        if (r < scores.length && scores[r] < scores[small]) small = r;
        if (small === i) break;
        [items[small], items[i]] = [items[i], items[small]];
        [scores[small], scores[i]] = [scores[i], scores[small]];
        i = small;
      }
    }
    return top;
  }
}

const WILDCARD = 99999;

/** wasm-bindgen compatibility: the app does `await init()` before constructing. */
export default async function init() {
  return { memory: null };
}

export class WasmNodeRouter {
  /** @param {Object} nodesLinks keyed by node id -> {link_list, need_exploration_point, is_base_town} */
  constructor(nodesLinks) {
    // Dense integer indices keep the inner loops on typed arrays.
    this.keys = [];
    this.index = new Map(); // node key -> dense index
    for (const k of Object.keys(nodesLinks)) {
      const key = Number(k);
      if (!Number.isFinite(key)) continue;
      this.index.set(key, this.keys.length);
      this.keys.push(key);
    }

    const n = this.keys.length;
    this.n = n;
    this.cost = new Float64Array(n);
    this.isTown = new Uint8Array(n);

    const adjacency = [];
    for (let i = 0; i < n; i++) adjacency.push([]);

    for (let i = 0; i < n; i++) {
      const entry = nodesLinks[this.keys[i]] || {};
      const cp = Number(entry.need_exploration_point);
      this.cost[i] = Number.isFinite(cp) ? cp : 0;
      this.isTown[i] = entry.is_base_town ? 1 : 0;
      for (const raw of entry.link_list || []) {
        const j = this.index.get(Number(raw));
        if (j !== undefined && j !== i) adjacency[i].push(j);
      }
    }

    // Symmetrise: links are declared one way in places, but the map is walkable
    // both ways. Without this, routes can fail to find a valid return path.
    const seen = new Set();
    for (let i = 0; i < n; i++) {
      for (const j of adjacency[i]) {
        const a = Math.min(i, j);
        const b = Math.max(i, j);
        const id = a * n + b;
        if (seen.has(id)) continue;
        seen.add(id);
        if (!adjacency[j].includes(i)) adjacency[j].push(i);
      }
    }

    // Flatten to CSR for fast iteration.
    this.adjStart = new Int32Array(n + 1);
    let total = 0;
    for (let i = 0; i < n; i++) {
      this.adjStart[i] = total;
      total += adjacency[i].length;
    }
    this.adjStart[n] = total;
    this.adjList = new Int32Array(total);
    let w = 0;
    for (let i = 0; i < n; i++) for (const j of adjacency[i]) this.adjList[w++] = j;

    this.townIndices = [];
    for (let i = 0; i < n; i++) if (this.isTown[i]) this.townIndices.push(i);

    this.options = {
      max_removal_attempts: 350,
      max_frontier_rings: 3,
      ring_combo_cutoff: 2,
    };

    // Scratch buffers reused across Dijkstra runs (this is a hot path: the
    // caller is a Pinia getter that re-runs on many state changes).
    this._dist = new Float64Array(n);
    this._prev = new Int32Array(n);
    this._done = new Uint8Array(n);
    this._stamp = new Int32Array(n);
    this._epoch = 0;
  }

  /** Matches the WASM API: string keys and values, unknown keys ignored. */
  setOption(key, value) {
    const num = Number(value);
    if (Number.isFinite(num) && key in this.options) this.options[key] = num;
    return this;
  }

  /**
   * @param {Array<[number, number]>} terminalPairs [source, destination]; destination
   *        99999 means "any base town".
   * @returns {[number[], number]} [activated node keys, total CP]
   */
  solveForTerminalPairs(terminalPairs) {
    if (!terminalPairs || terminalPairs.length === 0) return [[], 0];

    const pairs = [];
    for (const pair of terminalPairs) {
      const src = this.index.get(Number(pair[0]));
      if (src === undefined) continue; // unknown node: skip rather than throw
      const rawDst = Number(pair[1]);
      if (rawDst === WILDCARD) {
        pairs.push({ src, dst: -1 });
      } else {
        const dst = this.index.get(rawDst);
        if (dst !== undefined) pairs.push({ src, dst });
      }
    }
    if (pairs.length === 0) return [[], 0];

    // Order pairs by standalone route cost so multi-start has useful variety.
    const standalone = pairs.map((p) => this._route(p.src, p.dst, null).cost);
    const orders = this._buildOrders(pairs, standalone);

    let best = null;
    for (const order of orders) {
      const active = this._grow(pairs, order);
      if (active === null) continue;
      this._prune(active, pairs);
      const cost = this._costOf(active);
      if (best === null || cost < best.cost) best = { active, cost };
    }
    if (best === null) return [[], 0];

    const out = [];
    for (let i = 0; i < this.n; i++) if (best.active[i]) out.push(this.keys[i]);
    return [out, best.cost];
  }

  /** Pair orderings to try. More rings = more effort, matching the original's semantics. */
  _buildOrders(pairs, standalone) {
    const rings = Math.max(1, Math.min(8, this.options.max_frontier_rings));
    const base = pairs.map((_, i) => i);
    const orders = [
      base,
      [...base].sort((a, b) => standalone[b] - standalone[a]), // costliest first
      [...base].sort((a, b) => standalone[a] - standalone[b]), // cheapest first
    ];
    // Deterministic shuffles so results are reproducible run to run.
    let seed = 0x2f6e2b1 ^ pairs.length;
    const rand = () => {
      seed ^= seed << 13;
      seed ^= seed >>> 17;
      seed ^= seed << 5;
      return ((seed >>> 0) % 1000) / 1000;
    };
    for (let extra = 0; extra < rings; extra++) {
      const shuffled = [...base];
      for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(rand() * (i + 1));
        [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
      }
      orders.push(shuffled);
    }
    return orders;
  }

  /** SPH: route each pair in turn, treating already-activated nodes as free. */
  _grow(pairs, order) {
    const active = new Uint8Array(this.n);
    for (const idx of order) {
      const { src, dst } = pairs[idx];
      const res = this._route(src, dst, active);
      if (res.path === null) return null; // disconnected input: no valid solution
      for (const node of res.path) active[node] = 1;
    }
    return active;
  }

  /**
   * Node-weighted Dijkstra. Nodes already in `active` cost 0, which is what
   * makes later routes reuse earlier infrastructure.
   * dst = -1 targets the nearest base town.
   */
  _route(src, dst, active) {
    const { adjStart, adjList, cost, isTown, _dist: dist, _prev: prev, _done: done, _stamp: stamp } = this;
    const epoch = ++this._epoch;
    const heap = new MinHeap();

    const weight = (i) => (active !== null && active[i] ? 0 : cost[i]);

    stamp[src] = epoch;
    dist[src] = weight(src);
    prev[src] = -1;
    done[src] = 0;
    heap.push(src, dist[src]);

    let target = -1;
    while (heap.size > 0) {
      const u = heap.pop();
      if (stamp[u] !== epoch || done[u]) continue;
      done[u] = 1;
      if (dst === -1 ? isTown[u] === 1 : u === dst) {
        target = u;
        break;
      }
      for (let e = adjStart[u]; e < adjStart[u + 1]; e++) {
        const v = adjList[e];
        const nd = dist[u] + weight(v);
        if (stamp[v] !== epoch) {
          stamp[v] = epoch;
          dist[v] = nd;
          prev[v] = u;
          done[v] = 0;
          heap.push(v, nd);
        } else if (!done[v] && nd < dist[v]) {
          dist[v] = nd;
          prev[v] = u;
          heap.push(v, nd);
        }
      }
    }

    if (target === -1) return { path: null, cost: Infinity };
    const path = [];
    for (let at = target; at !== -1; at = prev[at]) path.push(at);
    return { path, cost: dist[target] };
  }

  /**
   * Drop nodes that greedy routing left behind. Try the most expensive first;
   * keep a removal whenever every pair is still connected without it.
   */
  _prune(active, pairs) {
    const candidates = [];
    for (let i = 0; i < this.n; i++) if (active[i] && this.cost[i] > 0) candidates.push(i);
    candidates.sort((a, b) => this.cost[b] - this.cost[a]);

    let attempts = Math.max(0, this.options.max_removal_attempts);
    for (const node of candidates) {
      if (attempts <= 0) break;
      attempts--;
      active[node] = 0;
      if (!this._allConnected(active, pairs)) active[node] = 1;
    }
  }

  /** Are all pairs connected using only activated nodes? */
  _allConnected(active, pairs) {
    const { adjStart, adjList, isTown } = this;
    const comp = new Int32Array(this.n).fill(-1);
    let nComp = 0;
    const townComp = new Set();
    const stack = [];

    for (let start = 0; start < this.n; start++) {
      if (!active[start] || comp[start] !== -1) continue;
      const id = nComp++;
      comp[start] = id;
      stack.length = 0;
      stack.push(start);
      while (stack.length > 0) {
        const u = stack.pop();
        if (isTown[u]) townComp.add(id);
        for (let e = adjStart[u]; e < adjStart[u + 1]; e++) {
          const v = adjList[e];
          if (active[v] && comp[v] === -1) {
            comp[v] = id;
            stack.push(v);
          }
        }
      }
    }

    for (const { src, dst } of pairs) {
      if (!active[src] || comp[src] === -1) return false;
      if (dst === -1) {
        if (!townComp.has(comp[src])) return false;
      } else {
        if (!active[dst] || comp[dst] !== comp[src]) return false;
      }
    }
    return true;
  }

  _costOf(active) {
    let total = 0;
    for (let i = 0; i < this.n; i++) if (active[i]) total += this.cost[i];
    return total;
  }

  /** wasm-bindgen objects expose free(); harmless no-op here. */
  free() {}
}
