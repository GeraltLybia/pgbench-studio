<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/http'
import { runsApi } from '@/api/runs'
import PageHeader from '@/components/layout/PageHeader.vue'
import LiveChart from '@/components/run/LiveChart.vue'
import LogConsole from '@/components/run/LogConsole.vue'
import ResourcePanel from '@/components/run/ResourcePanel.vue'
import RunProgress from '@/components/run/RunProgress.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import KpiTile from '@/components/ui/KpiTile.vue'
import { formatCompact, formatNumber } from '@/composables/useFormat'
import { useRunSocket } from '@/composables/useRunSocket'
import { useActiveRunStore } from '@/stores/activeRun'
import { useAuthStore } from '@/stores/auth'
import { useRunStore } from '@/stores/run'
import { useSystemStore } from '@/stores/system'
import type { RunStatus } from '@/types/events'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const system = useSystemStore()
const activeRun = useActiveRunStore()

const runId = Number(route.params.id)
const run = useRunStore(runId)
const socket = useRunSocket(runId, { onMessage: (m) => run.apply(m) })

if (!system.info) void system.loadInfo().catch(() => undefined)

const STATUS: Record<RunStatus, string> = {
  queued: 'в очереди',
  running: 'выполняется',
  finalizing: 'обработка результатов',
  completed: 'завершён',
  failed: 'ошибка',
  cancelled: 'остановлен',
}

const status = computed(() => run.status?.status ?? null)
const running = computed(() => status.value === 'queued' || status.value === 'running')
const info = computed(() => run.info)

const subtitle = computed(() => {
  const parts = ['Шаг 3 из 4']
  if (info.value?.profile_name) parts.push(info.value.profile_name)
  return parts.join(' · ')
})

// --- KPI -----------------------------------------------------------------------------------

const avgTps = computed(() => {
  const p = run.progress
  return p.length ? p.reduce((s, x) => s + x.tps, 0) / p.length : null
})

const transactions = computed(() => {
  let total = 0
  let prev = 0
  for (const p of run.progress) {
    total += p.tps * Math.max(p.t - prev, 0)
    prev = p.t
  }
  return total
})

const projected = computed(() => {
  const i = info.value
  if (!i) return null
  if (i.mode === 'transactions' && i.clients && i.transactions) return i.clients * i.transactions
  return avgTps.value !== null && i.duration_s ? avgTps.value * i.duration_s : null
})

const failures = computed(() => ({
  failed: run.progress.reduce((s, p) => s + p.failed, 0),
  retried: run.progress.reduce((s, p) => s + p.retried, 0),
}))

// --- stop ----------------------------------------------------------------------------------

const stopping = ref(false)
const stopError = ref<string | null>(null)

async function stop(): Promise<void> {
  if (!window.confirm(`Остановить тест #${runId}? pgbench завершится не дольше чем за 10 секунд.`)) return
  stopError.value = null
  stopping.value = true
  try {
    await runsApi.cancel(runId)
  } catch (e) {
    stopError.value = e instanceof ApiError ? e.message : 'Не удалось остановить тест'
    stopping.value = false
  }
}

// Finished: the menu stops showing «идёт»; a completed test opens its report.
watch(status, (value) => {
  if (!value || running.value || value === 'finalizing') return
  activeRun.clear(runId)
  stopping.value = false
  if (value === 'completed' && info.value?.kind === 'bench') {
    void router.replace(`/runs/${runId}/report`)
  }
})
</script>

<template>
  <PageHeader :title="`Тест #${runId}`" :subtitle="subtitle">
    <template #actions>
      <span v-if="status" class="status" :class="status">
        <i v-if="running" class="pulse" />{{ STATUS[status] }}
      </span>
      <AppButton
        v-if="running && auth.can('runs.start')"
        variant="danger"
        :loading="stopping"
        @click="stop"
      >
        <AppIcon name="stop" :size="14" /> {{ stopping ? 'Останавливаем…' : 'Остановить' }}
      </AppButton>
    </template>
  </PageHeader>

  <p v-if="socket.state.value === 'reconnecting'" class="notice-warning" role="status">
    Соединение потеряно — переподключаемся…
  </p>
  <p v-if="stopError" class="notice-warning" role="alert">{{ stopError }}</p>
  <div v-if="status === 'failed' || status === 'cancelled'" class="notice-warning final" role="alert">
    <AppIcon name="alert" :size="16" class="notice-icon" />
    <div>
      <strong>{{ status === 'failed' ? 'Тест завершился с ошибкой' : 'Тест остановлен' }}</strong>
      <span v-if="run.status?.stopped_by"> пользователем {{ run.status.stopped_by }}</span>
      <div v-if="run.status?.error && status === 'failed'" class="mono err">{{ run.status.error }}</div>
      <div v-if="info?.kind === 'bench'">
        <RouterLink :to="`/runs/${runId}/report`">Открыть отчёт</RouterLink>
      </div>
    </div>
  </div>

  <div v-if="!run.status" class="card muted loading">Подключаемся к запуску…</div>

  <template v-else>
    <RunProgress :info="info" :last="run.last" :last-at="run.lastProgressAt" :finished="run.finished" />

    <div class="kpis">
      <KpiTile
        label="TPS сейчас"
        :value="run.last ? formatNumber(run.last.tps, 0) : '—'"
        :note="avgTps !== null ? `среднее за тест ${formatNumber(avgTps, 0)}` : undefined"
      />
      <KpiTile
        label="Latency"
        :value="run.last ? formatNumber(run.last.lat_ms, 2) : '—'"
        unit="мс"
        :note="run.last?.stddev_ms != null ? `stddev ${formatNumber(run.last.stddev_ms, 2)} мс` : undefined"
      />
      <KpiTile
        label="Транзакций"
        :value="formatNumber(transactions, 0)"
        :note="projected ? `≈ ${formatCompact(projected)} к концу` : undefined"
      />
      <KpiTile
        label="Ошибок"
        :value="formatNumber(failures.failed, 0)"
        :tone="failures.failed ? 'warn' : 'default'"
        :note="`failed / retried ${failures.retried}`"
      />
    </div>

    <ResourcePanel
      v-if="info?.kind === 'bench'"
      :samples="run.resources"
      :warnings="run.warnings"
      :agent-name="info.agent_name"
      :cpu-threshold="system.info?.cpu_warning_percent ?? 85"
    />
    <LiveChart
      v-if="info?.kind === 'bench'"
      :points="run.progress"
      :duration-s="info.mode === 'duration' ? (info.duration_s ?? null) : null"
    />
    <LogConsole :lines="run.log" :run-id="runId" />
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

.pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-cyan);
  animation: pulse 1.4s ease-in-out infinite;
}

@keyframes pulse {
  50% {
    opacity: 0.35;
  }
}

.final {
  margin-bottom: 20px;
}

.final .err {
  margin-top: 4px;
  font-size: 12px;
}

.loading {
  padding: 40px;
  text-align: center;
}

.kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin: 20px 0;
}

:deep(.resources),
:deep(.chart-card) {
  margin-bottom: 20px;
}

@media (max-width: 900px) {
  .kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
