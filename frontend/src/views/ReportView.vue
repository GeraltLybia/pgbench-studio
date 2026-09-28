<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/http'
import { runsApi, type Report, type RunStatus } from '@/api/runs'
import PageHeader from '@/components/layout/PageHeader.vue'
import ExportMenu from '@/components/report/ExportMenu.vue'
import LatencyBandChart from '@/components/report/LatencyBandChart.vue'
import LatencyHistogram from '@/components/report/LatencyHistogram.vue'
import RawOutput from '@/components/report/RawOutput.vue'
import RunParams from '@/components/report/RunParams.vue'
import StatementBars from '@/components/report/StatementBars.vue'
import TimeSeriesChart from '@/components/report/TimeSeriesChart.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import KpiTile from '@/components/ui/KpiTile.vue'
import { formatInt, formatLatency, formatNumber, formatTime } from '@/composables/useFormat'

const route = useRoute()
const router = useRouter()
const runId = Number(route.params.id)

const report = ref<Report | null>(null)
const error = ref<string | null>(null)

async function load(): Promise<void> {
  try {
    report.value = await runsApi.report(runId)
  } catch (e) {
    if (e instanceof ApiError && e.code === 'run_active') {
      // Still running: its live screen is where it is.
      await router.replace(`/runs/${runId}`)
      return
    }
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить отчёт'
  }
}
void load()

const run = computed(() => report.value?.run ?? null)
const summary = computed(() => run.value?.summary ?? null)
const pgbench = computed(() => (summary.value?.complete ? (summary.value.pgbench ?? null) : null))
const percentiles = computed(() => summary.value?.percentiles ?? null)
const isBench = computed(() => run.value?.kind === 'bench')

const STATUS: Partial<Record<RunStatus, string>> = {
  completed: 'завершён',
  failed: 'ошибка',
  cancelled: 'остановлен',
}

const FINISHED_AS: Partial<Record<RunStatus, string>> = {
  completed: 'завершён',
  failed: 'завершился с ошибкой',
  cancelled: 'остановлен',
}

function spell(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s} с`
  const m = Math.floor(s / 60)
  return s % 60 ? `${m} мин ${s % 60} с` : `${m} мин`
}

const subtitle = computed(() => {
  const r = run.value
  if (!r) return 'Шаг 4 из 4'
  const parts = ['Шаг 4 из 4']
  if (r.finished_at) {
    const date = new Date(r.finished_at).toLocaleDateString('ru-RU')
    parts.push(`${FINISHED_AS[r.status] ?? r.status} ${date} в ${formatTime(r.finished_at)}`)
  }
  if (r.started_at && r.finished_at) {
    const seconds = (new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000
    parts.push(`длительность ${spell(seconds)}`)
  }
  return parts.join(' · ')
})

// --- KPI -----------------------------------------------------------------------------------

// pgbench prints tps with %f and latencies with %.3f: toFixed restores the printed text.
const tps = computed(() => pgbench.value?.tps ?? null)
const latency = computed(() => pgbench.value?.latency_avg_ms ?? null)

const p9x = computed(() => {
  const p = percentiles.value
  return p?.p95 != null && p.p99 != null ? `${formatLatency(p.p95, 1)} / ${formatLatency(p.p99, 1)}` : '—'
})

const txNote = computed(() => {
  const s = pgbench.value
  if (!s) return undefined
  if (s.duration_s != null) return `за ${s.duration_s} с`
  if (s.processed_target != null) return `из ${formatInt(s.processed_target)}`
  return undefined
})

const failed = computed(() => pgbench.value?.failed ?? null)
const failedNote = computed(() => {
  const s = pgbench.value
  if (!s) return undefined
  return `${formatNumber(s.failed_pct ?? 0, 2)} % · retried ${formatInt(s.retried ?? 0)}`
})

// --- charts --------------------------------------------------------------------------------

const seriesNote = computed(() => {
  switch (summary.value?.series_source) {
    case 'transactions':
      return summary.value.sampling_rate
        ? `по логу транзакций, выборка ${summary.value.sampling_rate} · пунктир — среднее`
        : 'по логу транзакций, 1 с · пунктир — среднее'
    case 'progress':
      return 'по строкам progress: лог -l не записан · пунктир — среднее'
    default:
      return 'агрегация 1 с · пунктир — среднее'
  }
})

const meanTps = computed(() => {
  if (tps.value !== null) return tps.value
  const series = report.value?.series ?? []
  return series.length ? series.reduce((s, p) => s + p.tps, 0) / series.length : null
})
</script>

<template>
  <PageHeader :title="`Отчёт · тест #${runId}`" :subtitle="subtitle">
    <template #actions>
      <span v-if="run && STATUS[run.status]" class="status" :class="run.status">
        <AppIcon v-if="run.status === 'completed'" name="check" :size="12" />
        {{ STATUS[run.status] }}
      </span>
      <ExportMenu v-if="report" :run-id="runId" :files="report.files" />
    </template>
  </PageHeader>

  <p v-if="error" class="notice-warning" role="alert">{{ error }}</p>
  <div v-else-if="!report" class="card muted loading">Загружаем отчёт…</div>

  <template v-else-if="run">
    <div v-if="run.status !== 'completed' || !summary?.complete" class="notice-warning final" role="status">
      <AppIcon name="alert" :size="16" class="notice-icon" />
      <div>
        <strong v-if="run.status === 'cancelled'">
          Тест остановлен<span v-if="run.stopped_by"> пользователем {{ run.stopped_by }}</span>
        </strong>
        <strong v-else-if="run.status === 'failed'">Тест завершился с ошибкой</strong>
        <strong v-else>pgbench не вывел итог</strong>
        <div v-if="run.error && run.status === 'failed'" class="mono err">{{ run.error }}</div>
        <div v-if="isBench && !summary?.complete">
          Итоговых метрик pgbench нет: он печатает их только при штатном завершении.
          <template v-if="summary?.series_source === 'progress'">График построен по строкам progress.</template>
        </div>
        <div v-if="pgbench?.aborted">Часть клиентов прервана — pgbench пометил итог как неполный.</div>
      </div>
    </div>
    <p v-if="summary?.parse_error" class="notice-warning" role="status">{{ summary.parse_error }}</p>

    <template v-if="isBench">
      <div class="kpis">
        <KpiTile
          label="TPS"
          :value="tps !== null ? formatNumber(tps, 0) : '—'"
          tone="accent"
          note="без времени подключения"
          :title="tps !== null ? `tps = ${tps.toFixed(6)}` : undefined"
        />
        <KpiTile
          label="Latency avg"
          :value="latency !== null ? formatLatency(latency) : '—'"
          :unit="latency !== null ? 'мс' : undefined"
          tone="warn"
          :note="pgbench?.latency_stddev_ms != null ? `stddev ${formatLatency(pgbench.latency_stddev_ms)} мс` : undefined"
          :title="latency !== null ? `latency average = ${latency.toFixed(3)} ms` : undefined"
        />
        <KpiTile
          label="p95 / p99"
          :value="p9x"
          :unit="p9x !== '—' ? 'мс' : undefined"
          :note="percentiles ? 'по подробному логу' : 'в подробном режиме'"
        />
        <KpiTile
          label="Транзакций"
          :value="pgbench?.processed != null ? formatInt(pgbench.processed) : '—'"
          :note="txNote"
        />
        <KpiTile
          label="Ошибок"
          :value="failed !== null ? formatInt(failed) : '—'"
          :tone="failed ? 'warn' : 'default'"
          :note="failedNote"
        />
      </div>

      <TimeSeriesChart :series="report.series" :mean-tps="meanTps" :note="seriesNote" />
      <LatencyBandChart :series="report.series" />
      <StatementBars :statements="report.statements" />

      <div class="pair">
        <LatencyHistogram
          :buckets="report.histogram"
          :percentiles="percentiles"
          :sampled="summary?.sampling_rate != null"
        />
        <RunParams :run="run" :summary="summary?.pgbench ?? null" />
      </div>
    </template>

    <RawOutput :text="report.raw_output" :truncated="report.raw_output_truncated" />
  </template>
</template>

<style scoped>
.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  align-self: center;
  padding: 4px 12px;
  border-radius: var(--radius-pill);
  background: var(--color-pill);
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 600;
}

.status.failed,
.status.cancelled {
  background: var(--color-warning-bg);
  color: var(--color-orange-text);
}

.loading {
  padding: 40px;
  text-align: center;
}

.final {
  margin-bottom: 20px;
}

.final .err {
  margin-top: 4px;
  font-size: 12px;
}

.kpis {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.pair {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

:deep(.chart-card),
:deep(.statements),
.pair,
:deep(.raw) {
  margin-bottom: 20px;
}

@media (max-width: 1100px) {
  .kpis {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 800px) {
  .kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .pair {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
