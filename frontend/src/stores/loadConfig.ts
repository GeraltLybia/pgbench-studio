import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import type { RunConfig } from '@/api/runs'
import { scriptsApi, type Builtin, type BuiltinName, type Script, type ScriptDiagnostic } from '@/api/scripts'
import { useProfilesStore } from '@/stores/profiles'
import { fieldErrors, type FieldErrors } from '@/validation/password'
import {
  VARIABLE_NAME,
  defaultParams,
  paramsSchema,
  type LoadParamsForm,
} from '@/validation/runConfig'

export const LOAD_DRAFT_KEY = 'pgbs-load-draft'

interface BaseScenario {
  uid: string
  weight: number
}

export interface BuiltinDraft extends BaseScenario {
  kind: 'builtin'
  name: BuiltinName
}

export interface ScriptDraft extends BaseScenario {
  kind: 'script'
  name: string
  body: string
  /** Library script it came from and its text at that moment («изменён» otherwise). */
  scriptId: number | null
  savedBody: string | null
}

export type ScenarioDraft = BuiltinDraft | ScriptDraft

export interface VariableDraft {
  name: string
  value: string
}

interface Draft {
  params: LoadParamsForm
  scenarios: ScenarioDraft[]
  variables: VariableDraft[]
  selected: string | null
}

let counter = 0
export function newUid(): string {
  counter += 1
  return `s${Date.now().toString(36)}${counter}`
}

function emptyDraft(): Draft {
  return {
    params: defaultParams(),
    scenarios: [{ uid: newUid(), kind: 'builtin', name: 'tpcb-like', weight: 1 }],
    variables: [],
    selected: null,
  }
}

function readDraft(): Draft {
  try {
    const raw = localStorage.getItem(LOAD_DRAFT_KEY)
    if (!raw) return emptyDraft()
    const draft = JSON.parse(raw) as Partial<Draft>
    return {
      params: { ...defaultParams(), ...draft.params },
      scenarios: Array.isArray(draft.scenarios) ? draft.scenarios : [],
      variables: Array.isArray(draft.variables) ? draft.variables : [],
      selected: draft.selected ?? null,
    }
  } catch {
    return emptyDraft()
  }
}

export interface ScriptCheck {
  diagnostics: ScriptDiagnostic[]
  variablesUsed: string[]
  /** Body and context (server version, -D names) the result belongs to; stale ones are ignored. */
  body: string
  context: string
}

export const useLoadConfigStore = defineStore('loadConfig', () => {
  const initial = readDraft()
  const params = ref<LoadParamsForm>(initial.params)
  const scenarios = ref<ScenarioDraft[]>(initial.scenarios)
  const variables = ref<VariableDraft[]>(initial.variables)
  const selected = ref<string | null>(initial.selected)
  const checks = ref<Record<string, ScriptCheck>>({})
  const library = ref<Script[]>([])
  const builtins = ref<Builtin[]>([])

  watch(
    [params, scenarios, variables, selected],
    () => {
      try {
        localStorage.setItem(
          LOAD_DRAFT_KEY,
          JSON.stringify({
            params: params.value,
            scenarios: scenarios.value,
            variables: variables.value,
            selected: selected.value,
          }),
        )
      } catch {
        // storage unavailable: the draft just is not kept
      }
    },
    { deep: true },
  )

  const selectedScenario = computed(
    () => scenarios.value.find((s) => s.uid === selected.value) ?? null,
  )
  const totalWeight = computed(() => scenarios.value.reduce((sum, s) => sum + s.weight, 0))

  function share(s: ScenarioDraft): number {
    return totalWeight.value > 0 ? Math.round((100 * s.weight) / totalWeight.value) : 0
  }

  const parsedParams = computed(() => paramsSchema.safeParse(params.value))
  const paramErrors = computed<FieldErrors<keyof LoadParamsForm>>(() =>
    parsedParams.value.success ? {} : fieldErrors(parsedParams.value.error),
  )

  const variableErrors = computed(() => {
    const seen = new Set<string>()
    return variables.value.map((v) => {
      if (!VARIABLE_NAME.test(v.name)) return 'Имя: латиница, цифры и _'
      if (seen.has(v.name)) return 'Имя повторяется'
      seen.add(v.name)
      return null
    })
  })

  const profiles = useProfilesStore()
  /** Server major from the last successful check: version-specific syntax depends on it. */
  const serverMajor = computed(() =>
    profiles.result?.ok === true ? profiles.result.server_major : null,
  )
  const variableNames = computed(() =>
    variables.value.map((v) => v.name).filter((n) => VARIABLE_NAME.test(n)),
  )
  const context = computed(() => `${serverMajor.value ?? '-'}|${[...variableNames.value].sort().join(',')}`)

  function checkOf(s: ScenarioDraft): ScriptCheck | null {
    const check = checks.value[s.uid]
    return s.kind === 'script' && check && check.body === s.body && check.context === context.value
      ? check
      : null
  }

  const inflight = new Map<string, Promise<ScriptCheck | null>>()

  /** Validate one script on the backend; concurrent calls for the same text share a request. */
  function validate(uid: string): Promise<ScriptCheck | null> {
    const s = scenarios.value.find((x) => x.uid === uid)
    if (!s || s.kind !== 'script') return Promise.resolve(null)
    const fresh = checkOf(s)
    if (fresh) return Promise.resolve(fresh)
    const body = s.body
    const ctx = context.value
    const key = `${uid}|${ctx}|${body}`
    let pending = inflight.get(key)
    if (!pending) {
      pending = scriptsApi
        .validate(body, serverMajor.value, variableNames.value)
        .then((res) => {
          const check: ScriptCheck = {
            diagnostics: res.diagnostics,
            variablesUsed: res.variables_used,
            body,
            context: ctx,
          }
          setCheck(uid, check)
          return check
        })
        .catch(() => null)
        .finally(() => inflight.delete(key))
      inflight.set(key, pending)
    }
    return pending
  }

  /** Validate every custom script whose result is stale. */
  async function validateAll(): Promise<void> {
    await Promise.all(
      scenarios.value.filter((s) => s.kind === 'script' && !checkOf(s)).map((s) => validate(s.uid)),
    )
  }

  function errorCount(s: ScenarioDraft): number {
    return checkOf(s)?.diagnostics.filter((d) => d.severity === 'error').length ?? 0
  }

  function isModified(s: ScenarioDraft): boolean {
    return s.kind === 'script' && s.scriptId !== null && s.body !== s.savedBody
  }

  /** Every custom script has fresh diagnostics for its current text. */
  const allChecked = computed(() =>
    scenarios.value.every((s) => s.kind === 'builtin' || checkOf(s) !== null),
  )

  const config = computed<RunConfig | null>(() => {
    if (!parsedParams.value.success || variableErrors.value.some(Boolean)) return null
    if (scenarios.value.length === 0) return null
    const p = parsedParams.value.data
    return {
      profile_id: 0,
      mode: p.mode,
      duration_s: p.duration_s,
      transactions: p.transactions,
      clients: p.clients,
      threads: p.threads,
      protocol: p.protocol,
      rate_tps: p.rate_tps,
      latency_limit_ms: p.latency_limit_ms,
      vacuum: p.vacuum,
      detailed_log: p.detailed_log,
      sampling_rate: p.sampling_rate,
      variables: variables.value.map((v) => ({ name: v.name, value: v.value })),
      scenarios: scenarios.value.map((s) =>
        s.kind === 'builtin'
          ? { kind: 'builtin' as const, name: s.name, weight: s.weight }
          : { kind: 'script' as const, name: s.name, body: s.body, weight: s.weight, script_id: s.scriptId },
      ),
      confirmed_rules: [],
    }
  })

  async function loadLibrary(): Promise<void> {
    const [scripts, builtinList] = await Promise.all([scriptsApi.list(), scriptsApi.builtins()])
    library.value = scripts
    builtins.value = builtinList
  }

  function addBuiltin(name: BuiltinName): void {
    const item: BuiltinDraft = { uid: newUid(), kind: 'builtin', name, weight: 1 }
    scenarios.value.push(item)
  }

  function uniqueName(base: string): string {
    const names = new Set(scenarios.value.map((s) => s.name))
    if (!names.has(base)) return base
    const stem = base.replace(/\.sql$/, '')
    for (let n = 2; ; n++) {
      const candidate = `${stem}-${n}.sql`
      if (!names.has(candidate)) return candidate
    }
  }

  function addScript(from?: Script): void {
    const item: ScriptDraft = {
      uid: newUid(),
      kind: 'script',
      name: uniqueName(from?.name ?? 'script.sql'),
      body: from?.body ?? '\\set aid random(1, 100000 * :scale)\nSELECT abalance FROM pgbench_accounts WHERE aid = :aid;\n',
      weight: 1,
      scriptId: from?.id ?? null,
      savedBody: from?.body ?? null,
    }
    scenarios.value.push(item)
    selected.value = item.uid
  }

  function remove(uid: string): void {
    scenarios.value = scenarios.value.filter((s) => s.uid !== uid)
    if (selected.value === uid) selected.value = null
  }

  function move(from: number, to: number): void {
    if (from === to || from < 0 || to < 0 || from >= scenarios.value.length) return
    const list = [...scenarios.value]
    const [item] = list.splice(from, 1)
    list.splice(Math.min(to, list.length), 0, item!)
    scenarios.value = list
  }

  function setWeight(uid: string, weight: number): void {
    const s = scenarios.value.find((x) => x.uid === uid)
    if (s) s.weight = Math.min(1000, Math.max(1, Math.round(weight) || 1))
  }

  function setCheck(uid: string, check: ScriptCheck): void {
    checks.value = { ...checks.value, [uid]: check }
  }

  /** Save the script to the library (create, or update the one it came from). */
  async function saveToLibrary(uid: string): Promise<void> {
    const s = scenarios.value.find((x) => x.uid === uid)
    if (!s || s.kind !== 'script') return
    const saved =
      s.scriptId !== null
        ? await scriptsApi.update(s.scriptId, s.name, s.body)
        : await scriptsApi.create(s.name, s.body)
    s.scriptId = saved.id
    s.savedBody = saved.body
    library.value = [...library.value.filter((x) => x.id !== saved.id), saved].sort((a, b) =>
      a.name.localeCompare(b.name),
    )
  }

  /**
   * «Повторить»: the parameters, variables and scenario texts a run was started with
   * (`run.config.run_config`), exactly as stored, even if library scripts changed since.
   */
  function applyRun(config: RunConfig): void {
    const text = (v: number | null | undefined) => (v == null ? '' : String(v))
    params.value = {
      ...defaultParams(),
      mode: config.mode ?? 'duration',
      duration_s: text(config.duration_s) || defaultParams().duration_s,
      transactions: text(config.transactions) || defaultParams().transactions,
      clients: text(config.clients),
      threads: text(config.threads),
      protocol: config.protocol ?? 'simple',
      rate_tps: text(config.rate_tps),
      latency_limit_ms: text(config.latency_limit_ms),
      vacuum: config.vacuum ?? true,
      detailed_log: config.detailed_log ?? false,
      sampling_rate: text(config.sampling_rate),
    }
    variables.value = (config.variables ?? []).map((v) => ({ name: v.name, value: v.value }))
    scenarios.value = config.scenarios.map((sc): ScenarioDraft =>
      sc.kind === 'builtin'
        ? { uid: newUid(), kind: 'builtin', name: sc.name, weight: sc.weight ?? 1 }
        : {
            uid: newUid(),
            kind: 'script',
            name: sc.name,
            body: sc.body,
            weight: sc.weight ?? 1,
            scriptId: sc.script_id ?? null,
            savedBody: sc.script_id != null ? sc.body : null,
          },
    )
    selected.value = scenarios.value.find((sc) => sc.kind === 'script')?.uid ?? null
    checks.value = {}
  }

  function reset(): void {
    const fresh = emptyDraft()
    params.value = fresh.params
    scenarios.value = fresh.scenarios
    variables.value = []
    selected.value = null
    checks.value = {}
  }

  return {
    params,
    scenarios,
    variables,
    selected,
    selectedScenario,
    checks,
    serverMajor,
    variableNames,
    context,
    validate,
    validateAll,
    library,
    builtins,
    totalWeight,
    parsedParams,
    paramErrors,
    variableErrors,
    allChecked,
    config,
    share,
    checkOf,
    errorCount,
    isModified,
    loadLibrary,
    addBuiltin,
    addScript,
    remove,
    move,
    setWeight,
    setCheck,
    saveToLibrary,
    applyRun,
    reset,
  }
})
