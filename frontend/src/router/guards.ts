import type { RouteLocationNormalized, RouteLocationRaw } from 'vue-router'
import { can, roleAllows, type Role } from '@/auth/permissions'

declare module 'vue-router' {
  interface RouteMeta {
    /** Reachable without a session (only /login). */
    public?: boolean
    /** Minimal role; the backend checks it again on every request. */
    role?: Role
    /** Full-screen page without the sidebar. */
    bare?: boolean
    title?: string
    /**
     * Needs a successful connection check with the current parameters.
     * 'all' — for every role; 'testers' — only for roles that can run the check
     * (viewers still watch runs and reports without it).
     */
    requiresConnection?: 'all' | 'testers'
  }
}

export interface SessionState {
  loaded: boolean
  role: Role | null
  mustChangePassword: boolean
  ensureLoaded: () => Promise<void>
  /** Loads profiles, auto-checks the remembered one once, reports a passed check. */
  connectionReady: () => Promise<boolean>
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
  const rule = to.meta.requiresConnection
  if (rule && (rule === 'all' || can(session.role, 'connection.test'))) {
    if (!(await session.connectionReady())) return HOME
  }
  return true
}

export { safeRedirect }
