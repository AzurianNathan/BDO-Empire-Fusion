import {defineStore} from "pinia";
import {useUserStore} from './user'

// Fields that make up "one empire" - see docs/empire-storehouse-plan.md for
// the full empire-specific vs global-preference classification this is based
// on. Everything else in userStore (region, tax, display toggles, etc.) is a
// global preference and is deliberately left out, so loading a saved empire
// via $patch() doesn't touch it.
const EMPIRE_FIELDS = [
  'userWorkers', 'lodgingP2W', 'lodgingTaken', 'activateAncado',
  'grindTakenList', 'farmingEnable', 'farmingProfit', 'farmingBareProfit',
  'farmingP2WShare', 'userWorkshops', 'palaceEnable', 'palaceProfit',
  'tradeDestinations', 'tradeRouteAlwaysOn', 'tradeInfraCp', 'tradeRouteCp',
]

export const useEmpireStorehouseStore = defineStore({
  id: "empireStorehouse",
  state: () => ({
    list: [],       // [{id, name, notes, savedAt, meta}] - no `empire` payload, list stays cheap
    loading: false,
  }),

  actions: {
    async refresh() {
      this.loading = true
      try {
        const r = await fetch('/api/empires')
        this.list = await r.json()
      } finally {
        this.loading = false
      }
    },

    async save(name, notes = '') {
      const userStore = useUserStore()
      const empire = {}
      for (const key of EMPIRE_FIELDS) {
        empire[key] = userStore[key]
      }
      const meta = {
        valuePerDay: userStore.allJobsTotalDailyProfit || 0,
        cpUsed: userStore.totalCP || 0,
        efficiency: userStore.allJobsDailyProfitPerCp || 0,
        region: userStore.selectedRegion,
        workerCount: userStore.userWorkers.length,
      }
      const r = await fetch('/api/empires', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, notes, empire, meta }),
      })
      const { id } = await r.json()
      await this.refresh()
      return id
    },

    async load(id) {
      const userStore = useUserStore()
      const r = await fetch(`/api/empires/${id}`)
      const snapshot = await r.json()
      // $patch(), not userStore.migrate(): migrate() runs legacy-field
      // back-compat renames and, if any fire, silently overwrites the live
      // `user` localStorage key as a side effect. A snapshot saved by this
      // app is already current-shaped, so that migration path isn't needed
      // and its side effect isn't wanted here.
      userStore.$patch(snapshot.empire)
    },

    async remove(id) {
      await fetch(`/api/empires/${id}`, { method: 'DELETE' })
      await this.refresh()
    },
  },
})
