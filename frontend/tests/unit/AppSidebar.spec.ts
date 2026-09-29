import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Role } from '@/auth/permissions'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import { useAuthStore } from '@/stores/auth'
import { useProfilesStore } from '@/stores/profiles'
import { CHECK_OK, PROFILE } from './fixtures'
import { jsonResponse } from './helpers'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(jsonResponse(500))))
  vi.stubGlobal('matchMedia', () => ({
    matches: false,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
})
afterEach(() => vi.unstubAllGlobals())

function mountAs(role: Role) {
  useAuthStore().user = { id: 1, username: 'u', role, must_change_password: false }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:p(.*)*', component: { template: '<div />' } }],
  })
  return mount(AppSidebar, { global: { plugins: [router] } })
}

describe('AppSidebar', () => {
  it.each([
    ['viewer', false],
    ['editor', false],
    ['admin', true],
  ] as const)('shows «Пользователи» to %s: %s', (role, visible) => {
    const text = mountAs(role).text()
    expect(text.includes('Пользователи')).toBe(visible)
    expect(text).toContain('История запусков')
  })

  it('keeps steps without a run disabled', () => {
    const wrapper = mountAs('editor')
    const disabled = wrapper.findAll('[aria-disabled="true"]').map((el) => el.text())
    expect(disabled.some((t) => t.includes('Выполнение'))).toBe(true)
    expect(disabled.some((t) => t.includes('Отчёт'))).toBe(true)
  })
})

describe('AppSidebar · active run', () => {
  it('links «Выполнение» to the running test with «идёт»', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const path = input instanceof Request ? input.url : String(input)
        return Promise.resolve(
          path === '/api/runs/active'
            ? jsonResponse(200, { run_id: 5, kind: 'bench', status: 'running' })
            : jsonResponse(500),
        )
      }),
    )
    const wrapper = mountAs('viewer')
    await vi.waitFor(() => expect(wrapper.find('a[href="/runs/5"]').exists()).toBe(true))
    expect(wrapper.get('a[href="/runs/5"]').text()).toContain('идёт')
  })
})

describe('AppSidebar · saved profile', () => {
  it('checks the saved profile as soon as the app opens, on any screen', async () => {
    localStorage.setItem('pgbs-active-profile', String(PROFILE.id))
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const path = input instanceof Request ? input.url : String(input)
        calls.push(path)
        if (path === '/api/profiles') return Promise.resolve(jsonResponse(200, [PROFILE]))
        if (path === '/api/profiles/test') return Promise.resolve(jsonResponse(200, CHECK_OK))
        return Promise.resolve(jsonResponse(500))
      }),
    )
    mountAs('editor')
    await vi.waitFor(() => expect(calls).toContain('/api/profiles/test'))
    expect(useProfilesStore().connected).toBe(true)
    localStorage.clear()
  })

  it('viewers only load profiles: they may not test connections', async () => {
    localStorage.setItem('pgbs-active-profile', String(PROFILE.id))
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const path = input instanceof Request ? input.url : String(input)
        calls.push(path)
        return Promise.resolve(path === '/api/profiles' ? jsonResponse(200, [PROFILE]) : jsonResponse(500))
      }),
    )
    mountAs('viewer')
    await vi.waitFor(() => expect(calls).toContain('/api/profiles'))
    expect(calls).not.toContain('/api/profiles/test')
    localStorage.clear()
  })
})

it('waits for the role before checking the saved profile (page reload)', async () => {
  localStorage.setItem('pgbs-active-profile', String(PROFILE.id))
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const path = input instanceof Request ? input.url : String(input)
      calls.push(path)
      if (path === '/api/profiles') return Promise.resolve(jsonResponse(200, [PROFILE]))
      if (path === '/api/profiles/test') return Promise.resolve(jsonResponse(200, CHECK_OK))
      return Promise.resolve(jsonResponse(500))
    }),
  )
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:p(.*)*', component: { template: '<div />' } }] })
  mount(AppSidebar, { global: { plugins: [router] } }) // no user yet: /api/auth/me still pending
  await new Promise((r) => setTimeout(r, 10))
  expect(calls).not.toContain('/api/profiles')
  useAuthStore().user = { id: 1, username: 'u', role: 'editor', must_change_password: false }
  await vi.waitFor(() => expect(calls).toContain('/api/profiles/test'))
  localStorage.clear()
})
