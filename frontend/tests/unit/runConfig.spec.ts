import { describe, expect, it } from 'vitest'
import {
  checkLimits,
  defaultParams,
  paramsSchema,
  type LimitContext,
  type LoadShape,
} from '@/validation/runConfig'

// Same fixtures as backend/tests/unit/test_limits_command.py: the two must agree.
const CTX: LimitContext = {
  limits: { connections_reserve: 5, max_duration_s: 14400, max_transactions: 100_000_000 },
  freeConnections: 105,
  cpuCount: 8,
  serverMajor: 16,
  pgbenchMajor: 18,
}

function dur(over: Partial<LoadShape> = {}): LoadShape {
  return {
    mode: 'duration',
    clients: 8,
    threads: 4,
    duration_s: 300,
    transactions: null,
    rate_tps: null,
    latency_limit_ms: null,
    ...over,
  }
}

function codes(shape: LoadShape, ctx: Partial<LimitContext> = {}) {
  return Object.fromEntries(checkLimits(shape, { ...CTX, ...ctx }).map((f) => [f.code, f.level]))
}

describe('checkLimits mirrors the backend table', () => {
  it.each([
    [80, {}],
    [81, { clients_near_free: 'warning' }],
    [100, { clients_near_free: 'warning' }],
    [101, { clients_over_free: 'error' }],
  ])('clients %i', (clients, expected) => {
    expect(codes(dur({ clients, threads: 1 }))).toEqual(expected)
  })

  it('ignores connections without a check', () => {
    expect(codes(dur({ clients: 10_000, threads: 1 }), { freeConnections: null })).toEqual({})
  })

  it.each([
    [8, 8, 8, {}],
    [8, 9, 16, { threads_over_clients: 'error' }],
    [16, 9, 8, { threads_over_cores: 'error' }],
  ])('threads c=%i j=%i cpus=%i', (clients, threads, cpuCount, expected) => {
    expect(codes(dur({ clients, threads }), { cpuCount })).toEqual(expected)
  })

  it.each([
    [9, { duration_too_short: 'error' }],
    [10, {}],
    [3600, {}],
    [3601, { duration_long: 'warning' }],
    [14400, { duration_long: 'warning' }],
    [14401, { duration_over_max: 'error' }],
  ])('duration %i', (duration_s, expected) => {
    expect(codes(dur({ duration_s }))).toEqual(expected)
  })

  it.each([
    [10, 10_000_000, {}],
    [10, 10_000_001, { transactions_over_max: 'error' }],
    [1, 0, { transactions_missing: 'error' }],
  ])('transactions c=%i t=%i', (clients, transactions, expected) => {
    const shape = dur({ mode: 'transactions', clients, threads: 1, duration_s: null, transactions })
    expect(codes(shape)).toEqual(expected)
  })

  it('rate and latency limit must be positive', () => {
    expect(codes(dur({ rate_tps: 0, latency_limit_ms: -1 }))).toEqual({
      rate_not_positive: 'error',
      latency_limit_not_positive: 'error',
    })
  })

  it.each([
    [12, true],
    [13, false],
    [18, false],
    [19, true],
  ])('server version %i warns: %s', (serverMajor, warns) => {
    expect('server_version' in codes(dur(), { serverMajor })).toBe(warns)
  })

  it('builds confirmation ids like the backend', () => {
    expect(checkLimits(dur({ duration_s: 5000 }), CTX)[0]?.ruleId).toBe('limits.duration_long')
  })
})

describe('paramsSchema', () => {
  it('turns the form into RunConfig numbers', () => {
    const parsed = paramsSchema.parse({ ...defaultParams(), rate_tps: '1,5', latency_limit_ms: '' })
    expect(parsed).toMatchObject({
      mode: 'duration',
      duration_s: 300,
      transactions: null,
      clients: 8,
      threads: 2,
      rate_tps: 1.5,
      latency_limit_ms: null,
      sampling_rate: null,
    })
  })

  it('validates the field of the chosen mode only', () => {
    const tx = paramsSchema.safeParse({ ...defaultParams(), mode: 'transactions', duration_s: 'x', transactions: '500' })
    expect(tx.success && tx.data.transactions).toBe(500)
    const bad = paramsSchema.safeParse({ ...defaultParams(), duration_s: '10.5' })
    expect(bad.success).toBe(false)
  })

  it('rejects bad numbers and keeps sampling only with a detailed log', () => {
    expect(paramsSchema.safeParse({ ...defaultParams(), clients: '0' }).success).toBe(false)
    expect(paramsSchema.safeParse({ ...defaultParams(), rate_tps: '-1' }).success).toBe(false)
    expect(paramsSchema.safeParse({ ...defaultParams(), detailed_log: true, sampling_rate: '2' }).success).toBe(false)
    const off = paramsSchema.parse({ ...defaultParams(), detailed_log: false, sampling_rate: '0.5' })
    expect(off.sampling_rate).toBeNull()
  })
})
