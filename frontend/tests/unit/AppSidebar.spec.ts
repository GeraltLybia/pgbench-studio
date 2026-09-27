import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Role } from '@/auth/permissions'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import { useAuthStore } from '@/stores/auth'
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
