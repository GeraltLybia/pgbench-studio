import type { components } from '@/types/api'
import { http } from './http'

export type Run = components['schemas']['RunOut']
export type RunConfig = components['schemas']['RunConfig']
export type Finding = components['schemas']['Finding']
export type CommandPreview = components['schemas']['CommandPreview']
export type DryRunRequest = components['schemas']['DryRunRequest']
export type DryRunResult = components['schemas']['DryRunResult']
export type RunStarted = components['schemas']['RunStarted']
export type ActiveRun = components['schemas']['ActiveRunOut']
export type RunStatus = Run['status']
export type Report = components['schemas']['ReportOut']
export type RunSummary = components['schemas']['RunSummaryOut']
export type PgbenchSummary = components['schemas']['PgbenchSummaryOut']
export type SeriesPoint = components['schemas']['SeriesPointOut']
export type Statement = components['schemas']['StatementOut']
export type HistogramBucket = components['schemas']['HistogramBucketOut']
export type RunFile = components['schemas']['RunFileOut']
export type ResourcePoint = components['schemas']['ResourcePointOut']
export type RunListItem = components['schemas']['RunListItem']
export type RunPage = components['schemas']['RunPage']
export type Compare = components['schemas']['CompareOut']
export type MetricDiff = components['schemas']['MetricDiff']
export type ParamDiff = components['schemas']['ParamDiff']

export interface RunQuery {
  q?: string
  profile_id?: number | null
  status?: RunStatus[]
  days?: number | null
  limit?: number
  offset?: number
}

function query(params: RunQuery): string {
  const search = new URLSearchParams()
  if (params.q?.trim()) search.set('q', params.q.trim())
  if (params.profile_id != null) search.set('profile_id', String(params.profile_id))
  for (const s of params.status ?? []) search.append('status', s)
  if (params.days != null) search.set('days', String(params.days))
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset) search.set('offset', String(params.offset))
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const FINISHED_STATUSES: readonly RunStatus[] = ['completed', 'failed', 'cancelled']

export const runsApi = {
  get: (id: number) => http.get<Run>(`/api/runs/${id}`),
  report: (id: number) => http.get<Report>(`/api/runs/${id}/report`),
  list: (params: RunQuery = {}) => http.get<RunPage>(`/api/runs${query(params)}`),
  compare: (a: number, b: number) => http.get<Compare>(`/api/runs/compare?a=${a}&b=${b}`),
  remove: (id: number) => http.delete<void>(`/api/runs/${id}`),
  setNote: (id: number, note: string | null) => http.patch<Run>(`/api/runs/${id}`, { note }),
  fileUrl: (id: number, name: string) => `/api/runs/${id}/files/${encodeURIComponent(name)}`,
  active: () => http.get<ActiveRun>('/api/runs/active'),
  cancel: (id: number) => http.post<RunStarted>(`/api/runs/${id}/cancel`),
  preview: (config: RunConfig) => http.post<CommandPreview>('/api/runs/preview', config),
  dry: (body: DryRunRequest) => http.post<DryRunResult>('/api/runs/dry', body),
  start: (config: RunConfig) => http.post<RunStarted>('/api/runs', config),
}
