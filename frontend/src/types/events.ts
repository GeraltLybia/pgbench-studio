/**
 * WebSocket messages of /api/runs/{id}/ws (согласно документации, «WebSocket»).
 * Hand-written: WebSocket payloads are not part of the OpenAPI schema.
 */

export type RunStatus = 'queued' | 'running' | 'finalizing' | 'completed' | 'failed' | 'cancelled'

interface Base {
  seq: number
  ts: string | null
}

export interface LogEvent extends Base {
  type: 'log'
  stream: 'stdout' | 'stderr'
  line: string
}

export interface ProgressEvent extends Base {
  type: 'progress'
  t: number
  tps: number
  lat_ms: number
  stddev_ms: number | null
  lag_ms: number | null
  failed: number
  skipped: number
  retried: number
  pct: number | null
  eta_s: number | null
}

export interface ResourcesEvent extends Base {
  type: 'resources'
  source: string
  t: number
  cpu_pct: number
  ram_pct: number
  ram_used_bytes: number
  ram_total_bytes: number
}

export interface WarningEvent extends Base {
  type: 'warning'
  code: string
  message: string
}

export interface StatusEvent extends Partial<Base> {
  type: 'status'
  status: RunStatus
  exit_code: number | null
  error: string | null
  stopped_by: string | null
}

export interface ScenarioInfo {
  kind: 'builtin' | 'script'
  name: string
  weight: number
}

export interface RunInfo {
  run_id: number
  kind: 'init' | 'bench'
  argv: string[]
  started_by: string | null
  started_at?: string | null
  agent_name: string
  profile_name?: string | null
  dbname?: string | null
  server_version?: string | null
  pgbench_version?: string | null
  mode?: 'duration' | 'transactions'
  duration_s?: number | null
  transactions?: number | null
  clients?: number
  threads?: number
  protocol?: string
  rate_tps?: number | null
  estimated?: boolean | null
  scenarios?: ScenarioInfo[]
}

export interface SnapshotEvent extends Base {
  type: 'snapshot'
  run_id: number
  status: StatusEvent
  config: RunInfo
  log: LogEvent[]
  progress: ProgressEvent[]
  resources: ResourcesEvent[]
  warnings: WarningEvent[]
}

export interface PongEvent {
  type: 'pong'
  ts: string
}

export type RunMessage =
  | SnapshotEvent
  | LogEvent
  | ProgressEvent
  | ResourcesEvent
  | WarningEvent
  | StatusEvent
  | PongEvent

export const FINAL_STATUSES: readonly RunStatus[] = ['completed', 'failed', 'cancelled']
