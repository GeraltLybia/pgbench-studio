import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { dipLabel, findDips, loadArgs, rebin } from '@/components/report/analysis'
import ExportMenu from '@/components/report/ExportMenu.vue'
import StatementBars from '@/components/report/StatementBars.vue'
import RunParams from '@/components/report/RunParams.vue'
import ReportView from '@/views/ReportView.vue'
import { report } from './fixtures'
import { jsonResponse, mockFetch } from './helpers'

vi.mock('vue-echarts', () => ({ default: { name: 'VChart', props: ['option'], template: '<div class="vchart" />' } }))

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('findDips', () => {
  const flat = (values: number[]) => values.map((tps, t_s) => ({ t_s, tps }))

  it('finds seconds under half of the median and merges neighbours', () => {
    const points = flat([100, 4800, 4810, 4790, 1500, 1400, 4800, 4805, 4800, 300])
    expect(findDips(points)).toEqual([{ from: 4, to: 5, minTps: 1400 }])
    expect(dipLabel({ from: 4, to: 5, minTps: 1400 })).toBe('просадка 4–5 с')
    expect(dipLabel({ from: 7, to: 7, minTps: 1 })).toBe('просадка 7 с')
  })

  it('ignores ramp-up, the last partial second and short or idle runs', () => {
    expect(findDips(flat([10, 4800, 4800, 4800, 4800, 20]))).toEqual([])
    expect(findDips(flat([1, 2, 3]))).toEqual([])
    expect(findDips(flat([0, 0, 0, 0, 0, 0]))).toEqual([])
  })

  it('keeps the three deepest dips in time order', () => {
    const values = [4800, 4800, 1000, 4800, 900, 4800, 800, 4800, 2000, 4800, 4800]
    expect(findDips(flat(values)).map((d) => d.from)).toEqual([2, 4, 6])
  })
})

describe('rebin', () => {
  it('spreads log buckets over equal bins and keeps every transaction', () => {
    const buckets = report().histogram
    const bins = rebin(buckets, 10, 1)
    expect(bins).toHaveLength(10)
    expect(bins.reduce((s, b) => s + b.count, 0)).toBe(755)
    expect(bins[0]!.from).toBeCloseTo(2.0, 2)
    expect(bins.at(-1)!.to).toBeCloseTo(18.4, 5)
  })

  it('puts the slow tail beyond the clip into the last bin', () => {
    const bins = rebin([{ upper_ms: 1, count: 999 }, { upper_ms: 500, count: 1 }], 5, 0.99)
    expect(bins.at(-1)!.to).toBeCloseTo(1, 5)
    expect(bins.at(-1)!.count).toBe(1)
    expect(rebin([])).toEqual([])
  })
})

it('loadArgs keeps only what the user chose', () => {
  expect(loadArgs(report().run.argv)).toBe('-c 32 -j 8 -T 300 -M prepared')
  expect(loadArgs(['pgbench', '-t', '10', '--failures-detailed', '--aggregate-interval=1', '--sampling-rate=0.1'])).toBe(
    '-t 10 --sampling-rate=0.1',
  )
})

it('StatementBars shows SQL rows, scaled bars and failures', () => {
  const wrapper = mount(StatementBars, { props: { statements: report().statements } })
  const rows = wrapper.findAll('.row')
  expect(rows).toHaveLength(2) // \set is hidden
  expect(rows[0]!.text()).toContain('UPDATE pgbench_branches')
  expect(rows[0]!.text()).toContain('2,940 мс')
  expect(rows[0]!.get('.fill').attributes('style')).toContain('width: 100%')
  expect(rows[1]!.text()).toContain('12 ошибок')
  expect(mount(StatementBars, { props: { statements: [] } }).text()).toContain('не вывел таблицу -r')
})

it('RunParams lists the mockup rows', () => {
  const r = report()
  const text = mount(RunParams, { props: { run: r.run, summary: r.run.summary!.pgbench! } }).text()
  expect(text).toContain('-c 32 -j 8 -T 300 -M prepared')
  expect(text).toContain('tpcb-like@1, select_hot.sql@3')
  expect(text).toContain('PostgreSQL 16.4 · stage-db')
  const long = { ...r.run, server_version: '18.6 (Debian 18.6-1.pgdg13+2)' }
  expect(mount(RunParams, { props: { run: long, summary: null } }).text()).toContain('PostgreSQL 18.6 · stage-db')
  expect(text).toContain('38 мс')
})

it('ExportMenu links every run file', async () => {
  const wrapper = mount(ExportMenu, { props: { runId: 128, files: report().files } })
  expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  await wrapper.get('button').trigger('click')
  const links = wrapper.findAll('a')
  expect(links.map((a) => a.attributes('href'))).toEqual([
    '/api/runs/128/files/stdout.log',
    '/api/runs/128/files/stderr.log',
    '/api/runs/128/files/pgbench_log.12.gz',
    '/api/runs/128/files/select_hot.sql',
  ])
  expect(links[2]!.text()).toContain('3,3 МБ')
})

async function mountReport() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/runs/:id', component: { template: '<div />' } },
      { path: '/runs/:id/report', component: ReportView },
    ],
  })
  await router.push('/runs/128/report')
  const wrapper = mount(ReportView, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('ReportView', () => {
  it('shows the mockup numbers from the stored summary', async () => {
    mockFetch(jsonResponse(200, report()))
    const { wrapper } = await mountReport()
    const text = wrapper.text()
    expect(text).toContain('Отчёт · тест #128')
    expect(text).toContain('длительность 5 мин')
    expect(text).toMatch(/4\s806/)
    expect(text).toContain('6,64')
    expect(text).toContain('stddev 2,11 мс')
    expect(text).toContain('10,4 / 14,8')
    expect(text).toMatch(/1\s441\s790/)
    expect(text).toContain('за 300 с')
    expect(text).toContain('0,00 % · retried 0')
    expect(text).toContain('tps = 4806.137122 (without initial connection time)')
    expect(wrapper.find('[title="tps = 4806.137122"]').exists()).toBe(true)
    expect(wrapper.find('[title="latency average = 6.642 ms"]').exists()).toBe(true)
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })

  it('explains a stopped run without a pgbench summary', async () => {
    mockFetch(
      jsonResponse(
        200,
        report(
          { status: 'cancelled', stopped_by: 'ed' },
          { complete: false, series_source: 'progress', percentiles: null },
        ),
      ),
    )
    const { wrapper } = await mountReport()
    const notice = wrapper.get('[role="status"]').text()
    expect(notice).toContain('Тест остановлен пользователем ed')
    expect(notice).toContain('График построен по строкам progress')
    expect(wrapper.text()).toContain('в подробном режиме')
  })

  it('sends an active run back to its live screen', async () => {
    mockFetch(jsonResponse(409, { detail: { code: 'run_active', message: 'Запуск ещё выполняется' } }))
    const { router } = await mountReport()
    expect(router.currentRoute.value.path).toBe('/runs/128')
  })

  it('shows other errors', async () => {
    mockFetch(jsonResponse(404, { detail: { code: 'run_not_found', message: 'Запуск не найден' } }))
    const { wrapper } = await mountReport()
    expect(wrapper.get('[role="alert"]').text()).toBe('Запуск не найден')
  })
})

it('sub-millisecond latencies keep three decimals', async () => {
  const r = report({}, { percentiles: { p50: 0.052, p95: 0.246, p99: 0.311 } })
  r.run.summary!.pgbench!.latency_avg_ms = 0.075
  mockFetch(jsonResponse(200, r))
  const { wrapper } = await mountReport()
  expect(wrapper.text()).toContain('0,246 / 0,311')
  expect(wrapper.text()).toContain('0,075')
})
