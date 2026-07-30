<script setup>
import { ref } from 'vue'
import { useUserStore } from '../stores/user'
import { useEmpireStorehouseStore } from '../stores/empireStorehouse'
import ModalDialog from './ModalDialog.vue'

// Global nav-bar affordance so the CURRENT empire (whatever's live on the
// map right now, not just an optimize result) can be snapshotted from any
// page, before something that overwrites it - most notably running Optimize
// with "Extend current empire" checked, which replaces userStore's live
// state with the solve result. empireStorehouse.save() already reads
// straight from live userStore state, same as OptimizeView.vue's own
// "Save to storehouse" button; this just gives it a second, always-visible
// entry point that doesn't require having just run a solve.
const userStore = useUserStore()
const empireStorehouse = useEmpireStorehouseStore()

const dialogVisible = ref(false)
const name = ref('')
const notes = ref('')
const saving = ref(false)

function openDialog() {
  const now = new Date()
  name.value = `Backup - ${now.toLocaleDateString()} ${now.toLocaleTimeString()}`
  notes.value = ''
  dialogVisible.value = true
}

async function confirmSave() {
  if (!name.value) return
  saving.value = true
  try {
    await empireStorehouse.save(name.value, notes.value)
    dialogVisible.value = false
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <button class="seb-btn" :disabled="!userStore.userWorkers.length" @click="openDialog" title="Save the current empire to the storehouse, before optimizing or importing over it">
    Save current empire
  </button>

  <ModalDialog v-model:show="dialogVisible">
    <h3>Save current empire</h3>
    <div class="seb-field">
      <label>Name</label>
      <input type="text" v-model="name" />
    </div>
    <div class="seb-field">
      <label>Notes</label>
      <input type="text" v-model="notes" placeholder="optional" />
    </div>
    <div class="seb-actions">
      <button class="seb-btn primary" :disabled="!name || saving" @click="confirmSave">
        {{ saving ? 'Saving...' : 'Save' }}
      </button>
    </div>
  </ModalDialog>
</template>

<style scoped>
.seb-btn {
  background: var(--color-background-soft, transparent);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
  font-family: inherit;
}
.seb-btn:hover:not(:disabled) {
  border-color: var(--color-text);
}
.seb-btn:disabled {
  opacity: .4;
  cursor: not-allowed;
}
.seb-btn.primary {
  font-weight: 600;
}
.seb-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.seb-field label {
  color: var(--color-text);
  opacity: .7;
  font-size: 13px;
}
.seb-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
