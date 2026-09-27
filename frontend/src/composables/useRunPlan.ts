/**
 * What the form knows before a run: limit findings, script findings, what needs confirmation
 * and why the start button is blocked. The backend repeats all of it on POST /api/runs.
 */
import { computed } from 'vue'
import { useLoadConfigStore } from '@/stores/loadConfig'
import { useProfilesStore } from '@/stores/profiles'
import { useSystemStore } from '@/stores/system'
import { checkLimits, type LimitFinding } from '@/validation/runConfig'

export interface PlanItem {
  ruleId: string
  level: 'error' | 'danger' | 'warning' | 'attention'
  message: string
  scenario?: string
  line?: number
}

export function useRunPlan() {
  const store = useLoadConfigStore()
  const profiles = useProfilesStore()
  const system = useSystemStore()

  const limitFindings = computed<LimitFinding[]>(() => {
    if (!store.parsedParams.success) return []
    const p = store.parsedParams.data
    const check = profiles.result?.ok === true ? profiles.result : null
    const pgbench = system.info?.pgbench_version ?? check?.pgbench_version ?? null
    return checkLimits(p, {
      limits: system.info?.limits ?? {
        connections_reserve: 5,
        max_duration_s: 14400,
        max_transactions: 100_000_000,
      },
      freeConnections: check?.free_connections ?? null,
      cpuCount: system.info?.cpu_count ?? 1,
      serverMajor: check?.server_major ?? null,
      pgbenchMajor: pgbench ? Number(pgbench.split('.')[0]) : null,
    })
  })

  const scriptItems = computed<PlanItem[]>(() =>
    store.scenarios.flatMap((s) => {
      const check = store.checkOf(s)
      if (!check) return []
      return check.diagnostics.map((d) => ({
        ruleId: `sql.${d.rule ?? 'syntax'}@${s.name}:${d.line}`,
        level: d.severity === 'warning' ? ('attention' as const) : d.severity,
        message: d.message,
        scenario: s.name,
        line: d.line,
      }))
    }),
  )

  const items = computed<PlanItem[]>(() => [
    ...limitFindings.value.map((f) => ({ ruleId: f.ruleId, level: f.level, message: f.message })),
    ...scriptItems.value,
  ])

  const toConfirm = computed(() =>
    items.value.filter((i) => i.level === 'danger' || i.level === 'warning'),
  )
  const attention = computed(() => items.value.filter((i) => i.level === 'attention'))

  const blockedReason = computed<string | null>(() => {
    if (!profiles.connected) return 'Сначала успешно проверьте соединение'
    if (!store.parsedParams.success) return 'Исправьте параметры нагрузки'
    if (store.variableErrors.some(Boolean)) return 'Исправьте переменные -D'
    if (store.scenarios.length === 0) return 'Добавьте хотя бы один сценарий'
    const badName = store.scenarios.find((s) => s.kind === 'script' && !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(s.name))
    if (badName) return `Исправьте имя сценария ${badName.name}`
    if (!store.allChecked) return 'Проверяем сценарии…'
    const withError = store.scenarios.find((s) => store.errorCount(s) > 0)
    if (withError) return `Исправьте ошибку в ${withError.name}`
    const limitError = limitFindings.value.find((f) => f.level === 'error')
    if (limitError) return limitError.message
    return null
  })

  return { limitFindings, items, toConfirm, attention, blockedReason }
}
