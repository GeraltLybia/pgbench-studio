import { z } from 'zod'

/** Mirrors ConnectionFields / ProfileCreate in backend/app/schemas.py. */
export const SSL_MODES = ['disable', 'prefer', 'require', 'verify-full'] as const

export const connectionSchema = z.object({
  host: z
    .string()
    .trim()
    .min(1, 'Укажите хост')
    .max(255, 'Не длиннее 255 символов')
    .regex(/^[A-Za-z0-9._:\-[\]]+$/, 'Только имя хоста или IP-адрес, без пробелов и запятых'),
  port: z.coerce
    .number({ message: 'Укажите порт' })
    .int('Целое число')
    .min(1, 'От 1 до 65535')
    .max(65535, 'От 1 до 65535'),
  dbname: z.string().min(1, 'Укажите базу данных').max(63, 'Не длиннее 63 символов'),
  user: z.string().min(1, 'Укажите пользователя').max(63, 'Не длиннее 63 символов'),
  sslmode: z.enum(SSL_MODES),
  app_name: z
    .string()
    .max(63, 'Не длиннее 63 символов')
    .regex(/^[\x20-\x7e]*$/, 'Только латиница, цифры и знаки ASCII'),
  connect_timeout_s: z.coerce
    .number({ message: 'Укажите таймаут' })
    .int('Целое число')
    .min(1, 'От 1 до 120 секунд')
    .max(120, 'От 1 до 120 секунд'),
  password: z.string().max(1024, 'Не длиннее 1024 символов'),
})

/** Form state: numbers stay strings while typing and are coerced on validation. */
export interface ConnectionForm {
  host: string
  port: string
  dbname: string
  user: string
  sslmode: (typeof SSL_MODES)[number]
  app_name: string
  connect_timeout_s: string
  password: string
}

export type ConnectionValues = z.output<typeof connectionSchema>

export function emptyConnection(): ConnectionForm {
  return {
    host: '',
    port: '5432',
    dbname: '',
    user: '',
    sslmode: 'prefer',
    app_name: 'pgbench-studio',
    connect_timeout_s: '10',
    password: '',
  }
}

/** Default profile name for a new profile, like «stage-db · bench» on the mockup. */
export function defaultProfileName(host: string, dbname: string): string {
  const shortHost = host.includes(':') ? host : (host.split('.')[0] ?? host)
  return `${shortHost} · ${dbname}`
}
