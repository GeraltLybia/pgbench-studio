<script setup lang="ts">
import { computed } from 'vue'
import type { PgbenchSummary, Run } from '@/api/runs'
import { formatNumber, formatTime } from '@/composables/useFormat'
import { loadArgs } from './analysis'

const props = defineProps<{ run: Run; summary: PgbenchSummary | null }>()

interface ScenarioRef {
  name: string
  weight?: number
}

const scenarios = computed(() => {
  const list = (props.run.config.run_config as { scenarios?: ScenarioRef[] } | undefined)?.scenarios ?? []
  return list.map((s) => `${s.name}@${s.weight ?? 1}`).join(', ') || '—'
})

const server = computed(() => {
  // «18.6 (Debian 18.6-1.pgdg13+2)» -> «PostgreSQL 18.6»
  const short = props.run.server_version?.split(' ')[0]
  const version = short ? `PostgreSQL ${short}` : null
  const profile = props.run.config.profile_name as string | undefined
  return [version, profile].filter(Boolean).join(' · ') || '—'
})

const rows = computed(() => {
  const s = props.summary
  const connection = s?.initial_connection_ms
  return [
    { label: 'Команда', value: loadArgs(props.run.argv) || '—' },
    { label: 'Сценарии', value: scenarios.value },
    { label: 'Scale', value: s?.scale != null ? String(s.scale) : '—' },
    { label: 'Сервер', value: server.value },
    { label: 'Старт / конец', value: `${formatTime(props.run.started_at)} – ${formatTime(props.run.finished_at)}` },
    {
      label: 'Initial connection',
      value: connection != null ? `${formatNumber(connection, 0)} мс` : '—',
      title: connection != null ? `initial connection time = ${connection.toFixed(3)} ms` : undefined,
    },
  ]
})
</script>

<template>
  <section class="card params" aria-labelledby="params-title">
    <h2 id="params-title">Параметры запуска</h2>
    <dl>
      <div v-for="row in rows" :key="row.label" class="row">
        <dt class="muted">{{ row.label }}</dt>
        <dd class="mono" :title="row.title">{{ row.value }}</dd>
      </div>
    </dl>
  </section>
</template>

<style scoped>
dl {
  margin: 16px 0 0;
}

.row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-border);
  font-size: 13px;
}

.row:last-child {
  border-bottom: 0;
}

dd {
  margin: 0;
  font-size: 12px;
  text-align: right;
  overflow-wrap: anywhere;
}
</style>
