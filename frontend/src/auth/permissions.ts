/** Role matrix from docs/architecture.md, «Роли и доступ». The backend enforces it too. */

export type Role = 'viewer' | 'editor' | 'admin'

export type Action =
  | 'history.view'
  | 'runs.watch'
  | 'profiles.view'
  | 'profiles.edit'
  | 'connection.test'
  | 'scripts.edit'
  | 'runs.start'
  | 'runs.delete'
  | 'users.manage'
  | 'password.change'

const LEVEL: Record<Role, number> = { viewer: 0, editor: 1, admin: 2 }

const REQUIRED: Record<Action, Role> = {
  'history.view': 'viewer',
  'runs.watch': 'viewer',
  'profiles.view': 'viewer',
  'profiles.edit': 'editor',
  'connection.test': 'editor',
  'scripts.edit': 'editor',
  'runs.start': 'editor',
  'runs.delete': 'editor',
  'users.manage': 'admin',
  'password.change': 'viewer',
}

export function roleAllows(role: Role, required: Role): boolean {
  return LEVEL[role] >= LEVEL[required]
}

export function can(role: Role | null | undefined, action: Action): boolean {
  return role != null && roleAllows(role, REQUIRED[action])
}

export const ROLE_LABELS: Record<Role, string> = {
  viewer: 'Наблюдатель',
  editor: 'Редактор',
  admin: 'Администратор',
}
