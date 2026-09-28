<script setup lang="ts">
import '@/charts/echarts'
import type { EChartsOption } from 'echarts'
import { computed } from 'vue'
import VChart from 'vue-echarts'
import AppIcon from '@/components/ui/AppIcon.vue'
import { useChartColors } from '@/charts/theme'
import { formatNumber } from '@/composables/useFormat'
import type { ResourcesEvent, WarningEvent } from '@/types/events'

const props = defineProps<{
  samples: ResourcesEvent[]
  warnings: WarningEvent[]
  agentName: string
  cpuThreshold: number
}>()
const colors = useChartColors()
const GB = 1024 ** 3

const last = computed(() => props.samples.at(-1) ?? null)
const window = computed(() => props.samples.slice(-120))
const span = computed(() => {
  const w = window.value
  return w.length > 1 ? Math.round(w.at(-1)!.t - w[0]!.t) : 0
})

const option = computed<EChartsOption>(() => {
  const c = colors.value
  return {
    animation: false,
    grid: { left: 0, right: 0, top: 8, bottom: 8 },
    xAxis: { type: 'value', show: false, min: 'dataMin', max: 'dataMax' },
    yAxis: { type: 'value', min: 0, max: 100, show: false },
    tooltip: { trigger: 'axis', valueFormatter: (v) => `${formatNumber(Number(v), 0)} %` },
    series: [
      {
        name: 'CPU',
        type: 'line',
        data: window.value.map((s) => [s.t, s.cpu_pct]),
        showSymbol: false,
        lineStyle: { color: c.cpu, width: 2 },
        itemStyle: { color: c.cpu },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: c.latency, type: 'dashed', width: 1 },
          label: { show: false },
          data: [{ yAxis: props.cpuThreshold }],
        },
      },
      {
        name: 'RAM',
        type: 'line',
        data: window.value.map((s) => [s.t, s.ram_pct]),
        showSymbol: false,
        lineStyle: { color: c.ram, width: 2 },
        itemStyle: { color: c.ram },
      },
    ],
  }
})
</script>

<template>
  <section class="card resources" aria-labelledby="res-title">
    <header class="head">
      <h2 id="res-title">Ресурсы агента нагрузки</h2>
      <div class="legend muted">
        <span><i class="line cpu" />CPU</span>
        <span><i class="line ram" />RAM</span>
        <span>0–100 % · обновление 1 с</span>
      </div>
    </header>

    <div v-for="w in warnings.slice(-1)" :key="w.seq" class="notice-warning" role="alert">
      <AppIcon name="alert" :size="16" class="notice-icon" />
      <div>{{ w.message }}</div>
    </div>

    <div class="inner">
      <div class="agent-head">
        <span class="mono agent">{{ agentName }}</span>
        <span class="pill">агент pgbench</span>
        <span v-if="span" class="muted when">{{ span }} с назад → сейчас</span>
      </div>
      <div class="body">
        <div class="meters">
          <div class="meter">
            <div class="meter-row">
              <span class="muted">CPU</span>
              <strong class="big" :class="{ hot: (last?.cpu_pct ?? 0) > cpuThreshold }">
                {{ last ? formatNumber(last.cpu_pct, 0) : '—' }}%
              </strong>
            </div>
            <div class="track"><span class="cpu" :style="{ width: `${last?.cpu_pct ?? 0}%` }" /></div>
          </div>
          <div class="meter">
            <div class="meter-row">
              <span class="muted">RAM</span>
              <strong class="big">
                {{ last ? `${formatNumber(last.ram_used_bytes / GB, 1)} / ${formatNumber(last.ram_total_bytes / GB, 0)} ГБ` : '—' }}
              </strong>
            </div>
            <div class="track"><span class="ram" :style="{ width: `${last?.ram_pct ?? 0}%` }" /></div>
          </div>
        </div>
        <VChart v-if="samples.length > 1" class="chart" :option="option" autoresize aria-label="CPU и RAM агента" />
        <p v-else class="muted wait">Ждём первые замеры…</p>
      </div>
      <p class="muted note">
        Если CPU агента выше {{ cpuThreshold }} %, упор в генератор нагрузки, а не в базу, — покажем
        предупреждение.
      </p>
    </div>
  </section>
</template>

<style scoped>
.resources {
  display: grid;
  gap: 16px;
}

.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
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

.inner {
  border: 1px solid var(--color-border);
  border-radius: 16px;
  padding: 16px;
  display: grid;
  gap: 12px;
}

.agent-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.agent {
  font-weight: 600;
}

.pill {
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  background: var(--color-pill);
  color: var(--color-primary-deep);
  font-size: 12px;
}

.when {
  margin-left: auto;
  font-size: 12px;
}

.body {
  display: grid;
  grid-template-columns: minmax(160px, 200px) 1fr;
  gap: 24px;
  align-items: center;
}

.meters {
  display: grid;
  gap: 18px;
}

.meter-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 12px;
}

.big {
  font-family: var(--font-display);
  font-size: 18px;
}

.big.hot {
  color: var(--color-orange-text);
}

.track {
  height: 6px;
  margin-top: 6px;
  border-radius: var(--radius-pill);
  background: var(--color-pill);
  overflow: hidden;
}

.track span {
  display: block;
  height: 100%;
  transition: width 0.8s linear;
}

.track .cpu {
  background: var(--color-primary);
}

.track .ram {
  background: var(--color-cyan);
}

.chart {
  height: 150px;
}

.wait {
  margin: 0;
}

.note {
  margin: 0;
  font-size: 12px;
}

@media (max-width: 720px) {
  .body {
    grid-template-columns: 1fr;
  }
}
</style>
