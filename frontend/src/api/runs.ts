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

export const FINISHED_STATUSES: readonly RunStatus[] = ['completed', 'failed', 'cancelled']

export const runsApi = {
  get: (id: number) => http.get<Run>(`/api/runs/${id}`),
  report: (id: number) => http.get<Report>(`/api/runs/${id}/report`),
  fileUrl: (id: number, name: string) => `/api/runs/${id}/files/${encodeURIComponent(name)}`,
  active: () => http.get<ActiveRun>('/api/runs/active'),
  cancel: (id: number) => http.post<RunStarted>(`/api/runs/${id}/cancel`),
  preview: (config: RunConfig) => http.post<CommandPreview>('/api/runs/preview', config),
  dry: (body: DryRunRequest) => http.post<DryRunResult>('/api/runs/dry', body),
  start: (config: RunConfig) => http.post<RunStarted>('/api/runs', config),
}
