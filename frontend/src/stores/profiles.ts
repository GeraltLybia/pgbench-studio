import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ApiError } from '@/api/http'
import {
  profilesApi,
  type ConnectionTestResult,
  type Profile,
  type ProfileCreate,
} from '@/api/profiles'
import { FINISHED_STATUSES, runsApi, type Run } from '@/api/runs'
import { fieldErrors, type FieldErrors } from '@/validation/password'
import {
  connectionSchema,
  defaultProfileName,
  emptyConnection,
  type ConnectionForm,
} from '@/validation/profile'

export const ACTIVE_PROFILE_KEY = 'pgbs-active-profile'
export const INIT_RUN_KEY = 'pgbs-init-run'
const POLL_MS = 1000

export type ConnectionField = keyof ConnectionForm

function readNumber(key: string): number | null {
  try {
    const value = Number(localStorage.getItem(key))
    return Number.isInteger(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

function writeNumber(key: string, value: number | null): void {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, String(value))
  } catch {
    // storage unavailable: the choice just is not remembered
  }
}

function formFromProfile(profile: Profile): ConnectionForm {
  return {
    host: profile.host,
    port: String(profile.port),
    dbname: profile.dbname,
    user: profile.user,
    sslmode: profile.sslmode,
    app_name: profile.app_name,
    connect_timeout_s: String(profile.connect_timeout_s),
    password: '',
  }
}

/**
 * Fingerprint of everything a connection check depends on. A stored result counts only while
 * the fingerprint matches: any edit or another profile means «not checked».
 */
export function paramsHash(profileId: number | null, form: ConnectionForm): string {
  return JSON.stringify([
    profileId,
    form.host.trim(),
    String(form.port).trim(),
    form.dbname,
    form.user,
    form.sslmode,
    form.app_name,
    String(form.connect_timeout_s).trim(),
    form.password,
  ])
}

export const useProfilesStore = defineStore('profiles', () => {
  const profiles = ref<Profile[]>([])
  const loaded = ref(false)
  const activeId = ref<number | null>(readNumber(ACTIVE_PROFILE_KEY))
  const form = ref<ConnectionForm>(emptyConnection())
  const errors = ref<FieldErrors<ConnectionField>>({})
  const check = ref<{ hash: string; result: ConnectionTestResult } | null>(null)
  const checking = ref(false)
  const saving = ref(false)
  const initRun = ref<Run | null>(null)
  let bootstrapped: Promise<void> | null = null
  let pollTimer: ReturnType<typeof setTimeout> | null = null

  const active = computed(() => profiles.value.find((p) => p.id === activeId.value) ?? null)
  const hash = computed(() => paramsHash(activeId.value, form.value))
  /** Result of the last check, only if it was made with the current parameters. */
  const result = computed(() =>
    check.value && check.value.hash === hash.value ? check.value.result : null,
  )
  const connected = computed(() => result.value?.ok === true)
  const initRunning = computed(
    () => initRun.value !== null && !FINISHED_STATUSES.includes(initRun.value.status),
  )

  async function load(): Promise<void> {
    profiles.value = await profilesApi.list()
    loaded.value = true
    if (activeId.value !== null && !active.value) select(null)
    else if (active.value && !form.value.host) form.value = formFromProfile(active.value)
  }

  function select(id: number | null): void {
    activeId.value = id
    writeNumber(ACTIVE_PROFILE_KEY, id)
    const profile = profiles.value.find((p) => p.id === id)
    form.value = profile ? formFromProfile(profile) : emptyConnection()
    errors.value = {}
  }

  function validate() {
    const parsed = connectionSchema.safeParse(form.value)
    errors.value = parsed.success ? {} : fieldErrors<ConnectionField>(parsed.error)
    return parsed.success ? parsed.data : null
  }

  async function runCheck(): Promise<ConnectionTestResult | null> {
    const values = validate()
    if (!values) return null
    const requestHash = hash.value
    checking.value = true
    try {
      const { password, ...fields } = values
      const res = await profilesApi.test({
        ...fields,
        profile_id: activeId.value,
        password: password === '' ? null : password,
      })
      check.value = { hash: requestHash, result: res }
      return res
    } finally {
      checking.value = false
    }
  }

  async function save(): Promise<Profile | null> {
    const values = validate()
    if (!values) return null
    const { password, ...fields } = values
    saving.value = true
    try {
      let saved: Profile
      if (active.value) {
        saved = await profilesApi.update(active.value.id, {
          ...fields,
          name: active.value.name,
          password: password === '' ? null : password,
          clear_password: false,
        })
      } else {
        saved = await createWithFreeName(fields, password)
      }
      const oldHash = hash.value
      profiles.value = [...profiles.value.filter((p) => p.id !== saved.id), saved].sort((a, b) =>
        a.name.localeCompare(b.name),
      )
      activeId.value = saved.id
      writeNumber(ACTIVE_PROFILE_KEY, saved.id)
      // Saving does not change the parameters: a check made just before stays valid.
      if (check.value?.hash === oldHash) check.value = { ...check.value, hash: hash.value }
      return saved
    } finally {
      saving.value = false
    }
  }

  async function createWithFreeName(
    fields: Omit<ProfileCreate, 'name' | 'password'>,
    password: string,
  ): Promise<Profile> {
    const base = defaultProfileName(fields.host, fields.dbname)
    for (let n = 1; n <= 20; n++) {
      const name = n === 1 ? base : `${base} (${n})`
      try {
        return await profilesApi.create({
          ...fields,
          name,
          password: password === '' ? null : password,
        })
      } catch (error) {
        if (!(error instanceof ApiError) || error.code !== 'profile_exists') throw error
      }
    }
    throw new ApiError(409, { code: 'profile_exists', message: 'Не удалось подобрать имя профиля' })
  }

  async function remove(): Promise<void> {
    if (!active.value) return
    await profilesApi.remove(active.value.id)
    profiles.value = profiles.value.filter((p) => p.id !== activeId.value)
    select(null)
  }

  /** On app start: load profiles and re-check the remembered one automatically. */
  function bootstrap(canTest: boolean): Promise<void> {
    bootstrapped ??= (async () => {
      await load()
      if (canTest && active.value) await runCheck().catch(() => null)
      const initId = readNumber(INIT_RUN_KEY)
      if (initId !== null) void followInit(initId)
    })()
    return bootstrapped
  }

  async function startInit(body: {
    scale: number
    fillfactor: number
    foreign_keys: boolean
    unlogged: boolean
    confirm_dbname: string
    confirm_large: boolean
  }): Promise<void> {
    if (!active.value) return
    const { run_id } = await profilesApi.init(active.value.id, body)
    writeNumber(INIT_RUN_KEY, run_id)
    await followInit(run_id)
  }

  async function followInit(runId: number): Promise<void> {
    if (pollTimer) clearTimeout(pollTimer)
    try {
      initRun.value = await runsApi.get(runId)
    } catch {
      writeNumber(INIT_RUN_KEY, null)
      initRun.value = null
      return
    }
    if (FINISHED_STATUSES.includes(initRun.value.status)) {
      writeNumber(INIT_RUN_KEY, null)
      // Fresh facts (tables, scale) after initialisation.
      if (initRun.value.status === 'completed' && initRun.value.profile_id === activeId.value) {
        await runCheck().catch(() => null)
      }
      return
    }
    pollTimer = setTimeout(() => void followInit(runId), POLL_MS)
  }

  function dismissInit(): void {
    initRun.value = null
  }

  function reset(): void {
    if (pollTimer) clearTimeout(pollTimer)
    bootstrapped = null
    check.value = null
    initRun.value = null
  }

  return {
    profiles,
    loaded,
    activeId,
    active,
    form,
    errors,
    checking,
    saving,
    result,
    connected,
    initRun,
    initRunning,
    load,
    select,
    runCheck,
    save,
    remove,
    bootstrap,
    startInit,
    followInit,
    dismissInit,
    reset,
  }
})
