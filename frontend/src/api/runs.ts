import type { components } from '@/types/api'
import { http } from './http'

export type Run = components['schemas']['RunOut']
export type RunConfig = components['schemas']['RunConfig']
export type Finding = components['schemas']['Finding']
export type CommandPreview = components['schemas']['CommandPreview']
export type DryRunRequest = components['schemas']['DryRunRequest']
export type DryRunResult = components['schemas']['DryRunResult']
export type RunStarted = components['schemas']['RunStarted']
export type RunStatus = Run['status']

export const FINISHED_STATUSES: readonly RunStatus[] = ['completed', 'failed', 'cancelled']

export const runsApi = {
  get: (id: number) => http.get<Run>(`/api/runs/${id}`),
  preview: (config: RunConfig) => http.post<CommandPreview>('/api/runs/preview', config),
  dry: (body: DryRunRequest) => http.post<DryRunResult>('/api/runs/dry', body),
  start: (config: RunConfig) => http.post<RunStarted>('/api/runs', config),
}
