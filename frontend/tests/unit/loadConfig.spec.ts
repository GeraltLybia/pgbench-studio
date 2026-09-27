import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRunPlan } from '@/composables/useRunPlan'
import { LOAD_DRAFT_KEY, useLoadConfigStore, type ScriptDraft } from '@/stores/loadConfig'
import { useProfilesStore } from '@/stores/profiles'
import { useSystemStore } from '@/stores/system'
import { CHECK_OK, PROFILE } from './fixtures'
import { jsonResponse } from './helpers'

let validateCalls: unknown[]

function mockApi(diagnostics: unknown[] = []) {
  validateCalls = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = input instanceof Request ? input.url : String(input)
      if (path === '/api/scripts/validate') {
        validateCalls.push(JSON.parse(init!.body as string))
        return Promise.resolve(jsonResponse(200, { diagnostics, variables_used: ['aid'], variables_defined: [], has_errors: false }))
      }
      if (path === '/api/profiles/test') return Promise.resolve(jsonResponse(200, CHECK_OK))
      if (path.startsWith('/api/scripts')) {
        return Promise.resolve(jsonResponse(200, { id: 5, name: 'hot.sql', body: 'SELECT 2;', updated_at: '2026-09-27T10:00:00Z' }))
      }
      return Promise.resolve(jsonResponse(404))
    }),
  )
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  mockApi()
})
afterEach(() => vi.unstubAllGlobals())

async function connected(): Promise<void> {
  const profiles = useProfilesStore()
  profiles.profiles = [PROFILE]
  profiles.select(7)
  await profiles.runCheck()
  useSystemStore().info = {
    app_version: '0.1.0',
    agent_name: 'a',
    pgbench_version: '18.6',
    dev_mode: true,
    cpu_count: 8,
    default_progress_interval_s: 1,
    cpu_warning_percent: 85,
    min_server_version: 13,
    limits: { connections_reserve: 5, max_duration_s: 14400, max_transactions: 100000000, max_scale: 5000, min_free_disk_gb: 5 },
  }
}

describe('load config store', () => {
  it('starts with tpcb-like and keeps the draft across reloads', async () => {
    const store = useLoadConfigStore()
    expect(store.scenarios.map((s) => s.name)).toEqual(['tpcb-like'])
    store.params.clients = '32'
    store.addScript()
    await Promise.resolve()
    expect(JSON.parse(localStorage.getItem(LOAD_DRAFT_KEY)!).params.clients).toBe('32')

    setActivePinia(createPinia())
    const reloaded = useLoadConfigStore()
    expect(reloaded.params.clients).toBe('32')
    expect(reloaded.scenarios).toHaveLength(2)
  })

  it('computes weight shares, reorders and clamps weights', () => {
    const store = useLoadConfigStore()
    store.addScript()
    const [first, second] = store.scenarios
    store.setWeight(second!.uid, 3)
    expect(store.share(first!)).toBe(25)
    expect(store.share(second!)).toBe(75)
    store.setWeight(first!.uid, 0)
    expect(first!.weight).toBe(1)
    store.setWeight(first!.uid, 5000)
    expect(first!.weight).toBe(1000)
    store.move(0, 1)
    expect(store.scenarios[0]!.uid).toBe(second!.uid)
  })

  it('builds RunConfig from the form', () => {
    const store = useLoadConfigStore()
    store.addScript({ id: 3, name: 'select_hot.sql', body: 'SELECT 1;', updated_at: '' })
    store.variables.push({ name: 'delta', value: '5' })
    store.params.rate_tps = '100'
    expect(store.config).toMatchObject({
      mode: 'duration',
      duration_s: 300,
      clients: 8,
      rate_tps: 100,
      variables: [{ name: 'delta', value: '5' }],
      scenarios: [
        { kind: 'builtin', name: 'tpcb-like', weight: 1 },
        { kind: 'script', name: 'select_hot.sql', body: 'SELECT 1;', script_id: 3 },
      ],
    })
    store.variables.push({ name: 'delta', value: '6' })
    expect(store.variableErrors[1]).toBe('Имя повторяется')
    expect(store.config).toBeNull()
  })

  it('names new scripts uniquely and tracks library changes', () => {
    const store = useLoadConfigStore()
    store.addScript()
    store.addScript()
    const names = store.scenarios.filter((s) => s.kind === 'script').map((s) => s.name)
    expect(names).toEqual(['script.sql', 'script-2.sql'])
    store.addScript({ id: 3, name: 'lib.sql', body: 'SELECT 1;', updated_at: '' })
    const lib = store.scenarios.at(-1) as ScriptDraft
    expect(store.isModified(lib)).toBe(false)
    lib.body = 'SELECT 2;'
    expect(store.isModified(lib)).toBe(true)
  })

  it('validates with the server version and -D names, once per text', async () => {
    await connected()
    const store = useLoadConfigStore()
    store.addScript()
    const uid = store.selected!
    store.variables.push({ name: 'delta', value: '1' })
    await Promise.all([store.validate(uid), store.validate(uid)])
    expect(validateCalls).toHaveLength(1)
    expect(validateCalls[0]).toMatchObject({ server_major: 16, variables: ['delta'] })
    expect(store.allChecked).toBe(true)

    await store.validate(uid)
    expect(validateCalls).toHaveLength(1)
    const script = store.scenarios.find((s) => s.uid === uid) as ScriptDraft
    script.body += '\nSELECT 2;'
    expect(store.allChecked).toBe(false)
    await store.validateAll()
    expect(validateCalls).toHaveLength(2)
  })

  it('saves a script to the library', async () => {
    const store = useLoadConfigStore()
    store.addScript()
    await store.saveToLibrary(store.selected!)
    const script = store.selectedScenario as ScriptDraft
    expect(script.scriptId).toBe(5)
    expect(store.library.map((s) => s.id)).toEqual([5])
  })
})

describe('run plan', () => {
  it('explains why the start is blocked, most important first', async () => {
    const store = useLoadConfigStore()
    const plan = useRunPlan()
    expect(plan.blockedReason.value).toBe('Сначала успешно проверьте соединение')

    await connected()
    expect(plan.blockedReason.value).toBeNull()

    store.params.clients = 'x'
    expect(plan.blockedReason.value).toBe('Исправьте параметры нагрузки')
    store.params.clients = '8'

    store.addScript()
    expect(plan.blockedReason.value).toBe('Проверяем сценарии…')
    mockApi([{ line: 2, col: 1, end_col: 5, severity: 'error', message: 'syntax', rule: null }])
    await store.validateAll()
    expect(plan.blockedReason.value).toBe('Исправьте ошибку в script.sql')

    store.remove(store.selected!)
    store.params.threads = '9'
    store.params.clients = '9'
    expect(plan.blockedReason.value).toContain('ядер на агенте')
  })

  it('lists what needs confirmation with backend rule ids', async () => {
    await connected()
    mockApi([
      { line: 3, col: 1, end_col: 7, severity: 'danger', message: 'DELETE без WHERE', rule: 'delete_without_where' },
      { line: 1, col: 1, end_col: 7, severity: 'warning', message: 'Запись', rule: 'write_non_pgbench' },
    ])
    const store = useLoadConfigStore()
    store.params.duration_s = '4000'
    store.addScript()
    await store.validateAll()
    const plan = useRunPlan()
    expect(plan.toConfirm.value.map((i) => i.ruleId)).toEqual([
      'limits.duration_long',
      'sql.delete_without_where@script.sql:3',
    ])
    expect(plan.attention.value.map((i) => i.ruleId)).toEqual(['sql.write_non_pgbench@script.sql:1'])
  })
})
