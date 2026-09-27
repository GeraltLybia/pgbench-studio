import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ACTIVE_PROFILE_KEY, INIT_RUN_KEY, paramsHash, useProfilesStore } from '@/stores/profiles'
import { emptyConnection } from '@/validation/profile'
import { CHECK_FAIL, CHECK_OK, PROFILE, run } from './fixtures'
import { jsonResponse } from './helpers'

type Handler = (init: RequestInit | undefined) => Response

let routes: Record<string, Handler[]>
let calls: { path: string; method: string; body: unknown }[]

function on(method: string, path: string, ...handlers: Handler[]): void {
  routes[`${method} ${path}`] = handlers
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  routes = {}
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = input instanceof Request ? input.url : String(input)
      const method = init?.method ?? 'GET'
      calls.push({ path, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
      const queue = routes[`${method} ${path}`]
      const handler = queue && queue.length > 1 ? queue.shift()! : queue?.[0]
      return Promise.resolve(handler ? handler(init) : jsonResponse(404))
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('paramsHash', () => {
  it('changes with any connection parameter and the profile', () => {
    const form = emptyConnection()
    const base = paramsHash(1, form)
    expect(paramsHash(1, { ...form })).toBe(base)
    expect(paramsHash(2, form)).not.toBe(base)
    for (const key of Object.keys(form) as (keyof typeof form)[]) {
      const changed = { ...form, [key]: key === 'sslmode' ? 'require' : `${form[key]}x` }
      expect(paramsHash(1, changed), key).not.toBe(base)
    }
  })
})

describe('profiles store', () => {
  it('restores the remembered profile into the form without a password', async () => {
    localStorage.setItem(ACTIVE_PROFILE_KEY, '7')
    on('GET', '/api/profiles', () => jsonResponse(200, [PROFILE]))
    const store = useProfilesStore()
    await store.load()
    expect(store.active?.name).toBe('stage-db · bench')
    expect(store.form.host).toBe('stage-db.internal')
    expect(store.form.port).toBe('5432')
    expect(store.form.password).toBe('')
  })

  it('forgets a remembered profile that no longer exists', async () => {
    localStorage.setItem(ACTIVE_PROFILE_KEY, '99')
    on('GET', '/api/profiles', () => jsonResponse(200, [PROFILE]))
    const store = useProfilesStore()
    await store.load()
    expect(store.activeId).toBeNull()
    expect(localStorage.getItem(ACTIVE_PROFILE_KEY)).toBeNull()
  })

  it('keeps a check result only for the parameters it was made with', async () => {
    on('GET', '/api/profiles', () => jsonResponse(200, [PROFILE, { ...PROFILE, id: 8, name: 'b' }]))
    on('POST', '/api/profiles/test', () => jsonResponse(200, CHECK_OK))
    const store = useProfilesStore()
    await store.load()
    store.select(7)
    await store.runCheck()
    expect(store.connected).toBe(true)

    store.form.host = 'other-host'
    expect(store.connected).toBe(false)
    expect(store.result).toBeNull()
    store.form.host = 'stage-db.internal'
    expect(store.connected).toBe(true)

    store.select(8)
    expect(store.connected).toBe(false)
  })

  it('sends the profile id and no password so the stored one is used', async () => {
    on('GET', '/api/profiles', () => jsonResponse(200, [PROFILE]))
    on('POST', '/api/profiles/test', () => jsonResponse(200, CHECK_FAIL))
    const store = useProfilesStore()
    await store.load()
    store.select(7)
    const result = await store.runCheck()
    expect(result?.ok).toBe(false)
    expect(store.connected).toBe(false)
    const body = calls.find((c) => c.path === '/api/profiles/test')!.body as Record<string, unknown>
    expect(body).toMatchObject({ profile_id: 7, password: null, port: 5432, connect_timeout_s: 10 })
  })

  it('validates the form before checking', async () => {
    const store = useProfilesStore()
    store.form.host = 'bad host'
    store.form.port = '70000'
    expect(await store.runCheck()).toBeNull()
    expect(store.errors.host).toBeTruthy()
    expect(store.errors.port).toBe('От 1 до 65535')
    expect(store.errors.dbname).toBe('Укажите базу данных')
    expect(calls).toHaveLength(0)
  })

  it('creates a new profile with a default name and keeps the check valid', async () => {
    on('POST', '/api/profiles/test', () => jsonResponse(200, CHECK_OK))
    on(
      'POST',
      '/api/profiles',
      () => jsonResponse(409, { detail: { code: 'profile_exists', message: 'exists' } }),
      () => jsonResponse(201, { ...PROFILE, id: 9, name: 'stage-db · bench (2)' }),
    )
    const store = useProfilesStore()
    Object.assign(store.form, { host: 'stage-db.internal', dbname: 'bench', user: 'u', password: 'p' })
    await store.runCheck()
    const saved = await store.save()
    expect(saved?.id).toBe(9)
    const names = calls.filter((c) => c.path === '/api/profiles').map((c) => (c.body as { name: string }).name)
    expect(names).toEqual(['stage-db · bench', 'stage-db · bench (2)'])
    expect(store.activeId).toBe(9)
    expect(localStorage.getItem(ACTIVE_PROFILE_KEY)).toBe('9')
    expect(store.connected).toBe(true)
  })

  it('updates an existing profile keeping its password when the field is empty', async () => {
    on('GET', '/api/profiles', () => jsonResponse(200, [PROFILE]))
    on('PUT', '/api/profiles/7', () => jsonResponse(200, { ...PROFILE, port: 6432 }))
    const store = useProfilesStore()
    await store.load()
    store.select(7)
    store.form.port = '6432'
    await store.save()
    const body = calls.find((c) => c.method === 'PUT')!.body as Record<string, unknown>
    expect(body).toMatchObject({ name: PROFILE.name, port: 6432, password: null, clear_password: false })
    expect(store.active?.port).toBe(6432)
  })

  it('auto-checks the remembered profile on start, only for roles that may', async () => {
    localStorage.setItem(ACTIVE_PROFILE_KEY, '7')
    on('GET', '/api/profiles', () => jsonResponse(200, [PROFILE]))
    on('POST', '/api/profiles/test', () => jsonResponse(200, CHECK_OK))
    const store = useProfilesStore()
    await store.bootstrap(true)
    await store.bootstrap(true)
    expect(calls.filter((c) => c.path === '/api/profiles/test')).toHaveLength(1)
    expect(store.connected).toBe(true)

    setActivePinia(createPinia())
    calls = []
    const viewerStore = useProfilesStore()
    await viewerStore.bootstrap(false)
    expect(calls.map((c) => c.path)).toEqual(['/api/profiles'])
  })

  it('follows pgbench -i until it finishes and re-checks the connection', async () => {
    vi.useFakeTimers()
    on('GET', '/api/profiles', () => jsonResponse(200, [PROFILE]))
    on('POST', '/api/profiles/test', () => jsonResponse(200, CHECK_OK))
    on('POST', '/api/profiles/7/init', () => jsonResponse(202, { run_id: 3 }))
    on(
      'GET',
      '/api/runs/3',
      () => jsonResponse(200, run('running', 40)),
      () => jsonResponse(200, run('completed')),
    )
    const store = useProfilesStore()
    await store.load()
    store.select(7)
    await store.startInit({
      scale: 1,
      fillfactor: 100,
      foreign_keys: true,
      unlogged: false,
      confirm_dbname: 'bench',
      confirm_large: false,
    })
    expect(store.initRunning).toBe(true)
    expect(store.initRun?.progress?.pct).toBe(40)
    expect(localStorage.getItem(INIT_RUN_KEY)).toBe('3')

    await vi.advanceTimersByTimeAsync(1000)
    expect(store.initRunning).toBe(false)
    expect(store.initRun?.status).toBe('completed')
    expect(localStorage.getItem(INIT_RUN_KEY)).toBeNull()
    expect(calls.filter((c) => c.path === '/api/profiles/test')).toHaveLength(1)
  })

  it('resumes following an init after reload and drops unknown runs', async () => {
    localStorage.setItem(INIT_RUN_KEY, '3')
    on('GET', '/api/profiles', () => jsonResponse(200, []))
    on('GET', '/api/runs/3', () => jsonResponse(200, run('failed')))
    const store = useProfilesStore()
    await store.bootstrap(true)
    await vi.waitFor(() => expect(store.initRun?.status).toBe('failed'))

    localStorage.setItem(INIT_RUN_KEY, '4')
    await store.followInit(4)
    expect(store.initRun).toBeNull()
    expect(localStorage.getItem(INIT_RUN_KEY)).toBeNull()
  })

  it('removes the active profile', async () => {
    on('GET', '/api/profiles', () => jsonResponse(200, [PROFILE]))
    on('DELETE', '/api/profiles/7', () => new Response(null, { status: 204 }))
    const store = useProfilesStore()
    await store.load()
    store.select(7)
    await store.remove()
    expect(store.profiles).toEqual([])
    expect(store.activeId).toBeNull()
    expect(store.form.host).toBe('')
  })
})
