import type { components } from '@/types/api'
import { http } from './http'

export type SystemHealth = components['schemas']['SystemHealth']
export type HealthCheck = components['schemas']['HealthCheckOut']
export type SystemInfo = components['schemas']['SystemInfo']
export type Readiness = components['schemas']['Readiness']

export const systemApi = {
  health: () => http.get<SystemHealth>('/api/system/health'),
  info: () => http.get<SystemInfo>('/api/system/info'),
  /** Public probe for the login screen; 503 still carries the list of failed checks. */
  async readiness(): Promise<Readiness | null> {
    try {
      const response = await fetch('/readyz', { credentials: 'same-origin' })
      if (response.status !== 200 && response.status !== 503) return null
      return (await response.json()) as Readiness
    } catch {
      return null
    }
  },
}
