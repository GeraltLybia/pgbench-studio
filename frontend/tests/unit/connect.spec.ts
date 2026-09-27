import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Role } from '@/auth/permissions'
import ConnectionCheck from '@/components/connect/ConnectionCheck.vue'
import ProfileForm from '@/components/connect/ProfileForm.vue'
import ConfirmByTyping from '@/components/ui/ConfirmByTyping.vue'
import { useAuthStore } from '@/stores/auth'
import { useProfilesStore } from '@/stores/profiles'
import type { ConnectionTestResult } from '@/api/profiles'
import { CHECK_FAIL, CHECK_OK, PROFILE } from './fixtures'
import { jsonResponse } from './helpers'

/** Intl uses non-breaking spaces in numbers; compare with plain ones. */
function plain(text: string): string {
  return text.replace(/\s/g, ' ')
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(jsonResponse(404))))
})
afterEach(() => vi.unstubAllGlobals())

/** Select the fixture profile and run a check that answers with `result`. */
async function withResult(result: ConnectionTestResult) {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(jsonResponse(200, result))))
  const store = useProfilesStore()
  if (store.profiles.length === 0) store.profiles = [PROFILE]
  if (store.form.host === '') store.select(7)
  await store.runCheck()
  return store
}

describe('ConnectionCheck', () => {
  it('shows server facts after a successful check', async () => {
    await withResult(CHECK_OK)
    const text = plain(mount(ConnectionCheck).text())
    expect(text).toContain('Соединение установлено')
    expect(text).toContain('Проверено сегодня в')
    expect(text).toContain('PostgreSQL 16.4')
    expect(text).toContain('18.6 · совместим')
    expect(text).toContain('200 (свободно 184)')
    expect(text).toContain('найдены · scale ≈ 100')
    expect(text).toContain('10 000 000 строк')
  })

  it('shows compatibility warnings without blocking', async () => {
    await withResult({ ...CHECK_OK, warnings: ['Сервер PostgreSQL 19 новее pgbench 18 на агенте.'] })
    const text = mount(ConnectionCheck).text()
    expect(text).toContain('есть предупреждение')
    expect(text).toContain('новее pgbench 18')
    expect(text).toContain('не блокируется')
  })

  it('explains a failure with the reason, hint and raw PostgreSQL text', async () => {
    await withResult(CHECK_FAIL)
    const wrapper = mount(ConnectionCheck)
    const text = wrapper.text()
    expect(text).toContain('Не удалось подключиться')
    expect(text).toContain('Неверный пользователь или пароль')
    expect(text).toContain('auth_failed')
    expect(text).toContain('pg_hba.conf')
    expect(wrapper.get('details pre').text()).toContain('password authentication failed')
    expect(text).toContain('Настройка нагрузки откроется после успешной проверки соединения')
  })

  it('invites to check when there is no result', () => {
    useProfilesStore()
    expect(mount(ConnectionCheck).text()).toContain('Соединение не проверено')
  })
})

function mountForm(role: Role) {
  useAuthStore().user = { id: 1, username: 'u', role, must_change_password: false }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:p(.*)*', component: { template: '<div />' } }],
  })
  return mount(ProfileForm, { global: { plugins: [router] } })
}

describe('ProfileForm', () => {
  it('keeps «Далее» disabled until the check passes', async () => {
    await withResult(CHECK_FAIL)
    const wrapper = mountForm('editor')
    const next = () => wrapper.findAll('button').find((b) => b.text().includes('Далее'))!
    expect(next().attributes('disabled')).toBeDefined()

    await withResult(CHECK_OK)
    await flushPromises()
    expect(next().attributes('disabled')).toBeUndefined()
  })

  it('shows the saved-password placeholder and the PGPASSWORD note', async () => {
    await withResult(CHECK_OK)
    const wrapper = mountForm('editor')
    const password = wrapper.get('input[type="password"]')
    expect(password.attributes('placeholder')).toBe('пароль сохранён')
    expect(wrapper.text()).toContain('PGPASSWORD, не попадает в командную строку и логи')
  })

  it('is read-only for viewers without check or save', async () => {
    await withResult(CHECK_OK)
    const wrapper = mountForm('viewer')
    const labels = wrapper.findAll('button').map((b) => b.text())
    expect(labels.some((t) => t.includes('Проверить соединение'))).toBe(false)
    expect(labels.some((t) => t.includes('Сохранить профиль'))).toBe(false)
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    expect(wrapper.findAll('input').every((i) => i.attributes('readonly') !== undefined)).toBe(true)
    expect(wrapper.text()).toContain('Пароль сохранён и не показывается')
  })
})

describe('ConfirmByTyping', () => {
  it('confirms only after the exact name is typed', async () => {
    const wrapper = mount(ConfirmByTyping, {
      props: { title: 'Инициализировать?', expected: 'bench', confirmLabel: 'Удалить и пересоздать' },
    })
    const confirm = () => wrapper.findAll('button').find((b) => b.text().includes('Удалить'))!
    expect(confirm().attributes('disabled')).toBeDefined()
    await wrapper.get('input').setValue('Bench')
    expect(confirm().attributes('disabled')).toBeDefined()
    await wrapper.get('input').setValue('bench')
    expect(confirm().attributes('disabled')).toBeUndefined()
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    await wrapper.findAll('button').find((b) => b.text() === 'Отмена')!.trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })
})
