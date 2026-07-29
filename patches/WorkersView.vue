<script>
import {useGameStore} from '../stores/game'
import {useUserStore} from '../stores/user'
import {useRoutingStore} from '../stores/routing'
import TownWorkers from '../components/TownWorkers.vue'
import ModalDialog from '../components/ModalDialog.vue'
import WorkerEdit from '../components/WorkerEdit.vue'
import WorkerSendSelection from '../components/WorkerSendSelection.vue'
import LodgingSelection from '../components/LodgingSelection.vue'
import HousesSelection from '../components/HousesSelection.vue'
import {levelup} from '../util.js'

// A standalone, all-towns worker management page. Reuses the exact
// TownWorkers rows, dialogs, and userStore actions HomeView.vue's map page
// already uses for its collapsed "All towns/workers list" section, just
// without the map itself - so edits made here are the same userStore
// mutations the map sees, not a separate data model.
export default {
  setup() {
    const gameStore = useGameStore()
    const userStore = useUserStore()
    const routingStore = useRoutingStore()

    // HomeView.vue relies on its always-mounted NodeMap/MapSelectedInfo
    // children for this same subscription; this page has no map, so it must
    // set persistence up itself (matches LodgingView.vue, ResourcesView.vue,
    // SettingsView.vue, which each do this directly in their own setup()).
    userStore.$subscribe((mutation, state) => {
      localStorage.setItem('user', JSON.stringify(state))
    })

    return { gameStore, userStore, routingStore }
  },

  components: {
    TownWorkers,
    ModalDialog,
    WorkerEdit,
    WorkerSendSelection,
    LodgingSelection,
    HousesSelection,
  },

  data: () => ({
    workerEditing: null,
    workerEditingInitial: null,
    workerEditingInitialProfit: 0,
    workerDialogVisible: false,
    sendDialogWorker: null,
    sendDialogVisible: false,
    lodgingDialogTown: "0",
    lodgingDialogData: null,
    lodgingDialogVisible: false,
    housesDialogTown: 0,
    housesDialogVisible: false,
  }),

  methods: {
    hireWorker(tk) {
      const w = this.userStore.useDefaultWorker
        ? {...this.userStore.defaultWorker, tnk: this.gameStore.tk2tnk(tk)}
        : this.hireRandomArtGob(tk)
      this.userStore.userWorkers.push(w)
    },

    hireRandomArtGob(tk) {
      const label = this.userStore.newWorkerName(tk)
      const charkey = 7572
      let w = {
        tk,
        tnk: this.gameStore.tk2tnk(tk),
        charkey,
        label,
        level: 1,
        wspdSheet: this.gameStore.workerStatic[charkey].wspd / 1E6,
        mspdSheet: this.gameStore.workerStatic[charkey].mspd / 100,
        luckSheet: this.gameStore.workerStatic[charkey].luck / 1E4,
        skills: [],
        job: null,
      }

      w.skills.push(this.gameStore.randomSkill(w.skills))

      levelup(this.gameStore, w, 40)
      w.wspdSheet = Math.round(w.wspdSheet * 100) / 100
      w.mspdSheet = Math.round(w.mspdSheet * 100) / 100
      w.luckSheet = Math.round(w.luckSheet * 100) / 100

      return w
    },

    sendWorker(worker) {
      this.sendDialogWorker = worker
      this.sendDialogVisible = true
    },

    editWorker(w) {
      this.workerEditing = w
      this.workerEditingInitial = JSON.parse(JSON.stringify(w))
      this.workerEditingInitialProfit = w && w.job && typeof(w.job) == 'number' ? this.routingStore.pzJobs[this.workerEditing.job].profit.priceDaily : 0
      this.workerDialogVisible = true
    },

    hireAll() {
      for (const tk of Object.keys(this.gameStore.lodgingPerTown)) {
        const slotsHere = this.userStore.townFreeLodgingCount(tk)
        for (let i = 0; i < slotsHere; i++) {
          this.hireWorker(tk)
        }
      }
    },

    fireAll() {
      this.userStore.userWorkers = []
    },

    selectLodging(tk) {
      this.lodgingDialogTown = tk
      this.lodgingDialogData = this.gameStore.lodgingPerTown[tk]
      this.lodgingDialogVisible = true
    },

    selectHouses(tk) {
      this.housesDialogTown = tk
      this.housesDialogVisible = true
    },

    panToPaPos() {
      // Map-camera-pan handler on the map page; no map here, so no-op.
    },
  },
}
</script>

<template>
  <main class="workers-page">
    <h1>Workers</h1>
    <p class="hint">Add, edit, and send workers for every town in one place - the same actions and data as the map's per-town worker lists.</p>

    <div class="workers-toolbar">
      <button @click="hireAll()">hire all</button>
      <button @click="fireAll()">fire all</button>
    </div>

    <table>
      <template v-for="(o, tk) in gameStore.lodgingPerTown">
        <TownWorkers
          :o="o"
          :tk="Number(tk)"
          @selectLodging="selectLodging"
          @selectHouses="selectHouses"
          @hireWorker="hireWorker"
          @editWorker="editWorker"
          @sendWorker="sendWorker"
          @panToPaPos="panToPaPos"
        />
      </template>
    </table>

    <ModalDialog v-model:show="workerDialogVisible">
      <WorkerEdit
        :workerEditing="workerEditing"
        :workerInitial="workerEditingInitial"
        :initialProfit="workerEditingInitialProfit"
        v-model:show="workerDialogVisible"
      />
    </ModalDialog>

    <ModalDialog v-model:show="sendDialogVisible">
      <WorkerSendSelection :w="sendDialogWorker" v-model:show="sendDialogVisible"/>
    </ModalDialog>

    <ModalDialog v-model:show="lodgingDialogVisible">
      <LodgingSelection :tk="lodgingDialogTown" :o="lodgingDialogData" v-model:show="lodgingDialogVisible"/>
    </ModalDialog>

    <ModalDialog v-model:show="housesDialogVisible">
      <HousesSelection :tk="housesDialogTown" v-model:show="housesDialogVisible"/>
    </ModalDialog>
  </main>
</template>

<style scoped>
.workers-page {
  max-width: 1000px;
  margin: 0 auto;
  padding: 16px;
}
.hint {
  color: var(--muted, #888);
  margin-bottom: 12px;
}
.workers-toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
table {
  width: 100%;
  border-collapse: collapse;
}
</style>
