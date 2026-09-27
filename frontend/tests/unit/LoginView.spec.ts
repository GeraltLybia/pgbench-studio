import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import LoginView from '@/views/LoginView.vue'
import { jsonResponse } from './helpers'

function setup(responses: Record<string, Response[]>) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const path = input instanceof Request ? input.url : String(input)
    const queue = responses[path]
    const next = queue?.shift()
    return Promise.resolve(next ?? jsonResponse(404))
  })
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('matchMedia', () => ({
    matches: false,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'login', component: LoginView },
      { path: '/connect', name: 'connect', component: { template: '<div />' } },
      { path: '/history', name: 'history', component: { template: '<div />' } },
      { path: '/password', name: 'password', component: { template: '<div />' } },
    ],
  })
  return { router, fetchMock }
}

async function mountAt(router: ReturnType<typeof setup>['router'], path: string) {
  await router.push(path)
  const wrapper = mount(LoginView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

async function fill(wrapper: Awaited<ReturnType<typeof mountAt>>, user: string, pass: string) {
  const inputs = wrapper.findAll('input')
  await inputs[0]!.setValue(user)
  await inputs[1]!.setValue(pass)
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('LoginView', () => {
  it('validates empty fields without calling the API', async () => {
    const { router, fetchMock } = setup({})
    const wrapper = await mountAt(router, '/login')
    fetchMock.mockClear()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('Введите логин')
    expect(wrapper.text()).toContain('Введите пароль')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows remaining attempts after a failed login', async () => {
    const { router } = setup({
      '/api/auth/login': [
        jsonResponse(401, {
          detail: {
            code: 'invalid_credentials',
            message: 'Неверный логин или пароль',
            attempts_left: 2,
            lockout_min: 5,
          },
        }),
      ],
    })
    const wrapper = await mountAt(router, '/login')
    await fill(wrapper, 'zakhar', 'wrong')
    expect(wrapper.get('[role="alert"]').text()).toContain('Неверный логин или пароль')
    expect(wrapper.text()).toContain('Осталось 2 попытки, затем вход будет заблокирован на 5 минут.')
    expect(wrapper.findAll('input.invalid')).toHaveLength(2)
  })

  it('explains a lockout', async () => {
    const { router } = setup({
      '/api/auth/login': [
        jsonResponse(429, {
          detail: { code: 'login_locked', message: 'x', retry_after_s: 240 },
        }),
      ],
    })
    const wrapper = await mountAt(router, '/login')
    await fill(wrapper, 'zakhar', 'wrong')
    expect(wrapper.text()).toContain('Попробуйте через 4 минуты')
  })

  it('returns to the requested page after login', async () => {
    const me = { id: 1, username: 'zakhar', role: 'editor', must_change_password: false }
    const { router } = setup({ '/api/auth/login': [jsonResponse(200, me)] })
    const wrapper = await mountAt(router, '/login?redirect=/history')
    await fill(wrapper, 'zakhar', 'right')
    expect(router.currentRoute.value.fullPath).toBe('/history')
  })

  it('sends users with a temporary password to the password change', async () => {
    const me = { id: 1, username: 'zakhar', role: 'editor', must_change_password: true }
    const { router } = setup({ '/api/auth/login': [jsonResponse(200, me)] })
    const wrapper = await mountAt(router, '/login?redirect=/history')
    await fill(wrapper, 'zakhar', 'temp')
    expect(router.currentRoute.value.name).toBe('password')
  })
})
