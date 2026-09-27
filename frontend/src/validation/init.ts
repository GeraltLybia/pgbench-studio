import { z } from 'zod'

/** Mirrors app/core/command.py: rough size of one scale unit, and the confirmation threshold. */
export const BYTES_PER_SCALE = 15 * 1024 ** 2
export const LARGE_INIT_BYTES = 50 * 1024 ** 3

export function estimateInitBytes(scale: number, fillfactor: number): number {
  return (scale * BYTES_PER_SCALE * 100) / fillfactor
}

export function initSchema(maxScale: number) {
  return z.object({
    scale: z.coerce
      .number({ message: 'Укажите scale' })
      .int('Целое число')
      .min(1, 'Не меньше 1')
      .max(maxScale, `Не больше ${maxScale} (limits.max_scale)`),
    fillfactor: z.coerce
      .number({ message: 'Укажите fillfactor' })
      .int('Целое число')
      .min(10, 'От 10 до 100')
      .max(100, 'От 10 до 100'),
    foreign_keys: z.boolean(),
    unlogged: z.boolean(),
  })
}

export interface InitForm {
  scale: string
  fillfactor: string
  foreign_keys: boolean
  unlogged: boolean
}
