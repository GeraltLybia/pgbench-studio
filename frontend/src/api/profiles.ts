import type { components } from '@/types/api'
import { http } from './http'

export type Profile = components['schemas']['ProfileOut']
export type ProfileCreate = components['schemas']['ProfileCreate']
export type ProfileUpdate = components['schemas']['ProfileUpdate']
export type ConnectionTestRequest = components['schemas']['ConnectionTestRequest']
export type ConnectionTestOk = components['schemas']['ConnectionTestOk']
export type ConnectionTestFail = components['schemas']['ConnectionTestFail']
export type ConnectionTestResult = ConnectionTestOk | ConnectionTestFail
export type SslMode = Profile['sslmode']
export type InitRequest = components['schemas']['InitRequest']
export type RunStarted = components['schemas']['RunStarted']

export const profilesApi = {
  list: () => http.get<Profile[]>('/api/profiles'),
  create: (body: ProfileCreate) => http.post<Profile>('/api/profiles', body),
  update: (id: number, body: ProfileUpdate) => http.put<Profile>(`/api/profiles/${id}`, body),
  remove: (id: number) => http.delete<void>(`/api/profiles/${id}`),
  test: (body: ConnectionTestRequest) =>
    http.post<ConnectionTestResult>('/api/profiles/test', body),
  init: (id: number, body: InitRequest) => http.post<RunStarted>(`/api/profiles/${id}/init`, body),
}
