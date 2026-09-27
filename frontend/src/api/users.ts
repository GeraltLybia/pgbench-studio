import type { components } from '@/types/api'
import { http } from './http'

export type User = components['schemas']['UserOut']
export type UserCreate = components['schemas']['UserCreate']
export type UserUpdate = components['schemas']['UserUpdate']
export type TemporaryPassword = components['schemas']['TemporaryPassword']

export const usersApi = {
  list: () => http.get<User[]>('/api/users'),
  create: (body: UserCreate) => http.post<TemporaryPassword>('/api/users', body),
  update: (id: number, body: UserUpdate) => http.patch<User>(`/api/users/${id}`, body),
  resetPassword: (id: number) =>
    http.post<TemporaryPassword>(`/api/users/${id}/reset-password`),
}
