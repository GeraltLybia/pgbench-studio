import { describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'
import type { Role } from '@/auth/permissions'
import { HOME, resolveNavigation, safeRedirect, type SessionState } from '@/router/guards'

function route(
  name: string,
  meta: RouteLocationNormalized['meta'] = {},
  fullPath = `/${name}`,
  query: Record<string, string> = {},
): RouteLocationNormalized {
  return { name, meta, fullPath, query } as unknown as RouteLocationNormalized
}

function session(role: Role | null, mustChangePassword = false, loaded = true): SessionState {
  return { loaded, role, mustChangePassword, ensureLoaded: vi.fn(() => Promise.resolve()) }
}

describe('resolveNavigation', () => {
  it('sends anonymous users to login and remembers the target', async () => {
    expect(await resolveNavigation(route('history'), session(null))).toEqual({
      name: 'login',
      query: { redirect: '/history' },
    })
    expect(await resolveNavigation(route('connect', {}, HOME), session(null))).toEqual({
      name: 'login',
      query: {},
    })
  })

  it('loads the session once before deciding', async () => {
    const s = session('viewer', false, false)
    await resolveNavigation(route('history'), s)
    expect(s.ensureLoaded).toHaveBeenCalledOnce()
  })

  it('lets public routes through and bounces logged-in users off login', async () => {
    expect(await resolveNavigation(route('login', { public: true }), session(null))).toBe(true)
    const loginWithRedirect = route('login', { public: true }, '/login', { redirect: '/history' })
    expect(await resolveNavigation(loginWithRedirect, session('viewer'))).toBe('/history')
  })

  it('forces the password change for temporary passwords', async () => {
    expect(await resolveNavigation(route('history'), session('editor', true))).toEqual({
      name: 'password',
    })
    expect(await resolveNavigation(route('password'), session('editor', true))).toBe(true)
  })

  it('checks the route role', async () => {
    const users = route('users', { role: 'admin' })
    expect(await resolveNavigation(users, session('viewer'))).toBe(HOME)
    expect(await resolveNavigation(users, session('editor'))).toBe(HOME)
    expect(await resolveNavigation(users, session('admin'))).toBe(true)
  })
})

describe('safeRedirect', () => {
  it('accepts only in-app paths', () => {
    expect(safeRedirect('/history?x=1')).toBe('/history?x=1')
    expect(safeRedirect('//evil.example')).toBe(HOME)
    expect(safeRedirect('https://evil.example')).toBe(HOME)
    expect(safeRedirect(undefined)).toBe(HOME)
    expect(safeRedirect(['/a'])).toBe(HOME)
  })
})
