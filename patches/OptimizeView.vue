<script>
import { useUserStore } from '../stores/user'
import { useMarketStore } from '../stores/market'
import { useOptimizeJobStore } from '../stores/optimizeJob'
import { useEmpireStorehouseStore } from '../stores/empireStorehouse'
import ModalDialog from '../components/ModalDialog.vue'

const DEFAULT_SOLVER = {
  mip_rel_gap: 0.0001,
  threads: 0,
  random_seed: 123456789,
  root_heuristic: true,
}

// Prices are considered fresh for this long before optimize() or "Reload
// prices" bothers re-fetching - matches the backend's own BDOLYTICS_CACHE_TTL
// (server/app.py) exactly, so the client never asks more often than the
// source could actually have changed.
const PRICE_FRESH_MS = 10 * 60 * 1000

// The Optimize page. Same dashboard design as the standalone panel, but wired
// directly to Workerman's Pinia stores so it uses the map's live prices and
// loads the solved empire straight onto the map via userStore.migrate().
//
// Job state (id/status/log/poll) lives in useOptimizeJobStore rather than
// this component's own data(), so a running solve survives navigating away
// from this page - the store is an app-lifetime singleton, the poll interval
// lives at module scope inside it, and neither is touched by this
// component's mount/unmount.
export default {
  setup() {
    return {
      userStore: useUserStore(),
      marketStore: useMarketStore(),
      jobStore: useOptimizeJobStore(),
      empireStorehouse: useEmpireStorehouseStore(),
    }
  },
  components: {
    ModalDialog,
  },
  data() {
    return {
      tab: 'optimize',
      connected: null,
      budget: 500,
      extend: false,
      matchAvailable: false,
      solver: { ...DEFAULT_SOLVER },
      priceLoading: false,
      priceStatus: null,
      saveDialogVisible: false,
      saveName: '',
      saveNotes: '',
      saving: false,
    }
  },
  computed: {
    solving() {
      return this.jobStore.solving
    },
    region: {
      get() { return this.userStore.selectedRegion },
      set(v) { this.userStore.selectedRegion = v },
    },
    priceCount() { return Object.keys(this.marketStore.apiPrices || {}).length },
    priceWhen() { return this.marketStore.apiDatetime },
    value() { return this.userStore.allJobsTotalDailyProfit || 0 },
    cpUsed() { return this.userStore.totalCP || 0 },
    workers() { return this.userStore.userWorkers.length },
    shortfall() {
      if (!this.priceStatus || !this.priceStatus.expected) return 0
      const got = this.priceCount
      return got && got < this.priceStatus.expected ? this.priceStatus.expected - got : 0
    },
    // userStore.allJobsDailyProfitPerCp already computes this exact ratio -
    // reuse it instead of re-deriving value/cpUsed a third time in the app.
    profitPerCp() {
      return this.userStore.allJobsDailyProfitPerCp || 0
    },
  },
  async mounted() {
    try {
      const r = await fetch('/api/health')
      this.connected = r.ok
      this.addLog(r.ok ? 'Backend connected.' : 'Backend not responding.')
    } catch {
      this.connected = false
      this.addLog('No backend detected. Start it with run and reload.')
    }
  },
  methods: {
    fmt(n) { return new Intl.NumberFormat('en-US').format(Math.round(n || 0)) },
    addLog(line) {
      this.jobStore.addLog(line)
      this.$nextTick(() => {
        const el = this.$refs.logbox
        if (el) el.scrollTop = el.scrollHeight
      })
    },
    async fetchPriceStatus() {
      try {
        const r = await fetch('/api/price-status')
        this.priceStatus = await r.json()
      } catch { this.priceStatus = null }
    },
    async reloadPrices(force = false) {
      if (!force && this.marketStore.apiDatetime && (Date.now() - this.marketStore.apiDatetime) < PRICE_FRESH_MS) {
        const ageS = Math.round((Date.now() - this.marketStore.apiDatetime) / 1000)
        this.addLog(`Prices already fresh (${ageS}s old).`)
        return
      }
      this.priceLoading = true
      this.addLog(`Fetching ${this.region} prices...`)
      try {
        await this.marketStore.fetchData()
        await this.fetchPriceStatus()
        this.addLog(`Prices ready: ${this.priceCount} items.`)
        if (this.priceStatus && this.priceStatus.source) {
          this.addLog(`Source: ${this.priceStatus.source}`)
        }
      } catch (e) {
        this.addLog(`Price fetch failed: ${e.message}`)
      } finally {
        this.priceLoading = false
      }
    },
    solverPayload() {
      const p = {}
      if (this.solver.mip_rel_gap) p.mip_rel_gap = Number(this.solver.mip_rel_gap)
      if (this.solver.threads !== '') p.threads = Number(this.solver.threads)
      if (this.solver.random_seed !== '') p.random_seed = Number(this.solver.random_seed)
      p.mip_heuristic_run_root_reduced_cost = !!this.solver.root_heuristic
      return p
    },
    baseEmpire() {
      if (!this.extend) return null
      return {
        userWorkers: this.userStore.userWorkers,
        lodgingP2W: this.userStore.lodgingP2W,
        grindTakenList: this.userStore.grindTakenList,
        regionResources: this.userStore.regionResources,
      }
    },
    cleanPrices(src) {
      // Workerman computes crafted prices as ret[component] * qty; an unpriced
      // component makes that NaN, which JSON.stringify sends as null and the API
      // rejects. Drop non-finite entries and report how many.
      const out = {}
      let dropped = 0
      for (const k in (src || {})) {
        const v = Number(src[k])
        if (Number.isFinite(v)) out[k] = v
        else dropped++
      }
      return { prices: out, dropped }
    },
    async optimize() {
      this.jobStore.log = []
      this.addLog(`Optimize starting - budget ${this.budget} CP.`)
      await this.reloadPrices()
      const { prices, dropped } = this.cleanPrices(this.marketStore.prices)
      if (dropped) {
        this.addLog(`${dropped} item(s) had no usable price and will be valued at 0.`)
      }
      const farming = Number(this.userStore.farmingProfitPerWorker) * 1e6
      const body = {
        budget: Number(this.budget) || 0,
        effectivePrices: prices,
        droppedPrices: dropped,
        farmingWorkerSilverPerDay: Number.isFinite(farming) ? farming : 0,
        modifiers: this.userStore.regionResources,
        baseEmpire: this.baseEmpire(),
        solverOverrides: this.solverPayload(),
        matchAvailableWorkers: this.extend && this.matchAvailable,
      }
      await this.jobStore.start(body)
    },
    async stop() {
      await this.jobStore.stop()
    },
    resetSolver() {
      this.solver = { ...DEFAULT_SOLVER }
    },
    openSaveDialog() {
      this.saveName = `${this.budget} CP - ${this.region}`
      this.saveNotes = ''
      this.saveDialogVisible = true
    },
    async confirmSave() {
      if (!this.saveName) return
      this.saving = true
      try {
        await this.empireStorehouse.save(this.saveName, this.saveNotes)
        this.saveDialogVisible = false
        this.addLog(`Saved to storehouse: "${this.saveName}"`)
      } finally {
        this.saving = false
      }
    },
    jobLabel() {
      if (!this.jobStore.status) return 'Idle'
      return {
        running: 'Solving', starting: 'Starting', stopping: 'Stopping',
        done: 'Done', stopped: 'Stopped (best so far)', error: 'Error',
      }[this.jobStore.status] || this.jobStore.status
    },
  },
}
</script>

<template>
  <div class="eo-root">
    <header class="eo-top">
      <div class="eo-brand">
        <span class="eo-mark">&#9670;</span>
        <div>
          <div class="eo-word">Empire Optimizer</div>
          <div class="eo-sub">Workerman &times; bdo-empire &middot; HiGHS solver</div>
        </div>
      </div>
      <span class="eo-conn" :class="connected === true ? 'ok' : connected === false ? 'demo' : 'wait'">
        {{ connected === true ? 'Backend connected' : connected === false ? 'Backend offline' : 'Checking...' }}
      </span>
    </header>

    <div class="eo-value" :class="{ pulse: solving }">
      <div class="eo-value-main">
        <span class="eo-value-num">{{ value ? fmt(value) : (solving ? '...' : '\u2014') }}</span>
        <span class="eo-value-unit">silver / day</span>
      </div>
      <div class="eo-value-tiles">
        <div class="eo-tile"><div class="eo-tile-v num">{{ fmt(budget) }}</div><div class="eo-tile-l">CP budget</div></div>
        <div class="eo-tile"><div class="eo-tile-v num">{{ cpUsed ? fmt(cpUsed) : '\u2014' }}</div><div class="eo-tile-l">CP used</div></div>
        <div class="eo-tile"><div class="eo-tile-v num">{{ workers ? fmt(workers) : '\u2014' }}</div><div class="eo-tile-l">Workers</div></div>
        <div class="eo-tile"><div class="eo-tile-v num">{{ profitPerCp ? fmt(profitPerCp) : '\u2014' }}</div><div class="eo-tile-l">Silver / CP</div></div>
      </div>
      <button class="eo-btn" :disabled="!workers" @click="openSaveDialog">Save to storehouse</button>
    </div>

    <ModalDialog v-model:show="saveDialogVisible">
      <h3>Save empire</h3>
      <div class="eo-field">
        <label>Name</label>
        <input type="text" v-model="saveName" />
      </div>
      <div class="eo-field">
        <label>Notes</label>
        <input type="text" v-model="saveNotes" placeholder="optional" />
      </div>
      <div class="eo-actions">
        <button class="eo-btn primary" :disabled="!saveName || saving" @click="confirmSave">
          {{ saving ? 'Saving...' : 'Save' }}
        </button>
      </div>
    </ModalDialog>

    <nav class="eo-tabs">
      <button v-for="t in [['optimize','Optimize'],['solver','Solver'],['prices','Prices'],['guide','Guide']]"
              :key="t[0]" class="eo-tab" :class="{ on: tab === t[0] }" @click="tab = t[0]">{{ t[1] }}</button>
    </nav>

    <main class="eo-main">
      <div v-if="tab === 'optimize'" class="eo-grid">
        <section class="eo-card">
          <h2 class="eo-h2">Run</h2>
          <div class="eo-field">
            <label>Region</label>
            <select v-model="region">
              <option v-for="r in ['EU','NA','SEA','MENA','KR','RU','JP','TH','TW','SA']" :key="r">{{ r }}</option>
            </select>
          </div>
          <div class="eo-field">
            <label>CP budget</label>
            <input type="number" min="1" v-model="budget" />
          </div>
          <label class="eo-check"><input type="checkbox" v-model="extend" /> Extend current empire</label>
          <label v-if="extend" class="eo-check eo-check-nested">
            <input type="checkbox" v-model="matchAvailable" />
            Match available workers to new slots
          </label>
          <p v-if="extend" class="eo-note eo-check-nested">
            Fills newly-picked plantzone slots with your own idle workers of the same
            town and type where one is available, instead of a fresh hire. Doesn't
            change which plantzones get picked or the profit shown.
          </p>
          <div class="eo-actions">
            <button v-if="!solving" class="eo-btn primary" @click="optimize">Optimize</button>
            <button v-else class="eo-btn danger" @click="stop">Stop</button>
          </div>
          <p class="eo-jobline" :class="jobStore.status || 'idle'">{{ jobLabel() }}</p>
        </section>

        <section class="eo-card">
          <h2 class="eo-h2">Prices</h2>
          <div class="eo-pstate">
            <span class="eo-dot" :class="marketStore.apiAlive ? 'ok' : 'wait'"></span>
            {{ priceCount ? fmt(priceCount) + ' items \u00b7 ' + region : 'Not loaded' }}
          </div>
          <button class="eo-btn" @click="reloadPrices(true)" :disabled="priceLoading">
            {{ priceLoading ? 'Loading...' : 'Reload prices' }}
          </button>
          <p v-if="priceStatus" class="eo-note" :class="{ 'eo-warn': shortfall }">{{ priceStatus.source }}</p>
      <p v-if="shortfall" class="eo-note eo-warn">
        {{ shortfall }} item(s) came back unpriced and are valued at 0 by the solver.
        Reload once the cache expires; transient rate limiting usually clears.
      </p>
      <p class="eo-note">Prices refresh automatically before each optimize if they're more than 10 minutes old.</p>
        </section>

        <section class="eo-card eo-span">
          <h2 class="eo-h2">Activity</h2>
          <div class="eo-log" ref="logbox">
            <div v-if="jobStore.log.length === 0" class="eo-log-empty">No activity yet. Set a budget, then Optimize.</div>
            <div v-for="(l, i) in jobStore.log" :key="i" class="eo-log-line">{{ l }}</div>
          </div>
        </section>
      </div>

      <section v-else-if="tab === 'solver'" class="eo-card">
        <h2 class="eo-h2">Solver configuration</h2>
        <p class="eo-note">Defaults match bdo-empire. Tighter gaps cost runtime; solves run from minutes to over an hour.</p>
        <div class="eo-solvergrid">
          <div class="eo-sfield">
            <div class="eo-sfield-l">MIP relative gap</div>
            <input v-model="solver.mip_rel_gap" />
            <div class="eo-sfield-h">Accuracy vs. speed.</div>
          </div>
          <div class="eo-sfield">
            <div class="eo-sfield-l">Threads</div>
            <input type="number" v-model="solver.threads" />
            <div class="eo-sfield-h">0 = auto-detect.</div>
          </div>
          <div class="eo-sfield">
            <div class="eo-sfield-l">Random seed</div>
            <input type="number" v-model="solver.random_seed" />
            <div class="eo-sfield-h">Reproducible runs.</div>
          </div>
          <div class="eo-sfield">
            <div class="eo-sfield-l">Root reduced-cost heuristic</div>
            <label class="eo-switch"><input type="checkbox" v-model="solver.root_heuristic" /> <span>{{ solver.root_heuristic ? 'On' : 'Off' }}</span></label>
            <div class="eo-sfield-h">Off on sub-300 budgets.</div>
          </div>
        </div>
        <button class="eo-btn ghost" @click="resetSolver">Reset to defaults</button>
      </section>

      <section v-else-if="tab === 'prices'" class="eo-card">
        <h2 class="eo-h2">Market data</h2>
        <div class="eo-pstate big">
          <span class="eo-dot" :class="marketStore.apiAlive ? 'ok' : 'wait'"></span>
          {{ priceCount ? fmt(priceCount) + ' items \u00b7 ' + region : 'Not loaded' }}
        </div>
        <dl class="eo-defs">
          <div><dt>Source</dt><dd>{{ priceStatus ? priceStatus.source : 'blackdesertmarket \u00b7 ' + region }}</dd></div>
          <div><dt>Items priced</dt><dd class="num">{{ priceCount ? fmt(priceCount) : '\u2014' }}</dd></div>
          <div><dt>Last reload</dt><dd>{{ priceWhen ? new Date(priceWhen).toLocaleTimeString() : '\u2014' }}</dd></div>
        </dl>
        <button class="eo-btn" @click="reloadPrices(true)" :disabled="priceLoading">Reload prices</button>
        <p class="eo-note">Served by the local backend via blackdesertmarket. Prices are cached briefly, so reloading a page does not re-request every item.</p>
      </section>

      <section v-else class="eo-card eo-guide">
        <h2 class="eo-h2">How it works</h2>
        <p>The solving is HiGHS running in the local backend. This page sends the map's current prices and modifiers to it, then loads the result back onto the map.</p>
        <ol class="eo-steps">
          <li><b>Set a CP budget</b> and click <b>Optimize</b>. Prices refresh automatically if they're more than 10 minutes old, so there's no need to reload them first. <b>Stop</b> keeps the best solution found so far.</li>
          <li>The solve keeps running even if you navigate to another page - come back to <b>Optimize</b> any time to see progress.</li>
          <li>When it finishes, the empire loads onto the map and the value bar above updates.</li>
        </ol>
        <p class="eo-note" v-if="connected === false">The backend isn't responding. Make sure it's running, then reload this page.</p>
      </section>
    </main>
  </div>
</template>

<style>
.eo-root{
  --ink:#14110c; --panel:#1e1a12; --panel2:#241f16; --line:#3a3123;
  --parch:#e9ddc4; --muted:#9a8f79; --brass:#c8a24c; --brass2:#e6c169;
  --jade:#4c9e86; --danger:#c9604e; --silver:#d6dcea;
  background:var(--ink); color:var(--parch);
  font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  padding:22px; border-radius:12px; font-size:14px; line-height:1.5; max-width:1000px; margin:0 auto;
}
.eo-root *{box-sizing:border-box}
.num,.eo-value-num{font-family:ui-monospace,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}
.eo-top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:18px}
.eo-brand{display:flex;align-items:center;gap:12px}
.eo-mark{color:var(--brass);font-size:22px}
.eo-word{font-family:Iowan Old Style,Georgia,serif;font-size:20px;color:#f3ead4}
.eo-sub{color:var(--muted);font-size:12px;letter-spacing:.04em}
.eo-conn{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;padding:5px 10px;border-radius:999px;border:1px solid var(--line)}
.eo-conn.ok{color:var(--jade);border-color:rgba(76,158,134,.5)}
.eo-conn.demo{color:var(--danger);border-color:rgba(201,96,78,.5)}
.eo-conn.wait{color:var(--muted)}
.eo-value{border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin-bottom:18px;
  background:radial-gradient(120% 140% at 0% 0%, rgba(200,162,76,.10), transparent 60%),linear-gradient(180deg,var(--panel2),var(--panel));
  display:flex;justify-content:space-between;align-items:flex-end;gap:20px;flex-wrap:wrap}
.eo-value.pulse{animation:eoglow 1.8s ease-in-out infinite}
@keyframes eoglow{0%,100%{box-shadow:0 0 0 rgba(200,162,76,0)}50%{box-shadow:0 0 26px rgba(200,162,76,.14)}}
.eo-value-num{font-size:clamp(30px,6vw,52px);color:var(--brass2);line-height:1;text-shadow:0 0 22px rgba(230,193,105,.25)}
.eo-value-unit{color:var(--muted);font-size:12px;letter-spacing:.16em;text-transform:uppercase;margin-top:8px;display:block}
.eo-value-tiles{display:flex;gap:10px;flex-wrap:wrap}
.eo-tile{border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:92px;background:rgba(0,0,0,.15)}
.eo-tile-v{font-size:17px;color:var(--silver)}
.eo-tile-l{font-size:11px;color:var(--muted);letter-spacing:.05em;margin-top:3px;text-transform:uppercase}
.eo-tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-bottom:18px;flex-wrap:wrap}
.eo-tab{background:none;border:none;color:var(--muted);padding:10px 16px;font-size:14px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
.eo-tab:hover{color:var(--parch)}
.eo-tab.on{color:var(--brass2);border-bottom-color:var(--brass)}
.eo-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.eo-span{grid-column:1/-1}
@media(max-width:720px){.eo-grid{grid-template-columns:1fr}}
.eo-card{border:1px solid var(--line);border-radius:12px;padding:18px;background:var(--panel)}
.eo-h2{font-family:Iowan Old Style,Georgia,serif;font-size:15px;margin:0 0 14px;color:#f0e6cf;font-weight:600}
.eo-field{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}
.eo-field label{color:var(--muted);font-size:13px}
.eo-root input,.eo-root select{background:var(--ink);color:var(--parch);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:14px;font-family:inherit;min-width:120px}
.eo-root input:focus,.eo-root select:focus{outline:none;border-color:var(--brass)}
.eo-check{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px;margin:4px 0 14px;cursor:pointer}
.eo-check input{min-width:auto}
.eo-check-nested{margin-left:22px}
label.eo-check-nested{margin:-6px 0 6px}
.eo-actions{display:flex;gap:10px;flex-wrap:wrap}
.eo-btn{background:var(--panel2);color:var(--parch);border:1px solid var(--line);border-radius:9px;padding:9px 16px;font-size:14px;cursor:pointer;font-family:inherit}
.eo-btn:hover:not(:disabled){border-color:var(--brass)}
.eo-btn:disabled{opacity:.4;cursor:not-allowed}
.eo-btn.primary{background:linear-gradient(180deg,var(--brass2),var(--brass));color:#241a06;border-color:var(--brass);font-weight:600}
.eo-btn.danger{background:linear-gradient(180deg,#d8715e,var(--danger));color:#2a0f0a;border-color:var(--danger);font-weight:600}
.eo-btn.ghost{background:none}
.eo-note{color:var(--muted);font-size:12px;margin:12px 0 0}
.eo-warn{color:var(--danger)}
.eo-jobline{margin:14px 0 0;font-size:13px}
.eo-jobline.idle{color:var(--muted)}
.eo-jobline.running,.eo-jobline.starting,.eo-jobline.stopping{color:var(--jade)}
.eo-jobline.done{color:var(--brass2)}
.eo-jobline.stopped{color:var(--brass)}
.eo-jobline.error{color:var(--danger)}
.eo-pstate{display:flex;align-items:center;gap:9px;font-size:13px;margin-bottom:14px}
.eo-pstate.big{font-size:15px;margin-bottom:18px}
.eo-dot{width:9px;height:9px;border-radius:50%;background:var(--muted)}
.eo-dot.ok{background:var(--jade);box-shadow:0 0 8px rgba(76,158,134,.6)}
.eo-dot.wait{background:var(--muted)}
.eo-log{background:var(--ink);border:1px solid var(--line);border-radius:9px;padding:12px;height:190px;overflow:auto;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:#bcae90}
.eo-log-line{padding:1px 0;white-space:pre-wrap}
.eo-log-empty{color:var(--muted)}
.eo-solvergrid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
@media(max-width:640px){.eo-solvergrid{grid-template-columns:1fr}}
.eo-sfield-l{font-size:13px;color:var(--parch);margin-bottom:6px}
.eo-sfield input{width:100%}
.eo-sfield-h{font-size:11.5px;color:var(--muted);margin-top:5px}
.eo-switch{display:flex;align-items:center;gap:8px;color:var(--muted);cursor:pointer}
.eo-switch input{min-width:auto}
.eo-defs{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:4px 0 16px}
@media(max-width:560px){.eo-defs{grid-template-columns:1fr}}
.eo-defs dt{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}
.eo-defs dd{margin:4px 0 0;font-size:16px;color:var(--silver)}
.eo-guide p{max-width:64ch;color:#cdc0a4}
.eo-steps{max-width:66ch;padding-left:20px;color:#cdc0a4}
.eo-steps li{margin:8px 0}
.eo-guide b{color:var(--parch)}
@media(prefers-reduced-motion:reduce){.eo-value.pulse{animation:none}}
</style>
