import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import { useSystemStore } from '@/stores/system'
import { jsonResponse, mockFetch } from './helpers'

const viewer = { id: 2, username: 'v', role: 'viewer', must_change_password: false }

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('auth store', () => {
  it('treats 401 from /me as logged out', async () => {
    mockFetch(jsonResponse(401, { detail: { code: 'not_authenticated', message: 'x' } }))
    const auth = useAuthStore()
    await expect(auth.fetchMe()).resolves.toBeNull()
    expect(auth.loaded).toBe(true)
    expect(auth.can('history.view')).toBe(false)
  })

  it('rethrows other errors from /me', async () => {
    mockFetch(jsonResponse(500))
    const auth = useAuthStore()
    await expect(auth.fetchMe()).rejects.toMatchObject({ status: 500 })
    expect(auth.loaded).toBe(true)
  })

  it('exposes role checks after login and clears on logout', async () => {
    mockFetch(jsonResponse(200, viewer), new Response(null, { status: 204 }))
    const auth = useAuthStore()
    await auth.login('v', 'secret')
    expect(auth.role).toBe('viewer')
    expect(auth.can('history.view')).toBe(true)
    expect(auth.can('runs.start')).toBe(false)
    expect(auth.can('users.manage')).toBe(false)
    await auth.logout()
    expect(auth.user).toBeNull()
  })

  it('updates the user after a password change', async () => {
    mockFetch(
      jsonResponse(200, { ...viewer, must_change_password: true }),
      jsonResponse(200, viewer),
    )
    const auth = useAuthStore()
    await auth.login('v', 'temp')
    expect(auth.mustChangePassword).toBe(true)
    await auth.changePassword('temp', 'new-password')
    expect(auth.mustChangePassword).toBe(false)
  })
})

describe('system store', () => {
  it('derives the indicator from health, then readiness', async () => {
    const system = useSystemStore()
    expect(system.indicator).toBe('unknown')

    mockFetch(jsonResponse(503, { status: 'fail', failed: ['pgbench'], pgbench_version: null }))
    await system.loadReadiness()
    expect(system.indicator).toBe('fail')

    mockFetch(jsonResponse(200, { status: 'warning', checked_at: '2026-09-27T10:00:00Z', checks: [] }))
    await system.loadHealth()
    expect(system.indicator).toBe('warning')
  })

  it('keeps the pgbench major version for captions', async () => {
    mockFetch(jsonResponse(200, { status: 'ok', failed: [], pgbench_version: '18.1' }))
    const system = useSystemStore()
    await system.loadReadiness()
    expect(system.pgbenchMajor).toBe('18')
  })

  it('flags a failed health request', async () => {
    mockFetch(jsonResponse(500))
    const system = useSystemStore()
    await system.loadHealth()
    expect(system.healthError).toBe(true)
  })

  it('treats an unreachable probe as unknown', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    const system = useSystemStore()
    await system.loadReadiness()
    expect(system.indicator).toBe('unknown')
  })
})
