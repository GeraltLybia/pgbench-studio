/** Formatting shared by the compare panel and the compare screen. */
import type { MetricDiff } from '@/api/runs'
import { formatInt, formatLatency, formatNumber } from '@/composables/useFormat'

export function metricValue(m: Pick<MetricDiff, 'key'>, value: number | null): string {
  if (value === null) return '—'
  if (m.key === 'tps') return formatNumber(value, 0)
  if (m.key === 'processed' || m.key === 'failed') return formatInt(value)
  return `${formatLatency(value)} мс`
}

export function diffText(pct: number | null): string {
  if (pct === null) return ''
  return `${pct > 0 ? '+' : pct < 0 ? '−' : '±'}${formatNumber(Math.abs(pct), 1)}%`
}

/** better / worse / same for colouring: +TPS is good, +latency is bad. */
export function diffTone(m: Pick<MetricDiff, 'better' | 'diff_pct'>): 'good' | 'bad' | 'same' {
  if (m.diff_pct === null || m.diff_pct === 0) return 'same'
  return (m.diff_pct > 0) === (m.better === 'higher') ? 'good' : 'bad'
}
