import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { BACKOFF_MS, PING_MS, runSocketUrl, useRunSocket } from '@/composables/useRunSocket'
import { LOG_BUFFER, useRunStore } from '@/stores/run'
import type { RunMessage, SnapshotEvent } from '@/types/events'

class FakeSocket {
  static all: FakeSocket[] = []
  sent: string[] = []
  closedWith: number | null = null
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  constructor(public url: string) {
    FakeSocket.all.push(this)
  }
  send(data: string) {
    this.sent.push(data)
  }
  close(code: number) {
    this.closedWith = code
  }
  open() {
    this.onopen?.()
  }
  message(m: unknown) {
    this.onmessage?.({ data: JSON.stringify(m) })
  }
  drop(code = 1006) {
    this.onclose?.({ code })
  }
}

function snapshot(status: string, extra: Partial<SnapshotEvent> = {}): SnapshotEvent {
  return {
    type: 'snapshot',
    seq: 3,
    ts: null,
    run_id: 5,
    status: { type: 'status', status: status as never, exit_code: null, error: null, stopped_by: null },
    config: { run_id: 5, kind: 'bench', argv: [], started_by: 'ed', agent_name: 'agent', mode: 'duration', duration_s: 300 },
    log: [],
    progress: [],
    resources: [],
    warnings: [],
    ...extra,
  }
}

function connect(onMessage: (m: RunMessage) => void = () => {}) {
  const scope = effectScope()
  const socket = scope.run(() =>
    useRunSocket(5, { onMessage, createSocket: (url) => new FakeSocket(url) as unknown as WebSocket }),
  )!
  return { socket, scope, ws: () => FakeSocket.all.at(-1)! }
}

beforeEach(() => {
  FakeSocket.all = []
  vi.useFakeTimers()
  setActivePinia(createPinia())
})
afterEach(() => vi.useRealTimers())

describe('useRunSocket', () => {
  it('builds the ws/wss URL from the page location', () => {
    expect(runSocketUrl(5, { protocol: 'https:', host: 'studio.corp' } as Location)).toBe('wss://studio.corp/api/runs/5/ws')
    expect(runSocketUrl(5, { protocol: 'http:', host: 'localhost:8080' } as Location)).toBe('ws://localhost:8080/api/runs/5/ws')
  })

  it('passes messages and pings every 30 s', () => {
    const got: RunMessage[] = []
    const { socket, ws } = connect((m) => got.push(m))
    ws().open()
    expect(socket.state.value).toBe('open')
    ws().message(snapshot('running'))
    expect(got[0]!.type).toBe('snapshot')
    vi.advanceTimersByTime(PING_MS)
    expect(ws().sent).toEqual(['{"type":"ping"}'])
  })

  it('reconnects with exponential backoff and resets it on success', () => {
    const { socket, ws } = connect()
    ws().open()
    ws().drop()
    expect(socket.state.value).toBe('reconnecting')
    vi.advanceTimersByTime(BACKOFF_MS[0]! - 1)
    expect(FakeSocket.all).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(FakeSocket.all).toHaveLength(2)
    ws().drop()
    vi.advanceTimersByTime(BACKOFF_MS[1]!)
    expect(FakeSocket.all).toHaveLength(3)
    ws().open()
    expect(socket.attempts.value).toBe(0)
  })

  it('does not reconnect after the run finished or when refused', () => {
    const { socket, ws } = connect()
    ws().open()
    ws().message({ type: 'status', status: 'completed', exit_code: 0, error: null, stopped_by: null })
    ws().drop(1000)
    vi.advanceTimersByTime(60_000)
    expect(FakeSocket.all).toHaveLength(1)
    expect(socket.state.value).toBe('closed')

    const other = connect()
    other.ws().drop(4401)
    vi.advanceTimersByTime(60_000)
    expect(FakeSocket.all).toHaveLength(2)
  })

  it('treats a snapshot of a finished run as final', () => {
    const { ws } = connect()
    ws().message(snapshot('cancelled'))
    ws().drop(1000)
    vi.advanceTimersByTime(60_000)
    expect(FakeSocket.all).toHaveLength(1)
  })

  it('closes when its scope ends', () => {
    const { scope, ws } = connect()
    scope.stop()
    expect(ws().closedWith).toBe(1000)
  })
})

describe('run store', () => {
  it('replaces the state with each snapshot and appends live messages', () => {
    const run = useRunStore(5)
    run.apply({ type: 'log', seq: 1, ts: null, stream: 'stdout', line: 'stale' })
    run.apply(
      snapshot('running', {
        log: [{ type: 'log', seq: 2, ts: null, stream: 'stderr', line: 'progress: 1.0 s' }],
        progress: [{ type: 'progress', seq: 3, ts: null, t: 1, tps: 10, lat_ms: 1, stddev_ms: 0.1, lag_ms: null, failed: 0, skipped: 0, retried: 0, pct: 1, eta_s: 299 }],
      }),
      1000,
    )
    expect(run.log.map((l) => l.line)).toEqual(['progress: 1.0 s'])
    expect(run.lastProgressAt).toBe(1000)
    run.apply({ type: 'progress', seq: 4, ts: null, t: 2, tps: 20, lat_ms: 1, stddev_ms: 0.1, lag_ms: null, failed: 0, skipped: 0, retried: 0, pct: 2, eta_s: 298 }, 2000)
    run.apply({ type: 'resources', seq: 5, ts: null, source: 'a', t: 2, cpu_pct: 5, ram_pct: 10, ram_used_bytes: 1, ram_total_bytes: 2 })
    run.apply({ type: 'warning', seq: 6, ts: null, code: 'agent_cpu_high', message: 'x' })
    run.apply({ type: 'status', status: 'completed', exit_code: 0, error: null, stopped_by: null })
    run.apply({ type: 'pong', ts: '' })
    expect(run.last?.tps).toBe(20)
    expect(run.lastProgressAt).toBe(2000)
    expect(run.lastResources?.cpu_pct).toBe(5)
    expect(run.warnings).toHaveLength(1)
    expect(run.finished).toBe(true)
  })

  it('keeps at most 5000 log lines', () => {
    const run = useRunStore(7)
    for (let i = 0; i < LOG_BUFFER + 10; i++) {
      run.apply({ type: 'log', seq: i, ts: null, stream: 'stdout', line: String(i) })
    }
    expect(run.log).toHaveLength(LOG_BUFFER)
    expect(run.log[0]!.line).toBe('10')
  })
})
