import type { ConnectionTestFail, ConnectionTestOk, Profile } from '@/api/profiles'
import type { Run } from '@/api/runs'

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
  }
}
