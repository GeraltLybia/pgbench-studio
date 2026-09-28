/**
 * Load parameters: zod schema and the limit rules from docs/architecture.md, «Параметры нагрузки».
 * Mirrors backend app/core/limits.py (same codes, levels and thresholds); the backend enforces
 * them again on POST /api/runs.
 */
import { z } from 'zod'

export const MIN_DURATION_S = 10
export const LONG_DURATION_S = 3600
export const NEAR_FREE_SHARE = 0.8
export const MIN_SERVER_MAJOR = 13

export type LimitLevel = 'error' | 'warning'

export interface LimitFinding {
  code: string
  level: LimitLevel
  field: string
  message: string
  ruleId: string
}

export interface Limits {
  connections_reserve: number
  max_duration_s: number
  max_transactions: number
}

export interface LoadShape {
  mode: 'duration' | 'transactions'
  clients: number
  threads: number
  duration_s: number | null
  transactions: number | null
  rate_tps: number | null
  latency_limit_ms: number | null
}

export interface LimitContext {
  limits: Limits
  freeConnections: number | null
  cpuCount: number
  serverMajor: number | null
  pgbenchMajor: number | null
}

export function checkLimits(shape: LoadShape, ctx: LimitContext): LimitFinding[] {
  const found: LimitFinding[] = []
  const add = (code: string, level: LimitLevel, field: string, message: string) =>
    found.push({ code, level, field, message, ruleId: `limits.${code}` })
  const { limits } = ctx

  if (ctx.freeConnections !== null) {
    const available = ctx.freeConnections - limits.connections_reserve
    if (shape.clients > available) {
      add(
        'clients_over_free',
        'error',
        'clients',
        `Клиентов больше, чем свободных соединений с учётом резерва: максимум ${Math.max(available, 0)} (свободно ${ctx.freeConnections}, резерв ${limits.connections_reserve})`,
      )
    } else if (shape.clients > NEAR_FREE_SHARE * available) {
      add(
        'clients_near_free',
        'warning',
        'clients',
        `Клиентов больше 80 % свободных соединений (${shape.clients} из ${available})`,
      )
    }
  }

  if (shape.threads > shape.clients) {
    add('threads_over_clients', 'error', 'threads', 'Потоков -j больше, чем клиентов -c')
  }
  if (shape.threads > ctx.cpuCount) {
    add('threads_over_cores', 'error', 'threads', `Потоков -j больше, чем ядер на агенте (${ctx.cpuCount})`)
  }

  if (shape.mode === 'duration') {
    const duration = shape.duration_s ?? 0
    if (duration < MIN_DURATION_S) {
      add('duration_too_short', 'error', 'duration_s', 'Длительность -T не меньше 10 с')
    } else if (duration > limits.max_duration_s) {
      add(
        'duration_over_max',
        'error',
        'duration_s',
        `Длительность -T больше допустимой: максимум ${limits.max_duration_s} с`,
      )
    } else if (duration > LONG_DURATION_S) {
      add('duration_long', 'warning', 'duration_s', 'Тест дольше часа')
    }
  } else {
    const tx = shape.transactions ?? 0
    if (tx < 1) {
      add('transactions_missing', 'error', 'transactions', 'Укажите число транзакций -t')
    } else if (shape.clients * tx > limits.max_transactions) {
      add(
        'transactions_over_max',
        'error',
        'transactions',
        `Всего транзакций c × t = ${shape.clients * tx} больше допустимого ${limits.max_transactions}`,
      )
    }
  }

  if (shape.rate_tps !== null && shape.rate_tps <= 0) {
    add('rate_not_positive', 'error', 'rate_tps', 'Ограничение TPS -R должно быть больше нуля')
  }
  if (shape.latency_limit_ms !== null && shape.latency_limit_ms <= 0) {
    add('latency_limit_not_positive', 'error', 'latency_limit_ms', 'Latency limit должен быть больше нуля')
  }

  const major = ctx.serverMajor
  if (major !== null && (major < MIN_SERVER_MAJOR || (ctx.pgbenchMajor && major > ctx.pgbenchMajor))) {
    add(
      'server_version',
      'warning',
      'profile_id',
      `PostgreSQL ${major} вне поддерживаемого диапазона ${MIN_SERVER_MAJOR}–${ctx.pgbenchMajor ?? 18}`,
    )
  }
  return found
}

const optionalPositive = (message: string) =>
  z
    .string()
    .trim()
    .transform((v) => (v === '' ? null : Number(v.replace(',', '.'))))
    .refine((v) => v === null || (Number.isFinite(v) && v > 0), message)

const positiveInt = (message: string) =>
  z
    .string()
    .trim()
    .regex(/^\d+$/, message)
    .transform(Number)
    .refine((v) => v >= 1, message)

/** Form fields are strings while typing; the schema turns them into RunConfig numbers. */
export const paramsSchema = z
  .object({
    mode: z.enum(['duration', 'transactions']),
    duration_s: z.string(),
    transactions: z.string(),
    clients: positiveInt('Целое число от 1'),
    threads: positiveInt('Целое число от 1'),
    protocol: z.enum(['simple', 'extended', 'prepared']),
    rate_tps: optionalPositive('Больше нуля или пусто'),
    latency_limit_ms: optionalPositive('Больше нуля или пусто'),
    vacuum: z.boolean(),
    detailed_log: z.boolean(),
    sampling_rate: z
      .string()
      .trim()
      .transform((v) => (v === '' ? null : Number(v.replace(',', '.'))))
      .refine((v) => v === null || (Number.isFinite(v) && v > 0 && v <= 1), 'От 0 до 1 или пусто'),
  })
  .superRefine((v, ctx) => {
    const key = v.mode === 'duration' ? 'duration_s' : 'transactions'
    if (!/^\d+$/.test(v[key].trim())) {
      ctx.addIssue({ code: 'custom', path: [key], message: 'Целое число' })
    }
  })
  .transform((v) => ({
    ...v,
    duration_s: v.mode === 'duration' ? Number(v.duration_s) : null,
    transactions: v.mode === 'transactions' ? Number(v.transactions) : null,
    sampling_rate: v.detailed_log ? v.sampling_rate : null,
  }))

export type LoadParamsForm = z.input<typeof paramsSchema>
export type LoadParamsValues = z.output<typeof paramsSchema>

export const VARIABLE_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,62}$/
export const SCRIPT_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/

export function defaultParams(): LoadParamsForm {
  return {
    mode: 'duration',
    duration_s: '300',
    transactions: '1000',
    clients: '8',
    threads: '2',
    protocol: 'prepared',
    rate_tps: '',
    latency_limit_ms: '',
    vacuum: true,
    detailed_log: false,
    sampling_rate: '',
  }
}
