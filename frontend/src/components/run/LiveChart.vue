<script setup lang="ts">
import '@/charts/echarts'
import type { EChartsOption } from 'echarts'
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { downsample, type Point } from '@/charts/lttb'
import { useChartColors } from '@/charts/theme'
import type { ProgressEvent } from '@/types/events'

const props = defineProps<{ points: ProgressEvent[]; durationS: number | null }>()
const colors = useChartColors()

const tps = computed<Point[]>(() => downsample(props.points.map((p) => [p.t, p.tps])))
const latency = computed<Point[]>(() => downsample(props.points.map((p) => [p.t, p.lat_ms])))
const lastT = computed(() => props.points.at(-1)?.t ?? 0)

const option = computed<EChartsOption>(() => {
  const c = colors.value
  const axisLabel = { color: c.muted, fontFamily: c.fontBody, fontSize: 11 }
  const splitLine = { lineStyle: { color: c.border } }
  // -T: the axis covers the whole test; the future is shaded with «осталось N с».
  const max = props.durationS ?? undefined
  const left = props.durationS ? Math.max(Math.round(props.durationS - lastT.value), 0) : 0
  return {
    animation: false,
    grid: { left: 48, right: 40, top: 16, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v) => (typeof v === 'number' ? v.toLocaleString('ru-RU', { maximumFractionDigits: 2 }) : String(v)),
    },
    xAxis: {
      type: 'value',
      min: 0,
      max,
      axisLabel: { ...axisLabel, formatter: '{value} с' },
      splitLine: { show: false },
      axisLine: { lineStyle: { color: c.border } },
    },
    yAxis: [
      { type: 'value', min: 0, axisLabel, splitLine },
      { type: 'value', min: 0, axisLabel: { ...axisLabel, color: c.latency }, splitLine: { show: false } },
    ],
    series: [
      {
        name: 'TPS',
        type: 'line',
        data: tps.value,
        showSymbol: false,
        lineStyle: { color: c.tps, width: 2 },
        itemStyle: { color: c.tps },
        markArea:
          props.durationS && left > 0
            ? {
                silent: true,
                itemStyle: { color: c.surfaceMuted },
                label: { show: true, position: 'inside', color: c.muted, fontFamily: c.fontBody, formatter: `осталось ${left} с` },
                data: [[{ xAxis: lastT.value }, { xAxis: props.durationS }]],
              }
            : undefined,
      },
      {
        name: 'latency, мс',
        type: 'line',
        yAxisIndex: 1,
        data: latency.value,
        showSymbol: false,
        lineStyle: { color: c.latency, width: 1.5 },
        itemStyle: { color: c.latency },
      },
    ],
  }
})
</script>

<template>
  <section class="card chart-card" aria-labelledby="live-title">
    <header class="head">
      <h2 id="live-title">TPS и latency</h2>
      <div class="legend muted">
        <span><i class="line tps" />TPS</span>
        <span><i class="line lat" />latency, мс</span>
      </div>
    </header>
    <VChart class="chart" :option="option" autoresize aria-label="График TPS и latency" />
  </section>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.legend {
  display: flex;
  gap: 16px;
  font-size: 12px;
}

.line {
  display: inline-block;
  width: 14px;
  height: 3px;
  margin-right: 6px;
  border-radius: 2px;
  vertical-align: middle;
}

.line.tps {
  background: var(--color-primary);
}

.line.lat {
  background: var(--color-orange);
}

.chart {
  height: 260px;
  margin-top: 12px;
}
</style>
