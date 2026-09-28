/**
 * Largest-Triangle-Three-Buckets downsampling for long series
 * (docs/architecture.md: more than 3600 points).
 */
export const LTTB_THRESHOLD = 3600

export type Point = [number, number]

export function lttb(data: Point[], threshold: number): Point[] {
  if (threshold >= data.length || threshold < 3) return data
  const sampled: Point[] = [data[0]!]
  const every = (data.length - 2) / (threshold - 2)
  let a = 0
  for (let i = 0; i < threshold - 2; i++) {
    const rangeStart = Math.floor((i + 1) * every) + 1
    const rangeEnd = Math.min(Math.floor((i + 2) * every) + 1, data.length)
    let avgX = 0
    let avgY = 0
    for (let j = rangeStart; j < rangeEnd; j++) {
      avgX += data[j]![0]
      avgY += data[j]![1]
    }
    const count = Math.max(rangeEnd - rangeStart, 1)
    avgX /= count
    avgY /= count

    const bucketStart = Math.floor(i * every) + 1
    const bucketEnd = Math.floor((i + 1) * every) + 1
    const [ax, ay] = data[a]!
    let maxArea = -1
    let next = bucketStart
    for (let j = bucketStart; j < bucketEnd; j++) {
      const [x, y] = data[j]!
      const area = Math.abs((ax - avgX) * (y - ay) - (ax - x) * (avgY - ay))
      if (area > maxArea) {
        maxArea = area
        next = j
      }
    }
    sampled.push(data[next]!)
    a = next
  }
  sampled.push(data[data.length - 1]!)
  return sampled
}

export function downsample(data: Point[]): Point[] {
  return data.length > LTTB_THRESHOLD ? lttb(data, LTTB_THRESHOLD) : data
}
