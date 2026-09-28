import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { lttb, downsample, LTTB_THRESHOLD, type Point } from '@/charts/lttb'
import RunProgress from '@/components/run/RunProgress.vue'
import { filterLog } from '@/components/run/logFilter'
import type { LogEvent, ProgressEvent, RunInfo } from '@/types/events'

const INFO: RunInfo = {
  run_id: 5,
  kind: 'bench',
  argv: [],
  started_by: 'ed',
  started_at: '2026-09-28T11:27:10Z',
  agent_name: 'load-agent-01',
  mode: 'duration',
  duration_s: 300,
  clients: 32,
  threads: 8,
  protocol: 'prepared',
  scenarios: [
    { kind: 'builtin', name: 'tpcb-like', weight: 1 },
    { kind: 'script', name: 'select_hot.sql', weight: 3 },
  ],
}

function point(t: number, eta: number | null, pct: number | null): ProgressEvent {
  return { type: 'progress', seq: t, ts: null, t, tps: 4812, lat_ms: 6.65, stddev_ms: 2.1, lag_ms: null, failed: 0, skipped: 0, retried: 0, pct, eta_s: eta }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-28T11:30:16Z'))
})
afterEach(() => vi.useRealTimers())

describe('RunProgress', () => {
  it('shows the mockup numbers for -T and counts down between points', async () => {
    const now = Date.now()
    const wrapper = mount(RunProgress, {
      props: { info: INFO, last: point(186, 114, 62), lastAt: now, finished: false },
    })
    const text = wrapper.text()
    expect(text).toContain('62%')
    expect(text).toContain('186 с из 300 с')
    expect(text).toContain('Осталось 1 мин 54 с')
    expect(text).toContain('-c 32 · -j 8')
    expect(text).toContain('-T 300')
    expect(text).toContain('tpcb-like@1 + select_hot.sql@3')
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('62')

    await vi.advanceTimersByTimeAsync(4000)
    expect(wrapper.text()).toContain('Осталось 1 мин 50 с')
  })

  it('marks -t progress as an estimate and shows 100 % when finished', async () => {
    const info: RunInfo = { ...INFO, mode: 'transactions', duration_s: null, transactions: 1000 }
    const wrapper = mount(RunProgress, { props: { info, last: point(10, 20, 33.3), lastAt: Date.now(), finished: false } })
    expect(wrapper.text()).toContain('оценка')
    expect(wrapper.text()).toContain('1000 транзакций на клиента')
    await wrapper.setProps({ finished: true })
    expect(wrapper.text()).toContain('100%')
    expect(wrapper.text()).not.toContain('Осталось')
  })
})

describe('log filter', () => {
  const lines: LogEvent[] = [
    { type: 'log', seq: 1, ts: null, stream: 'stdout', line: 'pgbench (18.6)' },
    { type: 'log', seq: 2, ts: null, stream: 'stderr', line: 'progress: 1.0 s, 5 tps' },
    { type: 'log', seq: 3, ts: null, stream: 'stderr', line: 'pgbench: error: client 0 aborted' },
  ]
  it('filters progress and errors', () => {
    expect(filterLog(lines, 'all')).toHaveLength(3)
    expect(filterLog(lines, 'progress').map((l) => l.seq)).toEqual([2])
    expect(filterLog(lines, 'errors').map((l) => l.seq)).toEqual([3])
  })
})

describe('LTTB', () => {
  it('keeps short series and thins long ones keeping the ends and the peaks', () => {
    const short: Point[] = [[0, 1], [1, 2]]
    expect(downsample(short)).toBe(short)
    const long: Point[] = Array.from({ length: 10_000 }, (_, i) => [i, i === 5000 ? 999 : Math.sin(i / 50)])
    const thin = downsample(long)
    expect(thin).toHaveLength(LTTB_THRESHOLD)
    expect(thin[0]).toEqual([0, 0])
    expect(thin.at(-1)![0]).toBe(9999)
    expect(thin.some(([, y]) => y === 999)).toBe(true)
    expect(lttb(long, 2)).toBe(long)
  })
})
