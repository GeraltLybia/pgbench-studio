<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ values: number[]; width?: number; height?: number }>(), {
  width: 80,
  height: 22,
})

const path = computed(() => {
  const v = props.values
  if (v.length < 2) return ''
  const max = Math.max(...v)
  const min = Math.min(...v)
  const span = max - min || 1
  const step = props.width / (v.length - 1)
  return v
    .map((y, i) => `${(i * step).toFixed(1)},${(props.height - 2 - ((y - min) / span) * (props.height - 4)).toFixed(1)}`)
    .join(' ')
})
</script>

<template>
  <svg
    v-if="path"
    class="sparkline"
    :width="width"
    :height="height"
    :viewBox="`0 0 ${width} ${height}`"
    role="img"
    aria-label="Динамика TPS"
  >
    <polyline :points="path" fill="none" stroke="var(--color-primary)" stroke-width="1.5" stroke-linejoin="round" />
  </svg>
  <span v-else class="muted">—</span>
</template>
