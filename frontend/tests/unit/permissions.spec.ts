import { describe, expect, it } from 'vitest'
import { can, roleAllows, type Action, type Role } from '@/auth/permissions'

const MATRIX: [Action, Record<Role, boolean>][] = [
  ['history.view', { viewer: true, editor: true, admin: true }],
  ['runs.watch', { viewer: true, editor: true, admin: true }],
  ['profiles.view', { viewer: true, editor: true, admin: true }],
  ['profiles.edit', { viewer: false, editor: true, admin: true }],
  ['connection.test', { viewer: false, editor: true, admin: true }],
  ['scripts.edit', { viewer: false, editor: true, admin: true }],
  ['runs.start', { viewer: false, editor: true, admin: true }],
  ['runs.delete', { viewer: false, editor: true, admin: true }],
  ['users.manage', { viewer: false, editor: false, admin: true }],
  ['password.change', { viewer: true, editor: true, admin: true }],
]

describe('role matrix', () => {
  it.each(MATRIX)('%s', (action, expected) => {
    for (const role of ['viewer', 'editor', 'admin'] as const) {
      expect(can(role, action)).toBe(expected[role])
    }
  })

  it('denies everything without a role', () => {
    expect(can(null, 'history.view')).toBe(false)
    expect(can(undefined, 'password.change')).toBe(false)
  })

  it('orders roles', () => {
    expect(roleAllows('admin', 'editor')).toBe(true)
    expect(roleAllows('editor', 'admin')).toBe(false)
  })
})
