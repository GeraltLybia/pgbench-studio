<script setup lang="ts">
import '@/charts/echarts'
import type { EChartsOption } from 'echarts'
import { computed } from 'vue'
import VChart from 'vue-echarts'
import type { ResourcePoint } from '@/api/runs'
import { downsample } from '@/charts/lttb'
import { useChartColors } from '@/charts/theme'
import { formatNumber } from '@/composables/useFormat'

const props = defineProps<{ samples: ResourcePoint[]; cpuThreshold: number; agentName: string | null }>()
const colors = useChartColors()

const peakCpu = computed(() => Math.max(...props.samples.map((s) => s.cpu_pct), 0))
const avgCpu = computed(() =>
  props.samples.length ? props.samples.reduce((s, x) => s + x.cpu_pct, 0) / props.samples.length : 0,
)
const peakRam = computed(() => Math.max(...props.samples.map((s) => s.ram_pct), 0))

const option = computed<EChartsOption>(() => {
  const c = colors.value
  const axisLabel = { color: c.muted, fontFamily: c.fontBody, fontSize: 11 }
  return {
    animation: false,
    grid: { left: 44, right: 16, top: 12, bottom: 28 },
    tooltip: { trigger: 'axis', valueFormatter: (v) => (typeof v === 'number' ? `${formatNumber(v, 0)} %` : String(v)) },
    xAxis: {
      type: 'value',
      min: 0,
      max: 'dataMax',
      axisLabel: { ...axisLabel, formatter: '{value} с' },
      splitLine: { show: false },
      axisLine: { lineStyle: { color: c.border } },
    },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { ...axisLabel, formatter: '{value} %' }, splitLine: { lineStyle: { color: c.border } } },
    series: [
      {
        name: 'CPU',
        type: 'line',
        data: downsample(props.samples.map((s) => [s.t_s, s.cpu_pct])),
        showSymbol: false,
        lineStyle: { color: c.cpu, width: 1.5 },
        itemStyle: { color: c.cpu },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: c.latency, type: 'dashed', width: 1 },
          label: {
            formatter: `порог ${props.cpuThreshold} %`,
            position: 'insideEndTop',
            color: c.latency,
            fontFamily: c.fontBody,
          },
          data: [{ yAxis: props.cpuThreshold }],
        },
      },
      {
        name: 'RAM',
        type: 'line',
        data: downsample(props.samples.map((s) => [s.t_s, s.ram_pct])),
        showSymbol: false,
        lineStyle: { color: c.ram, width: 1.5 },
        itemStyle: { color: c.ram },
      },
    ],
  }
})
</script>

<template>
  <section class="card chart-card" aria-labelledby="resources-title">
    <header class="head">
      <h2 id="resources-title">Ресурсы агента нагрузки</h2>
      <div class="legend muted">
        <span><i class="line cpu" />CPU</span>
        <span><i class="line ram" />RAM</span>
        <span v-if="agentName" class="mono">{{ agentName }}</span>
      </div>
    </header>
    <template v-if="samples.length">
      <p class="muted summary">
        CPU в среднем {{ formatNumber(avgCpu, 0) }} %, пик {{ formatNumber(peakCpu, 0) }} % · RAM пик
        {{ formatNumber(peakRam, 0) }} %
        <strong v-if="peakCpu > cpuThreshold" class="warn">· выше порога: упор мог быть в агент, а не в базу</strong>
      </p>
      <VChart class="chart" :option="option" autoresize aria-label="CPU и RAM агента во время теста" />
    </template>
    <p v-else class="muted empty">Замеров ресурсов агента нет.</p>
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

.line {
  display: inline-block;
  width: 14px;
  height: 3px;
  margin-right: 6px;
  border-radius: 2px;
  vertical-align: middle;
}

.line.cpu {
  background: var(--color-primary);
}

.line.ram {
  background: var(--color-cyan);
}

.summary {
  margin: 8px 0 0;
  font-size: 12px;
}

.warn {
  color: var(--color-orange-text);
}

.chart {
  height: 180px;
  margin-top: 8px;
}

.empty {
  margin: 16px 0 0;
}
</style>
