import type { ConnectionTestFail, ConnectionTestOk, Profile } from '@/api/profiles'
import type { Report, Run, RunSummary } from '@/api/runs'

export const PROFILE: Profile = {
  id: 7,
  name: 'stage-db · bench',
  host: 'stage-db.internal',
  port: 5432,
  dbname: 'bench',
  user: 'bench_runner',
  sslmode: 'require',
  app_name: 'pgbench-studio',
  connect_timeout_s: 10,
  has_password: true,
  created_at: '2026-09-27T10:00:00Z',
  updated_at: '2026-09-27T10:00:00Z',
}

export const CHECK_OK: ConnectionTestOk = {
  ok: true,
  checked_at: new Date().toISOString(),
  server_version: '16.4 (Debian 16.4-1.pgdg120+1)',
  server_version_num: 160004,
  server_major: 16,
  pgbench_version: '18.6',
  warnings: [],
  response_ms: 1.8,
  max_connections: 200,
  reserved_connections: 3,
  used_connections: 13,
  free_connections: 184,
  pgbench_tables: true,
  scale: 100,
  accounts_rows: 10_000_000,
}

export const CHECK_FAIL: ConnectionTestFail = {
  ok: false,
  checked_at: new Date().toISOString(),
  code: 'auth_failed',
  message: 'Неверный пользователь или пароль',
  hint: 'Проверьте логин и пароль, а также правила pg_hba.conf для адреса агента нагрузки.',
  raw: 'FATAL:  password authentication failed for user "bench_runner"',
}

export function run(status: Run['status'], pct: number | null = null): Run {
  return {
    id: 3,
    kind: 'init',
    status,
    profile_id: 7,
    started_by: 'ed',
    stopped_by: null,
    created_at: '2026-09-27T10:00:00Z',
    started_at: '2026-09-27T10:00:00Z',
    finished_at: null,
    pgbench_version: '18.6',
    server_version: '16.4',
    error: status === 'failed' ? 'pgbench: error: boom' : null,
    argv: ['pgbench', '-i', '-s', '1'],
    config: {},
    progress:
      pct === null
        ? null
        : { done: pct, total: 100, pct, elapsed_s: 1, remaining_s: 2, phase: 'Генерация данных' },
    log_tail: [{ stream: 'stderr', line: 'creating tables...' }],
    summary: null,
    note: null,
  }
}

const MIXED_STDOUT = `pgbench (18.6 (Debian 18.6-1.pgdg13+2), server 13.23 (Debian 13.23-1.pgdg13+1))
transaction type: multiple scripts
tps = 4806.137122 (without initial connection time)
`

/** A finished -T 300 report shaped like the mockup (two scripts, detailed log). */
export function report(overrides: Partial<Report['run']> = {}, summary: Partial<RunSummary> = {}): Report {
  const series = Array.from({ length: 300 }, (_, t) => {
    const tps = t === 0 ? 1200 : t === 97 || t === 98 ? 1500 : 4800 + (t % 7)
    return {
      t_s: t,
      tx: tps,
      tps,
      lat_avg_ms: 6.6,
      lat_min_ms: 2.1,
      lat_max_ms: 18.4,
      lat_std_ms: 2.1,
      lag_ms: null,
      failed: 0,
      retried: 0,
    }
  })
  return {
    run: {
      ...run('completed'),
      id: 128,
      kind: 'bench',
      started_at: '2026-09-27T11:27:10Z',
      finished_at: '2026-09-27T11:32:10Z',
      argv: ['pgbench', '-c', '32', '-j', '8', '-T', '300', '-M', 'prepared', '-P', '1', '-r', '-l',
        '--log-prefix=pgbench_log', '-b', 'tpcb-like@1', '-f', 'select_hot.sql@3'],
      config: {
        profile_name: 'stage-db',
        run_config: { scenarios: [{ kind: 'builtin', name: 'tpcb-like', weight: 1 }, { kind: 'script', name: 'select_hot.sql', weight: 3 }] },
      },
      log_tail: [],
      summary: {
        exit_code: 0,
        complete: true,
        series_source: 'transactions',
        sampling_rate: null,
        parse_error: null,
        percentiles: { p50: 6.2, p95: 10.4, p99: 14.8 },
        pgbench: {
          tps: 4806.137122,
          processed: 1441790,
          failed: 0,
          failed_pct: 0,
          retried: null,
          latency_avg_ms: 6.642,
          latency_stddev_ms: 2.108,
          scale: 100,
          duration_s: 300,
          initial_connection_ms: 38.214,
          aborted: false,
          scripts: [],
        },
        ...summary,
      },
      ...overrides,
    },
    series,
    statements: [
      { script: 'tpcb-like', idx: 0, sql: '\\set aid random(1, 100000 * :scale)', latency_ms: 0.002, failures: 0 },
      { script: 'tpcb-like', idx: 1, sql: 'UPDATE pgbench_branches SET bbalance = bbalance + :delta WHERE bid = :bid;', latency_ms: 2.94, failures: 0 },
      { script: 'select_hot.sql', idx: 1, sql: 'SELECT abalance FROM pgbench_accounts WHERE aid = :aid;', latency_ms: 0.37, failures: 12 },
    ],
    histogram: [
      { upper_ms: 2.02, count: 10 },
      { upper_ms: 6.2, count: 500 },
      { upper_ms: 10.4, count: 200 },
      { upper_ms: 14.8, count: 40 },
      { upper_ms: 18.4, count: 5 },
    ],
    resources: Array.from({ length: 300 }, (_, t) => ({
      t_s: t,
      cpu_pct: 30 + (t % 5),
      ram_pct: 12,
      ram_used_bytes: 1_000_000_000,
    })),
    raw_output: MIXED_STDOUT,
    raw_output_truncated: false,
    files: [
      { name: 'stdout.log', size_bytes: 900 },
      { name: 'stderr.log', size_bytes: 20_000 },
      { name: 'pgbench_log.12.gz', size_bytes: 3_500_000 },
      { name: 'select_hot.sql', size_bytes: 90 },
    ],
  }
}
