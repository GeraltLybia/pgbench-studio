<script setup lang="ts">
import '@/charts/echarts'
import type { EChartsOption } from 'echarts'
import { computed } from 'vue'
import VChart from 'vue-echarts'
import type { SeriesPoint } from '@/api/runs'
import { downsample } from '@/charts/lttb'
import { useChartColors } from '@/charts/theme'

const props = defineProps<{ series: SeriesPoint[] }>()
const colors = useChartColors()

const withLatency = computed(() => props.series.filter((p) => p.lat_avg_ms !== null))
const hasBand = computed(() => withLatency.value.some((p) => p.lat_min_ms !== null && p.lat_max_ms !== null))
const avg = computed(() => downsample(withLatency.value.map((p) => [p.t_s, p.lat_avg_ms!])))
// The band is two stacked series: an invisible floor at min and the min–max height on top.
const floor = computed(() => withLatency.value.map((p) => [p.t_s, p.lat_min_ms]))
const height = computed(() =>
  withLatency.value.map((p) => [
    p.t_s,
    p.lat_min_ms !== null && p.lat_max_ms !== null ? p.lat_max_ms - p.lat_min_ms : null,
  ]),
)
const format = (v: number) => v.toLocaleString('ru-RU', { maximumFractionDigits: 3 })

const option = computed<EChartsOption>(() => {
  const c = colors.value
  const axisLabel = { color: c.muted, fontFamily: c.fontBody, fontSize: 11 }
  const band = hasBand.value
    ? [
        {
          name: 'min',
          type: 'line' as const,
          data: floor.value,
          stack: 'band',
          showSymbol: false,
          lineStyle: { opacity: 0 },
          silent: true,
        },
        {
          name: 'min–max',
          type: 'line' as const,
          data: height.value,
          stack: 'band',
          showSymbol: false,
          lineStyle: { opacity: 0 },
          areaStyle: { color: c.latency, opacity: 0.18 },
          silent: true,
        },
      ]
    : []
  return {
    animation: false,
    grid: { left: 56, right: 24, top: 16, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const list = Array.isArray(params) ? params : [params]
        const t = (list[0]?.value as number[] | undefined)?.[0]
        const point = withLatency.value.find((p) => p.t_s === t)
        if (!point) return ''
        const rows = [`${t} с`, `среднее ${format(point.lat_avg_ms!)} мс`]
        if (point.lat_min_ms !== null && point.lat_max_ms !== null) {
          rows.push(`min–max ${format(point.lat_min_ms)}–${format(point.lat_max_ms)} мс`)
        }
        return rows.join('<br>')
      },
    },
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
      axisLabel: { ...axisLabel, formatter: (v: number) => v.toLocaleString('ru-RU') },
      splitLine: { lineStyle: { color: c.border } },
    },
    series: [
      ...band,
      {
        name: 'среднее',
        type: 'line',
        data: avg.value,
        showSymbol: false,
        lineStyle: { color: c.latency, width: 1.5 },
        itemStyle: { color: c.latency },
      },
    ],
  }
})
</script>

<template>
  <section class="card chart-card" aria-labelledby="latency-title">
    <header class="head">
      <h2 id="latency-title">Latency во времени</h2>
      <div class="legend muted">
        <span><i class="line" />среднее</span>
        <span v-if="hasBand"><i class="band" />min–max за секунду</span>
        <span>мс</span>
      </div>
    </header>
    <VChart
      v-if="withLatency.length"
      class="chart"
      :option="option"
      autoresize
      aria-label="График latency по секундам"
    />
    <p v-else class="muted empty">Нет данных о latency.</p>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 16px;
}

.legend {
  display: flex;
  gap: 16px;
  font-size: 12px;
}

.line,
.band {
  display: inline-block;
  width: 14px;
  margin-right: 6px;
  vertical-align: middle;
  border-radius: 2px;
}

.line {
  height: 3px;
  background: var(--color-orange);
}

.band {
  height: 10px;
  background: var(--color-orange);
  opacity: 0.25;
}

.chart {
  height: 240px;
  margin-top: 12px;
}

.empty {
  margin: 24px 0 8px;
}
</style>
