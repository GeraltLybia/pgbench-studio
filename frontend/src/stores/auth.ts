import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authApi, type Me } from '@/api/auth'
import { ApiError } from '@/api/http'
import { can as canRole, type Action } from '@/auth/permissions'
import { useProfilesStore } from './profiles'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<Me | null>(null)
  /** true once the session has been checked with /api/auth/me */
  const loaded = ref(false)

  const role = computed(() => user.value?.role ?? null)
  const mustChangePassword = computed(() => user.value?.must_change_password ?? false)

  async function fetchMe(): Promise<Me | null> {
    try {
      user.value = await authApi.me()
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error
      user.value = null
    } finally {
      loaded.value = true
    }
    return user.value
  }

  async function login(username: string, password: string): Promise<Me> {
    user.value = await authApi.login(username, password)
    loaded.value = true
    return user.value
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } finally {
      clear()
    }
  }

  async function changePassword(current: string, next: string): Promise<void> {
    user.value = await authApi.changePassword(current, next)
  }

  function clear(): void {
    user.value = null
    loaded.value = true
    // The next user checks the connection again under their own role.
    useProfilesStore().reset()
  }

  function can(action: Action): boolean {
    return canRole(role.value, action)
  }

  return { user, loaded, role, mustChangePassword, fetchMe, login, logout, changePassword, clear, can }
})
