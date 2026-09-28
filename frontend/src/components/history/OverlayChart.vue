<script setup lang="ts">
import '@/charts/echarts'
import type { EChartsOption } from 'echarts'
import { computed } from 'vue'
import VChart from 'vue-echarts'
import type { SeriesPoint } from '@/api/runs'
import { downsample } from '@/charts/lttb'
import { useChartColors } from '@/charts/theme'

/** Two runs on one axis from 0 s: `a` in blue, `b` in orange, as on the mockup. */
const props = withDefaults(
  defineProps<{
    a: SeriesPoint[]
    b: SeriesPoint[]
    labelA: string
    labelB: string
    metric?: 'tps' | 'lat_avg_ms'
    height?: number
  }>(),
  { metric: 'tps', height: 220 },
)
const colors = useChartColors()

function points(series: SeriesPoint[]) {
  return downsample(
    series.filter((p) => p[props.metric] !== null).map((p) => [p.t_s, p[props.metric] as number]),
  )
}

const option = computed<EChartsOption>(() => {
  const c = colors.value
  const axisLabel = { color: c.muted, fontFamily: c.fontBody, fontSize: 11 }
  const digits = props.metric === 'tps' ? 0 : 3
  const format = (v: number) => v.toLocaleString('ru-RU', { maximumFractionDigits: digits })
  return {
    animation: false,
    grid: { left: 56, right: 16, top: 12, bottom: 28 },
    tooltip: { trigger: 'axis', valueFormatter: (v) => (typeof v === 'number' ? format(v) : String(v)) },
    xAxis: {
      type: 'value',
      min: 0,
      max: 'dataMax',
      axisLabel: { ...axisLabel, formatter: '{value} с' },
      splitLine: { show: false },
      axisLine: { lineStyle: { color: c.border } },
    },
    yAxis: {
      type: 'value',
      min: 0,
      axisLabel: { ...axisLabel, formatter: (v: number) => format(v) },
      splitLine: { lineStyle: { color: c.border } },
    },
    series: [
      { name: props.labelA, type: 'line', data: points(props.a), showSymbol: false, lineStyle: { color: c.tps, width: 1.5 }, itemStyle: { color: c.tps } },
      { name: props.labelB, type: 'line', data: points(props.b), showSymbol: false, lineStyle: { color: c.latency, width: 1.5 }, itemStyle: { color: c.latency } },
    ],
  }
})
</script>

<template>
  <VChart
    class="overlay"
    :style="{ height: `${height}px` }"
    :option="option"
    autoresize
    :aria-label="`${metric === 'tps' ? 'TPS' : 'Latency'}: ${labelA} и ${labelB}`"
  />
</template>
