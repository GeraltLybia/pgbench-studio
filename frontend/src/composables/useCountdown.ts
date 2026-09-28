/** Remaining time and end time, counted down locally between progress points. */
import { useIntervalFn } from '@vueuse/core'
import { computed, shallowRef, type Ref } from 'vue'

export function useCountdown(etaAtLastPoint: Ref<number | null>, lastPointAt: Ref<number | null>) {
  const now = shallowRef(new Date())
  useIntervalFn(() => (now.value = new Date()), 1000)

  const remaining = computed(() => {
    if (etaAtLastPoint.value === null || lastPointAt.value === null) return null
    const elapsed = Math.max((now.value.getTime() - lastPointAt.value) / 1000, 0)
    return Math.max(etaAtLastPoint.value - elapsed, 0)
  })
  const endsAt = computed(() =>
    remaining.value === null ? null : new Date(now.value.getTime() + remaining.value * 1000),
  )
  return { remaining, endsAt, now }
}
