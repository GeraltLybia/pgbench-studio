import type { components } from '@/types/api'
import { http } from './http'

export type Me = components['schemas']['Me']
export type Role = Me['role']

export const authApi = {
  login: (username: string, password: string) =>
    http.post<Me>('/api/auth/login', { username, password }, { silent: true }),
  logout: () => http.post<void>('/api/auth/logout', undefined, { silent: true }),
  me: () => http.get<Me>('/api/auth/me', { silent: true }),
  changePassword: (currentPassword: string, newPassword: string) =>
    http.post<Me>('/api/auth/password', {
      current_password: currentPassword,
      new_password: newPassword,
    }),
}
