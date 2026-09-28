/** Pure helpers of the report screen: dips, histogram bins, command arguments. */
import type { HistogramBucket, SeriesPoint } from '@/api/runs'

export interface Dip {
  from: number
  to: number
  minTps: number
}

/** Share of the median TPS below which a second counts as a dip. */
export const DIP_RATIO = 0.5
const MAX_DIPS = 3

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2
}

/**
 * Seconds where TPS falls below half of the median, merged into ranges; the deepest three.
 * The first and last points are skipped: ramp-up and an incomplete interval.
 */
export function findDips(points: Pick<SeriesPoint, 't_s' | 'tps'>[], ratio = DIP_RATIO): Dip[] {
  if (points.length < 5) return []
  const inner = points.slice(1, -1)
  const threshold = median(inner.map((p) => p.tps)) * ratio
  if (threshold <= 0) return []
  const dips: Dip[] = []
  for (const p of inner) {
    if (p.tps >= threshold) continue
    const last = dips.at(-1)
    if (last && p.t_s - last.to <= 1) {
      last.to = p.t_s
      last.minTps = Math.min(last.minTps, p.tps)
    } else {
      dips.push({ from: p.t_s, to: p.t_s, minTps: p.tps })
    }
  }
  return dips
    .sort((a, b) => a.minTps - b.minTps)
    .slice(0, MAX_DIPS)
    .sort((a, b) => a.from - b.from)
}

export function dipLabel(dip: Dip): string {
  return dip.from === dip.to ? `просадка ${dip.from} с` : `просадка ${dip.from}–${dip.to} с`
}

export interface Bin {
  from: number
  to: number
  count: number
}

/** Upper edge / lower edge of a stored bucket (1 % logarithmic buckets). */
const BUCKET_RATIO = 1.01

/**
 * Stored log buckets regrouped into `count` equal bins for display. The range ends at the
 * 99.9th percentile; the rare slower transactions go into the last bin.
 */
export function rebin(buckets: HistogramBucket[], count = 40, clip = 0.999): Bin[] {
  const total = buckets.reduce((s, b) => s + b.count, 0)
  if (!total) return []
  const lo = buckets[0]!.upper_ms / BUCKET_RATIO
  let seen = 0
  let hi = buckets.at(-1)!.upper_ms
  for (const b of buckets) {
    seen += b.count
    if (seen >= total * clip) {
      hi = b.upper_ms
      break
    }
  }
  const width = (hi - lo) / count || 1
  const bins: Bin[] = Array.from({ length: count }, (_, i) => ({
    from: lo + i * width,
    to: lo + (i + 1) * width,
    count: 0,
  }))
  for (const b of buckets) {
    const mid = (b.upper_ms / BUCKET_RATIO + b.upper_ms) / 2
    const index = Math.min(Math.max(Math.floor((mid - lo) / width), 0), count - 1)
    bins[index]!.count += b.count
  }
  return bins
}

/** Flags the agent always adds, and the scenario list (shown in its own row). */
const AUTO = /^(-r|-l|--log-prefix=.*|--failures-detailed|--aggregate-interval=.*)$/
const WITH_VALUE = new Set(['-P', '-b', '-f'])

/** The load arguments a user chose: `-c 32 -j 8 -T 300 -M prepared`. */
export function loadArgs(argv: string[]): string {
  const out: string[] = []
  for (let i = 1; i < argv.length; i++) {
    const arg = argv[i]!
    if (WITH_VALUE.has(arg)) {
      i += 1
      continue
    }
    if (!AUTO.test(arg)) out.push(arg)
  }
  return out.join(' ')
}
