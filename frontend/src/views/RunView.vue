<script setup lang="ts">
import { useIntervalFn } from '@vueuse/core'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError } from '@/api/http'
import { FINISHED_STATUSES, runsApi, type Run } from '@/api/runs'
import PageHeader from '@/components/layout/PageHeader.vue'
import { formatDateTime } from '@/composables/useFormat'

// Stage 2: status by polling. Live progress, charts and logs arrive in stage 3.
const POLL_MS = 2000

const route = useRoute()
const run = ref<Run | null>(null)
const error = ref<string | null>(null)
const id = computed(() => Number(route.params.id))

const STATUS: Record<Run['status'], string> = {
  queued: 'в очереди',
  running: 'выполняется',
  finalizing: 'обработка результатов',
  completed: 'завершён',
  failed: 'ошибка',
  cancelled: 'остановлен',
}

async function load(): Promise<void> {
  try {
    run.value = await runsApi.get(id.value)
    error.value = null
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить запуск'
  }
}

const { pause, resume } = useIntervalFn(() => void load(), POLL_MS, { immediate: false })
onMounted(async () => {
  await load()
  resume()
})
watch(id, () => void load())
watch(
  () => run.value?.status,
  (status) => {
    if (status && FINISHED_STATUSES.includes(status)) pause()
  },
)

const tail = computed(() => run.value?.log_tail.slice(-40).map((l) => l.line).join('\n') ?? '')
</script>

<template>
  <PageHeader :title="`Тест #${id}`" :subtitle="run ? `запустил ${run.started_by ?? '—'} · ${formatDateTime(run.started_at ?? run.created_at)}` : undefined">
    <template #actions>
      <span v-if="run" class="status" :class="run.status">{{ STATUS[run.status] }}</span>
    </template>
  </PageHeader>
  <p v-if="error" class="notice-warning" role="alert">{{ error }}</p>
  <section v-if="run" class="card body">
    <p class="muted note">
      Живой прогресс, графики и логи появятся на этапе 3. Сейчас экран обновляет статус раз в 2 с.
    </p>
    <dl>
      <div><dt>Команда</dt><dd class="mono">{{ run.argv.join(' ') }}</dd></div>
      <div v-if="run.error"><dt>Ошибка</dt><dd class="err">{{ run.error }}</dd></div>
      <div v-if="run.finished_at"><dt>Завершён</dt><dd>{{ formatDateTime(run.finished_at) }}</dd></div>
    </dl>
    <pre v-if="tail" class="log mono">{{ tail }}</pre>
  </section>
</template>

<style scoped>
.status {
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

.body {
  display: grid;
  gap: 16px;
}

.note {
  margin: 0;
  font-size: 12px;
}

dl {
  margin: 0;
  display: grid;
  gap: 10px;
}

dl > div {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 12px;
  font-size: 13px;
}

dt {
  color: var(--color-text-muted);
}

dd {
  margin: 0;
  word-break: break-word;
}

.err {
  color: var(--color-orange-text);
}

.log {
  margin: 0;
  max-height: 360px;
  overflow: auto;
  padding: 14px;
  border-radius: 14px;
  background: var(--color-code-bg);
  color: var(--color-code-text);
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
