import type { RouteLocationNormalized, RouteLocationRaw } from 'vue-router'
import { roleAllows, type Role } from '@/auth/permissions'

declare module 'vue-router' {
  interface RouteMeta {
    /** Reachable without a session (only /login). */
    public?: boolean
    /** Minimal role; the backend checks it again on every request. */
    role?: Role
    /** Full-screen page without the sidebar. */
    bare?: boolean
    title?: string
  }
}

export interface SessionState {
  loaded: boolean
  role: Role | null
  mustChangePassword: boolean
  ensureLoaded: () => Promise<void>
}

export const HOME = '/connect'

function safeRedirect(value: unknown): string {
  // Only in-app paths: never follow an absolute or protocol-relative URL.
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    ? value
    : HOME
}

/** Decide where navigation goes: true to proceed or a redirect. */
export async function resolveNavigation(
  to: RouteLocationNormalized,
  session: SessionState,
): Promise<true | RouteLocationRaw> {
  if (!session.loaded) await session.ensureLoaded()
  const loggedIn = session.role !== null

  if (to.meta.public) {
    if (loggedIn && to.name === 'login') return safeRedirect(to.query.redirect)
    return true
  }
  if (!loggedIn) {
    return { name: 'login', query: to.fullPath === HOME ? {} : { redirect: to.fullPath } }
  }
  if (session.mustChangePassword && to.name !== 'password') {
    return { name: 'password' }
  }
  if (to.meta.role && !roleAllows(session.role!, to.meta.role)) {
    return HOME
  }
  return true
}

export { safeRedirect }
