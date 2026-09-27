import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { systemApi, type Readiness, type SystemHealth, type SystemInfo } from '@/api/system'

export type Indicator = 'ok' | 'warning' | 'fail' | 'unknown'

export const INDICATOR_LABELS: Record<Indicator, string> = {
  ok: 'Система работает',
  warning: 'Есть предупреждения',
  fail: 'Система неисправна',
  unknown: 'Состояние неизвестно',
}

export const useSystemStore = defineStore('system', () => {
  const health = ref<SystemHealth | null>(null)
  const info = ref<SystemInfo | null>(null)
  const readiness = ref<Readiness | null>(null)
  const healthError = ref(false)

  const indicator = computed<Indicator>(() => {
    if (health.value) return health.value.status
    if (readiness.value) return readiness.value.status === 'ok' ? 'ok' : 'fail'
    return 'unknown'
  })

  const pgbenchVersion = computed(
    () => info.value?.pgbench_version ?? readiness.value?.pgbench_version ?? null,
  )

  /** Major version for captions like «pgbench 18». */
  const pgbenchMajor = computed(() => pgbenchVersion.value?.split('.')[0] ?? null)

  async function loadHealth(): Promise<void> {
    try {
      health.value = await systemApi.health()
      healthError.value = false
    } catch {
      healthError.value = true
    }
  }

  async function loadInfo(): Promise<void> {
    info.value = await systemApi.info()
  }

  async function loadReadiness(): Promise<void> {
    readiness.value = await systemApi.readiness()
  }

  return {
    health,
    info,
    readiness,
    healthError,
    indicator,
    pgbenchVersion,
    pgbenchMajor,
    loadHealth,
    loadInfo,
    loadReadiness,
  }
})
