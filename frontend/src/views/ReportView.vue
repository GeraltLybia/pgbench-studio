<script setup lang="ts">
import { computed, nextTick, ref, useTemplateRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/http'
import { runsApi, type Report, type RunConfig, type RunStatus } from '@/api/runs'
import PageHeader from '@/components/layout/PageHeader.vue'
import ExportMenu from '@/components/report/ExportMenu.vue'
import LatencyBandChart from '@/components/report/LatencyBandChart.vue'
import LatencyHistogram from '@/components/report/LatencyHistogram.vue'
import RawOutput from '@/components/report/RawOutput.vue'
import ResourceChart from '@/components/report/ResourceChart.vue'
import RunParams from '@/components/report/RunParams.vue'
import StatementBars from '@/components/report/StatementBars.vue'
import TimeSeriesChart from '@/components/report/TimeSeriesChart.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import KpiTile from '@/components/ui/KpiTile.vue'
import { formatInt, formatLatency, formatNumber, formatTime } from '@/composables/useFormat'
import { useAuthStore } from '@/stores/auth'
import { useLoadConfigStore } from '@/stores/loadConfig'
import { useProfilesStore } from '@/stores/profiles'
import { useSystemStore } from '@/stores/system'

const route = useRoute()
const router = useRouter()
const runId = Number(route.params.id)
const auth = useAuthStore()
const system = useSystemStore()
if (!system.info) void system.loadInfo().catch(() => undefined)

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

// --- actions: repeat, delete, note --------------------------------------------------------

const runConfig = computed(() => (run.value?.config.run_config as RunConfig | undefined) ?? null)

/** «Повторить»: the same parameters and scenario texts on the load screen, same profile. */
async function repeat(): Promise<void> {
  const r = run.value
  if (!r || !runConfig.value) return
  useLoadConfigStore().applyRun(runConfig.value)
  const profiles = useProfilesStore()
  if (!profiles.loaded) await profiles.load().catch(() => undefined)
  // A deleted profile leaves the current one; the load screen then needs a checked connection.
  const exists = profiles.profiles.some((p) => p.id === r.profile_id)
  if (exists && r.profile_id !== profiles.activeId) profiles.select(r.profile_id)
  await router.push('/load')
}

const deleting = ref(false)
async function remove(): Promise<void> {
  if (!window.confirm(`Удалить тест #${runId} из истории вместе с логами? Это нельзя отменить.`)) return
  deleting.value = true
  try {
    await runsApi.remove(runId)
    await router.push('/history')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось удалить запуск'
    deleting.value = false
  }
}

const editingNote = ref(false)
const noteDraft = ref('')
const savingNote = ref(false)

const noteInput = useTemplateRef<HTMLInputElement>('noteInput')

async function editNote(): Promise<void> {
  noteDraft.value = run.value?.note ?? ''
  editingNote.value = true
  await nextTick()
  noteInput.value?.focus()
}

async function saveNote(): Promise<void> {
  savingNote.value = true
  try {
    const updated = await runsApi.setNote(runId, noteDraft.value.trim() || null)
    if (report.value) report.value.run.note = updated.note
    editingNote.value = false
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось сохранить заметку'
  } finally {
    savingNote.value = false
  }
}

const meanTps = computed(() => {
  if (tps.value !== null) return tps.value
  const series = report.value?.series ?? []
  return series.length ? series.reduce((s, p) => s + p.tps, 0) / series.length : null
})
</script>

<template>
  <PageHeader :title="`Отчёт · тест #${runId}`" :subtitle="subtitle">
    <template #badge>
      <span v-if="run && STATUS[run.status]" class="status" :class="run.status">
        <AppIcon v-if="run.status === 'completed'" name="check" :size="12" />
        {{ STATUS[run.status] }}
      </span>
    </template>
    <template #actions>
      <AppButton v-if="isBench" @click="router.push(`/history?with=${runId}`)">
        <AppIcon name="chart" :size="14" /> Сравнить с…
      </AppButton>
      <ExportMenu v-if="report" :run-id="runId" :files="report.files" />
      <AppButton v-if="isBench && runConfig && auth.can('runs.start')" variant="primary" @click="repeat">
        <AppIcon name="refresh" :size="14" /> Повторить
      </AppButton>
      <AppButton
        v-if="report && auth.can('runs.delete')"
        variant="ghost"
        :loading="deleting"
        aria-label="Удалить запуск"
        title="Удалить запуск"
        @click="remove"
      >
        <AppIcon name="trash" :size="14" />
      </AppButton>
    </template>
  </PageHeader>

  <div v-if="report" class="note-row">
    <template v-if="editingNote">
      <input
        ref="noteInput"
        v-model="noteDraft"
        class="note-input"
        maxlength="500"
        placeholder="Что изменилось перед этим прогоном: индекс, настройка, версия…"
        aria-label="Заметка к запуску"
        @keyup.enter="saveNote"
        @keyup.esc="editingNote = false"
      />
      <AppButton variant="primary" :loading="savingNote" @click="saveNote">Сохранить</AppButton>
      <AppButton variant="ghost" @click="editingNote = false">Отмена</AppButton>
    </template>
    <template v-else>
      <span v-if="report.run.note" class="note-text">Заметка: {{ report.run.note }}</span>
      <button v-if="auth.can('runs.note')" type="button" class="link" @click="editNote">
        {{ report.run.note ? 'Изменить' : '+ Заметка' }}
      </button>
    </template>
  </div>

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
      <!-- Runs before agent samples were stored have none: no empty card for them. -->
      <ResourceChart
        v-if="report.resources.length"
        :samples="report.resources"
        :cpu-threshold="system.info?.cpu_warning_percent ?? 85"
        :agent-name="system.info?.agent_name ?? null"
      />
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

.note-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: -12px 0 20px;
  font-size: 13px;
}

.note-input {
  flex: 1;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-field);
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
}

.link {
  border: 0;
  background: none;
  color: var(--color-primary);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
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
