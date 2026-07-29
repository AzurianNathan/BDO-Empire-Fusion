import {defineStore} from "pinia";
import {useUserStore} from './user'

// Poll interval handle lives at module scope, not in reactive state, so it
// survives regardless of which component (if any) is mounted. This is the
// whole point of this store: OptimizeView.vue used to keep job/log/poll in
// its own component-local data(), which Vue Router destroyed on navigating
// away from /optimize - even though the solve kept running server-side in a
// daemon thread. Moving that state here means the poll is tied to the app's
// lifetime, not a component's.
let pollHandle = null

export const useOptimizeJobStore = defineStore({
  id: "optimizeJob",
  state: () => ({
    jobId: null,
    status: null,   // null | starting | running | stopping | done | stopped | error
    log: [],
    cursor: 0,
    result: null,
  }),

  getters: {
    solving: (state) => !!state.status && ['running', 'starting', 'stopping'].includes(state.status),
  },

  actions: {
    addLog(line) {
      const t = new Date().toLocaleTimeString()
      this.log.push(`${t}  ${line}`)
      if (this.log.length > 140) this.log.shift()
    },

    async start(body) {
      clearInterval(pollHandle)
      this.cursor = 0
      this.result = null
      try {
        const r = await fetch('/api/optimize', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!r.ok) throw new Error(`server ${r.status}`)
        const d = await r.json()
        this.jobId = d.job_id
        this.status = 'running'
        this.addLog(`Job ${d.job_id.slice(0, 8)} running. Large budgets can take a while.`)
        this._poll()
      } catch (e) {
        this.status = 'error'
        this.addLog(`Failed to start: ${e.message}`)
      }
    },

    _poll() {
      pollHandle = setInterval(async () => {
        try {
          const r = await fetch(`/api/optimize/${this.jobId}?since=${this.cursor}`)
          const d = await r.json()
          if (Array.isArray(d.lines)) {
            for (const line of d.lines) this.addLog(line)
          }
          if (typeof d.cursor === 'number') this.cursor = d.cursor
          this.status = d.status
          if (d.status === 'done' || d.status === 'stopped') {
            clearInterval(pollHandle)
            this._finish(d)
          } else if (d.status === 'error') {
            clearInterval(pollHandle)
            this.addLog(d.error ? `Solver error: ${d.error}` : 'Solver error (see server console).')
          }
        } catch (e) {
          // A failed poll tick is a transient network hiccup, not proof the job
          // died - keep retrying instead of giving up. (The bug this store fixes
          // was a client-side JSON.parse failure on a *successful* result being
          // misreported as "lost contact"; a real network error deserves a real
          // retry, not an immediate bail-out.)
          this.addLog(`Poll error, retrying: ${e.message}`)
        }
      }, 2000)
    },

    _finish(d) {
      this.result = d.result || null
      if (d.result) {
        const userStore = useUserStore()
        // userStore.migrate() is upstream Workerman code that expects a JSON
        // *string* (it does JSON.parse(localStored) internally, matching how
        // App.vue calls it with localStorage.getItem('user')). d.result here
        // is already a parsed object from r.json(), so it must be
        // re-stringified or JSON.parse coerces it to "[object Object]" and
        // throws.
        userStore.migrate(JSON.stringify(d.result))
        // Logged unconditionally (not just when the Optimize page happens to be
        // open) since a finished job now auto-applies regardless of which page
        // the user is on.
        this.addLog('Optimized empire loaded onto the map.')
      } else {
        this.addLog('Job finished but returned no empire.')
      }
    },

    async stop() {
      if (!this.jobId) return
      this.addLog('Stopping - keeps best solution so far.')
      this.status = 'stopping'
      await fetch(`/api/optimize/${this.jobId}/stop`, { method: 'POST' })
    },
  },
})
