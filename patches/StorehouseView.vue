<script>
import {useUserStore} from '../stores/user'
import {useEmpireStorehouseStore} from '../stores/empireStorehouse'
import {formatFixed} from '../util.js'

// Standalone list of saved empires - see docs/empire-storehouse-plan.md.
export default {
  setup() {
    const userStore = useUserStore()
    const storehouse = useEmpireStorehouseStore()

    // Same reasoning as WorkersView.vue: no always-mounted map child here to
    // lean on for persistence, so this page must set it up itself or a
    // loaded empire won't survive a reload.
    userStore.$subscribe((mutation, state) => {
      localStorage.setItem('user', JSON.stringify(state))
    })

    return { userStore, storehouse }
  },

  data: () => ({
    loadingId: null,
  }),

  async mounted() {
    await this.storehouse.refresh()
  },

  methods: {
    formatFixed,
    formatDate(iso) {
      return new Date(iso).toLocaleString()
    },
    async load(id) {
      this.loadingId = id
      try {
        await this.storehouse.load(id)
      } finally {
        this.loadingId = null
      }
    },
    async remove(id, name) {
      if (!confirm(`Delete "${name}"? This can't be undone.`)) return
      await this.storehouse.remove(id)
    },
  },
}
</script>

<template>
  <main class="storehouse-page">
    <h1>Empire Storehouse</h1>
    <p class="hint">Saved empires - load one back onto the map, or clear out old ones.</p>

    <p v-if="storehouse.loading">Loading...</p>
    <p v-else-if="storehouse.list.length === 0" class="hint">Nothing saved yet. Save an empire from the Optimize page.</p>

    <table v-else>
      <thead>
        <tr>
          <th>Name</th>
          <th>Saved</th>
          <th>Silver/CP</th>
          <th>M$/day</th>
          <th>CP</th>
          <th>Workers</th>
          <th>Region</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="e in storehouse.list" :key="e.id">
          <td>{{ e.name }}<div v-if="e.notes" class="notes">{{ e.notes }}</div></td>
          <td>{{ formatDate(e.savedAt) }}</td>
          <td>{{ formatFixed(e.meta.efficiency, 2) }}</td>
          <td>{{ formatFixed(e.meta.valuePerDay, 1) }}</td>
          <td>{{ e.meta.cpUsed }}</td>
          <td>{{ e.meta.workerCount }}</td>
          <td>{{ e.meta.region }}</td>
          <td>
            <button @click="load(e.id)" :disabled="loadingId === e.id">
              {{ loadingId === e.id ? 'Loading...' : 'Load' }}
            </button>
            <button @click="remove(e.id, e.name)">Delete</button>
          </td>
        </tr>
      </tbody>
    </table>
  </main>
</template>

<style scoped>
.storehouse-page {
  max-width: 1000px;
  margin: 0 auto;
  padding: 16px;
}
.hint {
  color: var(--muted, #888);
  margin-bottom: 12px;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th, td {
  text-align: left;
  padding: 6px 10px;
}
.notes {
  font-size: 0.85em;
  color: var(--muted, #888);
}
</style>
