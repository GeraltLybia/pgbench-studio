import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Compare, RunListItem } from '@/api/runs'
import { diffText, diffTone, metricValue } from '@/components/history/compare'
import Sparkline from '@/components/history/Sparkline.vue'
import { useAuthStore } from '@/stores/auth'
import { useLoadConfigStore } from '@/stores/loadConfig'
import { useProfilesStore } from '@/stores/profiles'
import CompareView from '@/views/CompareView.vue'
import HistoryView from '@/views/HistoryView.vue'
import ReportView from '@/views/ReportView.vue'
import { PROFILE, report } from './fixtures'
import { jsonResponse } from './helpers'

vi.mock('vue-echarts', () => ({ default: { name: 'VChart', props: ['option'], template: '<div class="vchart" />' } }))

function item(id: number, overrides: Partial<RunListItem> = {}): RunListItem {
  return {
    id,
    status: 'completed',
    created_at: '2026-09-27T11:27:10Z',
    started_at: '2026-09-27T11:27:10Z',
    finished_at: '2026-09-27T11:32:10Z',
    started_by: 'ed',
    stopped_by: null,
    profile_id: 7,
    profile_name: 'stage-db',
    scenarios: ['tpcb-like@1', 'select_hot.sql@3'],
    mode: 'duration',
    duration_s: 300,
    transactions: null,
    clients: 32,
    threads: 8,
    tps: 4806.137122,
    latency_avg_ms: 6.642,
    failed: 0,
    error: null,
    note: null,
    sparkline: [4800, 4810, 4790],
    ...overrides,
  }
}

function compare(): Compare {
  const a = report({ id: 128, note: 'добавлен индекс' })
  const b = report({ id: 127 })
  return {
    a,
    b,
    metrics: [
      { key: 'tps', label: 'TPS', a: 4806.137122, b: 3912.2, diff_pct: 22.9, better: 'higher' },
      { key: 'latency_avg_ms', label: 'Latency avg', a: 6.642, b: 8.17, diff_pct: -18.7, better: 'lower' },
      { key: 'failed', label: 'Ошибок', a: 0, b: 0, diff_pct: null, better: 'lower' },
    ],
    params: [],
  }
}

let calls: string[]

function mockApi(routes: Record<string, () => Response>) {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = input instanceof Request ? input.url : String(input)
      calls.push(`${init?.method ?? 'GET'} ${path}`)
      const key = Object.keys(routes).find((k) => `${init?.method ?? 'GET'} ${path}`.startsWith(k))
      return Promise.resolve(key ? routes[key]!() : jsonResponse(404, { detail: { code: 'x', message: 'нет' } }))
    }),
  )
}

async function mountAt(path: string, component: unknown) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/history', component: HistoryView },
      { path: '/compare', component: CompareView },
      { path: '/runs/:id/report', component: ReportView },
      { path: '/load', component: { template: '<div />' } },
      { path: '/runs/:id', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  const wrapper = mount(component as never, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  useAuthStore().user = { id: 1, username: 'ed', role: 'editor', must_change_password: false }
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('compare helpers', () => {
  it('formats values and signed differences', () => {
    expect(metricValue({ key: 'tps' }, 4806.4)).toMatch(/4\s806/)
    expect(metricValue({ key: 'latency_avg_ms' }, 0.075)).toBe('0,075 мс')
    expect(metricValue({ key: 'failed' }, 12000)).toMatch(/12\s000/)
    expect(metricValue({ key: 'tps' }, null)).toBe('—')
    expect(diffText(22.9)).toBe('+22,9%')
    expect(diffText(-18.7)).toBe('−18,7%')
    expect(diffText(0)).toBe('±0,0%')
    expect(diffText(null)).toBe('')
  })

  it('colours by what is better', () => {
    expect(diffTone({ better: 'higher', diff_pct: 5 })).toBe('good')
    expect(diffTone({ better: 'lower', diff_pct: 5 })).toBe('bad')
    expect(diffTone({ better: 'lower', diff_pct: -5 })).toBe('good')
    expect(diffTone({ better: 'lower', diff_pct: null })).toBe('same')
  })
})

it('Sparkline draws a polyline or a dash', () => {
  expect(mount(Sparkline, { props: { values: [1, 3, 2] } }).find('polyline').attributes('points')).toBe(
    '0.0,20.0 40.0,2.0 80.0,11.0',
  )
  expect(mount(Sparkline, { props: { values: [5] } }).text()).toBe('—')
})

describe('HistoryView', () => {
  it('lists runs, filters and pages', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const page1 = { items: Array.from({ length: 20 }, (_, i) => item(200 - i)), total: 21 }
    mockApi({
      'GET /api/profiles': () => jsonResponse(200, [PROFILE]),
      'GET /api/runs?days=30&limit=20&offset=20': () => jsonResponse(200, { items: [item(180)], total: 21 }),
      'GET /api/runs?': () => jsonResponse(200, page1),
    })
    const { wrapper } = await mountAt('/history', HistoryView)
    expect(calls).toContain('GET /api/runs?days=30&limit=20')
    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(20)
    expect(rows[0]!.text()).toContain('#200')
    expect(rows[0]!.text()).toContain('tpcb-like, select_hot')
    expect(rows[0]!.text()).toContain('32 / 8')
    expect(rows[0]!.text()).toContain('300 с')
    expect(rows[0]!.text()).toContain('6,64')
    expect(rows[0]!.text()).toContain('завершён')

    await wrapper.get('.more button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(21)
    expect(wrapper.find('.more').exists()).toBe(false)

    await wrapper.get('input[type="search"]').setValue('#128')
    await vi.advanceTimersByTimeAsync(350)
    await flushPromises()
    expect(calls.at(-1)).toBe('GET /api/runs?q=%23128&days=30&limit=20')

    const [profile, period] = wrapper.findAll('select')
    await profile!.setValue(String(PROFILE.id))
    await period!.setValue('')
    await flushPromises()
    expect(calls).toContain(`GET /api/runs?q=%23128&profile_id=${PROFILE.id}&days=30&limit=20`)
  })

  it('compares two ticked runs, older on the right', async () => {
    mockApi({
      'GET /api/profiles': () => jsonResponse(200, []),
      'GET /api/runs/compare': () => jsonResponse(200, compare()),
      'GET /api/runs?': () => jsonResponse(200, { items: [item(128), item(127), item(126)], total: 3 }),
    })
    const { wrapper } = await mountAt('/history?with=127', HistoryView)
    const boxes = wrapper.findAll('input[type="checkbox"]')
    expect((boxes[1]!.element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.text()).toContain('Отметьте ещё один запуск')

    await boxes[0]!.setValue(true)
    await flushPromises()
    expect(calls).toContain('GET /api/runs/compare?a=128&b=127')
    const panel = wrapper.get('.compare').text()
    expect(panel).toContain('Сравнение: #128 против #127')
    expect(panel).toContain('+22,9%')
    expect(panel).toContain('параметры запуска совпадают · #128: добавлен индекс')

    await boxes[2]!.setValue(true) // a third tick drops the earliest one
    await flushPromises()
    expect(calls.at(-1)).toBe('GET /api/runs/compare?a=128&b=126')
  })

  it('hides «Новый тест» from viewers', async () => {
    useAuthStore().user = { id: 1, username: 'v', role: 'viewer', must_change_password: false }
    mockApi({ 'GET /api/profiles': () => jsonResponse(200, []), 'GET /api/runs?': () => jsonResponse(200, { items: [], total: 0 }) })
    const { wrapper } = await mountAt('/history', HistoryView)
    expect(wrapper.text()).not.toContain('Новый тест')
    expect(wrapper.text()).toContain('Ничего не найдено')
  })
})

describe('CompareView', () => {
  it('shows metrics, differences and overlays', async () => {
    const data = compare()
    data.params = [
      { key: 'clients', label: 'Клиенты -c', a: '32', b: '16' },
      { key: 'body:select_hot.sql', label: 'Текст сценария select_hot.sql', a: 'отличается', b: 'отличается' },
    ]
    mockApi({ 'GET /api/runs/compare?a=128&b=127': () => jsonResponse(200, data) })
    const { wrapper } = await mountAt('/compare?a=128&b=127', CompareView)
    const text = wrapper.text()
    expect(text).toContain('Сравнение: #128 против #127')
    expect(text).toContain('−18,7%')
    expect(text).toContain('Клиенты -c3216')
    expect(text).toContain('тексты сценария отличаются')
    expect(text).toContain('добавлен индекс')
    expect(wrapper.findAll('.vchart')).toHaveLength(2)
    expect(wrapper.get('.diff.good').text()).toBe('+22,9%')
  })

  it('needs two different runs', async () => {
    mockApi({})
    const { wrapper } = await mountAt('/compare?a=5&b=5', CompareView)
    expect(wrapper.get('[role="alert"]').text()).toContain('два разных запуска')
    expect(calls).toEqual([])
  })
})

describe('report actions', () => {
  it('«Повторить» loads the stored parameters and scripts on the load screen', async () => {
    const r = report()
    r.run.profile_id = PROFILE.id
    r.run.config.run_config = {
      mode: 'transactions',
      transactions: 500,
      clients: 16,
      threads: 4,
      protocol: 'extended',
      rate_tps: 100,
      latency_limit_ms: null,
      vacuum: false,
      detailed_log: true,
      sampling_rate: 0.5,
      variables: [{ name: 'delta', value: '5' }],
      scenarios: [
        { kind: 'builtin', name: 'tpcb-like', weight: 1 },
        { kind: 'script', name: 'select_hot.sql', body: 'SELECT 1;\n', weight: 3, script_id: 9 },
      ],
    }
    mockApi({
      'GET /api/runs/128/report': () => jsonResponse(200, r),
      'GET /api/profiles': () => jsonResponse(200, [PROFILE]),
      'GET /api/system/info': () => jsonResponse(500),
    })
    const { wrapper, router } = await mountAt('/runs/128/report', ReportView)
    const button = wrapper.findAll('button').find((b) => b.text().includes('Повторить'))!
    await button.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/load')
    const store = useLoadConfigStore()
    expect(store.params).toMatchObject({ mode: 'transactions', transactions: '500', clients: '16', threads: '4', protocol: 'extended', rate_tps: '100', latency_limit_ms: '', vacuum: false, detailed_log: true, sampling_rate: '0.5' })
    expect(store.variables).toEqual([{ name: 'delta', value: '5' }])
    expect(store.scenarios.map((s) => [s.kind, s.name, s.weight])).toEqual([
      ['builtin', 'tpcb-like', 1],
      ['script', 'select_hot.sql', 3],
    ])
    const script = store.scenarios[1]!
    expect(script.kind === 'script' && script.body).toBe('SELECT 1;\n')
    expect(store.isModified(script)).toBe(false)
    expect(useProfilesStore().activeId).toBe(PROFILE.id)
  })

  it('deletes a run after confirmation and saves a note', async () => {
    vi.stubGlobal('confirm', () => true)
    mockApi({
      'GET /api/runs/128/report': () => jsonResponse(200, report()),
      'GET /api/system/info': () => jsonResponse(500),
      'PATCH /api/runs/128': () => jsonResponse(200, { ...report().run, note: 'индекс' }),
      'DELETE /api/runs/128': () => new Response(null, { status: 204 }),
      'GET /api/runs?': () => jsonResponse(200, { items: [], total: 0 }),
      'GET /api/profiles': () => jsonResponse(200, []),
    })
    vi.stubGlobal('confirm', () => true)
    const { wrapper, router } = await mountAt('/runs/128/report', ReportView)
    expect(wrapper.text()).toContain('Ресурсы агента нагрузки')
    expect(wrapper.text()).toContain('CPU в среднем 32 %')

    await wrapper.get('.link').trigger('click')
    await wrapper.get('.note-input').setValue('  индекс ')
    await wrapper.findAll('button').find((b) => b.text() === 'Сохранить')!.trigger('click')
    await flushPromises()
    expect(calls).toContain('PATCH /api/runs/128')
    expect(wrapper.text()).toContain('Заметка: индекс')

    await wrapper.get('[aria-label="Удалить запуск"]').trigger('click')
    await flushPromises()
    expect(calls).toContain('DELETE /api/runs/128')
    expect(router.currentRoute.value.path).toBe('/history')
  })

  it('viewers get neither «Повторить», delete nor note editing', async () => {
    useAuthStore().user = { id: 1, username: 'v', role: 'viewer', must_change_password: false }
    mockApi({ 'GET /api/runs/128/report': () => jsonResponse(200, report()), 'GET /api/system/info': () => jsonResponse(500) })
    const { wrapper } = await mountAt('/runs/128/report', ReportView)
    const text = wrapper.text()
    expect(text).toContain('Сравнить с…')
    expect(text).not.toContain('Повторить')
    expect(text).not.toContain('Заметка')
    expect(wrapper.find('[aria-label="Удалить запуск"]').exists()).toBe(false)
  })
})
