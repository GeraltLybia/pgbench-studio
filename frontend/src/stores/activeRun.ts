import { defineStore } from 'pinia'
import { ref } from 'vue'
import { runsApi, type ActiveRun } from '@/api/runs'

/** The run in progress on the agent, for «Выполнение · идёт» in the menu. */
export const ACTIVE_POLL_MS = 5000

export const useActiveRunStore = defineStore('activeRun', () => {
  const active = ref<ActiveRun | null>(null)

  async function refresh(): Promise<void> {
    try {
      active.value = await runsApi.active()
    } catch {
      // keep the last known value; the menu is a convenience
    }
  }

  function set(runId: number): void {
    active.value = { run_id: runId, kind: 'bench', status: 'running' }
  }

  function clear(runId: number): void {
    if (active.value?.run_id === runId) active.value = { run_id: null, kind: null, status: null }
  }

  return { active, refresh, set, clear }
})
