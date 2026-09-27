import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import PreRunSummary from '@/components/load/PreRunSummary.vue'
import { useLoadConfigStore } from '@/stores/loadConfig'
import { useProfilesStore } from '@/stores/profiles'
import { CHECK_OK, PROFILE } from './fixtures'
import { jsonResponse } from './helpers'

let startBodies: Record<string, unknown>[]
let startResponses: Response[]

beforeEach(async () => {
  localStorage.clear()
  setActivePinia(createPinia())
  startBodies = []
  startResponses = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = input instanceof Request ? input.url : String(input)
      if (path === '/api/profiles/test') return Promise.resolve(jsonResponse(200, CHECK_OK))
      if (path === '/api/scripts/validate') {
        return Promise.resolve(
          jsonResponse(200, {
            diagnostics: [
              { line: 1, col: 1, end_col: 7, severity: 'danger', message: 'DELETE без WHERE удалит все строки', rule: 'delete_without_where' },
            ],
            variables_used: [],
            variables_defined: [],
            has_errors: false,
          }),
        )
      }
      if (path === '/api/runs') {
        startBodies.push(JSON.parse(init!.body as string) as Record<string, unknown>)
        return Promise.resolve(startResponses.shift() ?? jsonResponse(202, { run_id: 12 }))
      }
      return Promise.resolve(jsonResponse(404))
    }),
  )
  const profiles = useProfilesStore()
  profiles.profiles = [PROFILE]
  profiles.select(7)
  await profiles.runCheck()
  const store = useLoadConfigStore()
  store.scenarios = []
  store.addScript({ id: 1, name: 'cleanup.sql', body: 'DELETE FROM pgbench_history;', updated_at: '' })
  await store.validateAll()
})
afterEach(() => vi.unstubAllGlobals())

async function mountSummary() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:p(.*)*', component: { template: '<div />' } }],
  })
  await router.push('/load')
  const wrapper = mount(PreRunSummary, { global: { plugins: [router] }, attachTo: document.body })
  const launch = () => wrapper.findAll('button').find((b) => b.text().includes('Запустить'))!
  return { wrapper, router, launch }
}

describe('PreRunSummary', () => {
  it('shows the database, load and scenarios and requires each danger to be confirmed', async () => {
    const { wrapper, router, launch } = await mountSummary()
    const text = wrapper.text()
    expect(text).toContain('stage-db · bench')
    expect(text).toContain('PostgreSQL 16.4')
    expect(text).toContain('-T 300 с')
    expect(text).toContain('cleanup.sql @1 · 100%')
    expect(text).toContain('DELETE без WHERE удалит все строки')
    expect(launch().attributes('disabled')).toBeDefined()

    await wrapper.get('input[type="checkbox"]').setValue(true)
    expect(launch().attributes('disabled')).toBeUndefined()
    await launch().trigger('click')
    await flushPromises()
    expect(startBodies[0]).toMatchObject({
      profile_id: 7,
      confirmed_rules: ['sql.delete_without_where@cleanup.sql:1'],
    })
    expect(router.currentRoute.value.fullPath).toBe('/runs/12')
    wrapper.unmount()
  })

  it('adds items the server found and asks to confirm them too', async () => {
    startResponses.push(
      jsonResponse(422, {
        detail: {
          code: 'confirmation_required',
          message: 'Нужно подтвердить',
          missing: ['limits.clients_near_free'],
          findings: [
            { rule_id: 'limits.clients_near_free', level: 'warning', message: 'Клиентов больше 80 %', field: 'clients', scenario: null, line: null },
          ],
        },
      }),
    )
    const { wrapper, launch } = await mountSummary()
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await launch().trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Клиентов больше 80 %')
    expect(wrapper.text()).toContain('Сервер нашёл ещё пункты')
    expect(launch().attributes('disabled')).toBeDefined()

    const boxes = wrapper.findAll('input[type="checkbox"]')
    await boxes[1]!.setValue(true)
    await launch().trigger('click')
    await flushPromises()
    expect(startBodies[1]!.confirmed_rules).toEqual([
      'sql.delete_without_where@cleanup.sql:1',
      'limits.clients_near_free',
    ])
    wrapper.unmount()
  })

  it('shows a busy agent', async () => {
    startResponses.push(jsonResponse(409, { detail: { code: 'agent_busy', message: 'На агенте уже выполняется запуск.' } }))
    const { wrapper, launch } = await mountSummary()
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await launch().trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('уже выполняется')
    wrapper.unmount()
  })
})
