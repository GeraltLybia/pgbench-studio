import { describe, expect, it } from 'vitest'
import { plural } from '@/composables/useFormat'
import {
  fieldErrors,
  loginSchema,
  passwordChangeSchema,
  usernameSchema,
} from '@/validation/password'

describe('password change schema', () => {
  const valid = { current: 'old-pass', next: 'new-password', repeat: 'new-password' }

  it('accepts a valid change', () => {
    expect(passwordChangeSchema.safeParse(valid).success).toBe(true)
  })

  it.each([
    [{ ...valid, next: 'short', repeat: 'short' }, 'next'],
    [{ ...valid, repeat: 'other-password' }, 'repeat'],
    [{ ...valid, next: 'old-pass', repeat: 'old-pass' }, 'next'],
    [{ ...valid, current: '' }, 'current'],
  ])('rejects %o on %s', (input, field) => {
    const result = passwordChangeSchema.safeParse(input)
    expect(result.success).toBe(false)
    if (!result.success) expect(Object.keys(fieldErrors(result.error))).toContain(field)
  })
})

describe('login and username', () => {
  it('requires both login fields', () => {
    const result = loginSchema.safeParse({ username: '  ', password: '' })
    expect(result.success).toBe(false)
    if (!result.success) {
      expect(fieldErrors(result.error)).toEqual({
        username: 'Введите логин',
        password: 'Введите пароль',
      })
    }
  })

  it('matches the backend username pattern', () => {
    expect(usernameSchema.safeParse('ivan.petrov-2').success).toBe(true)
    expect(usernameSchema.safeParse('ab').success).toBe(false)
    expect(usernameSchema.safeParse('иван').success).toBe(false)
    expect(usernameSchema.safeParse('a b c').success).toBe(false)
  })
})

describe('plural', () => {
  it.each([
    [1, 'попытка'],
    [2, 'попытки'],
    [4, 'попытки'],
    [5, 'попыток'],
    [11, 'попыток'],
    [12, 'попыток'],
    [21, 'попытка'],
    [22, 'попытки'],
  ])('%i -> %s', (n, form) => {
    expect(plural(n, ['попытка', 'попытки', 'попыток'])).toBe(form)
  })
})
