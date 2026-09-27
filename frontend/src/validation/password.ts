import { z } from 'zod'

/** Same limits as the backend (app/security/passwords.py). */
export const MIN_PASSWORD_LENGTH = 8
export const MAX_PASSWORD_LENGTH = 256

export const loginSchema = z.object({
  username: z.string().trim().min(1, 'Введите логин'),
  password: z.string().min(1, 'Введите пароль'),
})

export const passwordChangeSchema = z
  .object({
    current: z.string().min(1, 'Введите текущий пароль'),
    next: z
      .string()
      .min(MIN_PASSWORD_LENGTH, `Не короче ${MIN_PASSWORD_LENGTH} символов`)
      .max(MAX_PASSWORD_LENGTH, `Не длиннее ${MAX_PASSWORD_LENGTH} символов`),
    repeat: z.string(),
  })
  .refine((v) => v.next === v.repeat, { path: ['repeat'], message: 'Пароли не совпадают' })
  .refine((v) => v.next !== v.current, {
    path: ['next'],
    message: 'Новый пароль должен отличаться от текущего',
  })

/** Same pattern as USERNAME_PATTERN in app/schemas.py. */
export const usernameSchema = z
  .string()
  .regex(/^[A-Za-z0-9._-]{3,64}$/, 'От 3 до 64 символов: латиница, цифры, точка, дефис, подчёркивание')

export type FieldErrors<K extends string> = Partial<Record<K, string>>

export function fieldErrors<K extends string>(error: z.ZodError): FieldErrors<K> {
  const result: FieldErrors<K> = {}
  for (const issue of error.issues) {
    const key = issue.path[0] as K | undefined
    if (key !== undefined && result[key] === undefined) result[key] = issue.message
  }
  return result
}
