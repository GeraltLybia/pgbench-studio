<script setup lang="ts">
import '@/charts/echarts'
import type { EChartsOption } from 'echarts'
import { computed } from 'vue'
import VChart from 'vue-echarts'
import type { HistogramBucket } from '@/api/runs'
import { useChartColors } from '@/charts/theme'
import { rebin } from './analysis'

const props = defineProps<{
  buckets: HistogramBucket[]
  percentiles: { p50?: number | null; p95?: number | null; p99?: number | null } | null
  sampled: boolean
}>()
const colors = useChartColors()

const bins = computed(() => rebin(props.buckets))
const format = (v: number) => v.toLocaleString('ru-RU', { maximumFractionDigits: v < 1 ? 3 : 1 })

function binOf(value: number): number {
  const i = bins.value.findIndex((b) => value < b.to)
  return i === -1 ? bins.value.length - 1 : i
}

const option = computed<EChartsOption>(() => {
  const c = colors.value
  const p99 = props.percentiles?.p99 ?? null
  const marks = (['p50', 'p95', 'p99'] as const)
    .map((name) => ({ name, value: props.percentiles?.[name] ?? null }))
    .filter((m): m is { name: 'p50' | 'p95' | 'p99'; value: number } => m.value !== null)
    .map((m) => ({
      xAxis: binOf(m.value),
      lineStyle: { color: c.text, type: 'dashed' as const, width: 1 },
      label: { formatter: `${m.name} ${format(m.value)}`, color: c.text, fontFamily: c.fontBody, fontWeight: 600 },
    }))
  return {
    animation: false,
    grid: { left: 8, right: 8, top: 28, bottom: 28, containLabel: false },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const index = (Array.isArray(params) ? params[0] : params)?.dataIndex ?? 0
        const bin = bins.value[index]
        return bin ? `${format(bin.from)}–${format(bin.to)} мс<br>${bin.count.toLocaleString('ru-RU')}` : ''
      },
    },
    xAxis: {
      type: 'category',
      data: bins.value.map((b) => format((b.from + b.to) / 2)),
      axisLabel: { color: c.muted, fontFamily: c.fontBody, fontSize: 11, formatter: '{value} мс' },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: c.border } },
    },
    yAxis: { type: 'value', show: false },
    series: [
      {
        type: 'bar',
        barCategoryGap: '12%',
        data: bins.value.map((b) => ({
          value: b.count,
          // Slower than p99: the tail, in orange as on the mockup.
          itemStyle: { color: p99 !== null && b.from >= p99 ? c.latency : c.tps, borderRadius: [2, 2, 0, 0] },
        })),
        markLine: { silent: true, symbol: 'none', data: marks },
      },
    ],
  }
})
</script>

<template>
  <section class="card histogram" aria-labelledby="histogram-title">
    <h2 id="histogram-title">Распределение latency</h2>
    <template v-if="bins.length">
      <VChart class="chart" :option="option" autoresize aria-label="Гистограмма latency" />
      <p v-if="sampled" class="muted note">По выборке транзакций (--sampling-rate).</p>
    </template>
    <p v-else class="muted empty">
      Гистограмма и p50 / p95 / p99 строятся в подробном режиме: на экране «Нагрузка» включите
      «Подробный лог каждой транзакции».
    </p>
  </section>
</template>

<style scoped>
.chart {
  height: 220px;
  margin-top: 8px;
}

.note {
  margin: 4px 0 0;
  font-size: 12px;
}

.empty {
  margin: 16px 0 0;
}
</style>
