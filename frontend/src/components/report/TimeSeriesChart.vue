<script setup lang="ts">
import '@/charts/echarts'
import type { EChartsOption } from 'echarts'
import { computed } from 'vue'
import VChart from 'vue-echarts'
import type { SeriesPoint } from '@/api/runs'
import { downsample } from '@/charts/lttb'
import { useChartColors } from '@/charts/theme'
import { dipLabel, findDips } from './analysis'

const props = defineProps<{ series: SeriesPoint[]; meanTps: number | null; note: string }>()
const colors = useChartColors()

const data = computed(() => downsample(props.series.map((p) => [p.t_s, p.tps])))
const dips = computed(() => findDips(props.series))
const format = (v: number) => v.toLocaleString('ru-RU', { maximumFractionDigits: 0 })

const option = computed<EChartsOption>(() => {
  const c = colors.value
  const axisLabel = { color: c.muted, fontFamily: c.fontBody, fontSize: 11 }
  const markLines: object[] = dips.value.map((dip) => ({
    xAxis: dip.from,
    lineStyle: { color: c.latency, type: 'dashed', width: 1 },
    label: { formatter: dipLabel(dip), color: c.latency, position: 'end', fontFamily: c.fontBody },
  }))
  if (props.meanTps !== null) {
    markLines.push({
      yAxis: props.meanTps,
      lineStyle: { color: c.tps, type: 'dashed', width: 1 },
      label: { formatter: format(props.meanTps), color: c.tps, position: 'end', fontFamily: c.fontBody },
    })
  }
  return {
    animation: false,
    grid: { left: 56, right: 56, top: 24, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v) => (typeof v === 'number' ? format(v) : String(v)),
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
      {
        name: 'TPS',
        type: 'line',
        data: data.value,
        showSymbol: false,
        lineStyle: { color: c.tps, width: 1.5 },
        itemStyle: { color: c.tps },
        areaStyle: { color: c.tps, opacity: 0.08 },
        markLine: { silent: true, symbol: 'none', data: markLines },
      },
    ],
  }
})
</script>

<template>
  <section class="card chart-card" aria-labelledby="tps-title">
    <header class="head">
      <h2 id="tps-title">Пропускная способность, TPS</h2>
      <span class="muted note">{{ note }}</span>
    </header>
    <VChart
      v-if="series.length"
      class="chart"
      :option="option"
      autoresize
      aria-label="График TPS по секундам"
    />
    <p v-else class="muted empty">Нет данных: pgbench не записал ни одного интервала.</p>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 16px;
}

.note {
  font-size: 12px;
}

.chart {
  height: 260px;
  margin-top: 12px;
}

.empty {
  margin: 24px 0 8px;
}
</style>
