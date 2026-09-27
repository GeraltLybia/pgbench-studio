import type { components } from '@/types/api'
import { http } from './http'

export type Run = components['schemas']['RunOut']
export type RunStatus = Run['status']

export const FINISHED_STATUSES: readonly RunStatus[] = ['completed', 'failed', 'cancelled']

export const runsApi = {
  get: (id: number) => http.get<Run>(`/api/runs/${id}`),
}
