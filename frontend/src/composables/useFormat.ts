const dateTime = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

const time = new Intl.DateTimeFormat('ru-RU', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return '—'
  return dateTime.format(typeof value === 'string' ? new Date(value) : value)
}

export function formatTime(value: string | Date | null | undefined): string {
  if (!value) return '—'
  return time.format(typeof value === 'string' ? new Date(value) : value)
}

/** Russian plural: plural(2, ['попытка', 'попытки', 'попыток']) -> 'попытки' */
export function plural(n: number, forms: [string, string, string]): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return forms[0]
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1]
  return forms[2]
}

const integer = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const decimal = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

/** 10000000 -> «10 000 000» */
export function formatInt(value: number | null | undefined): string {
  return value == null ? '—' : integer.format(value)
}

const UNITS = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']

/** 1610612736 -> «1,5 ГБ» */
export function formatBytes(bytes: number): string {
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${decimal.format(value)} ${UNITS[unit]}`
}

export function formatMs(ms: number): string {
  return `${decimal.format(ms)} мс`
}

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  const m = Math.floor(s / 60)
  return m > 0 ? `${m} мин ${s % 60} с` : `${s} с`
}

export function isToday(value: string | Date): boolean {
  const date = typeof value === 'string' ? new Date(value) : value
  return date.toDateString() === new Date().toDateString()
}

/** 114 -> «1 мин 54 с», 3725 -> «1 ч 2 мин» */
export function formatLeft(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h} ч ${m} мин`
  return m > 0 ? `${m} мин ${s % 60} с` : `${s % 60} с`
}

/** 1440000 -> «1,44 млн» */
export function formatCompact(value: number): string {
  if (value >= 1_000_000) return `${decimal.format(Math.round(value / 10_000) / 100)} млн`
  if (value >= 10_000) return `${decimal.format(Math.round(value / 100) / 10)} тыс`
  return integer.format(Math.round(value))
}

/** Latency in ms: three decimals below 1 ms (0,082), otherwise `digits` (6,64). */
export function formatLatency(ms: number, digits = 2): string {
  return formatNumber(ms, ms < 1 ? 3 : digits)
}

export function formatNumber(value: number, digits = 0): string {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value)
}
