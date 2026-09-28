<script setup lang="ts">
import type { RunListItem, RunStatus } from '@/api/runs'
import { formatLatency, formatNumber } from '@/composables/useFormat'
import Sparkline from './Sparkline.vue'

defineProps<{ items: RunListItem[]; selected: number[] }>()
const emit = defineEmits<{ toggle: [id: number] }>()

const STATUS: Record<RunStatus, string> = {
  queued: 'в очереди',
  running: 'идёт',
  finalizing: 'обработка',
  completed: 'завершён',
  failed: 'ошибка',
  cancelled: 'остановлен',
}

const date = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit' })
const time = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' })

function when(value: string): [string, string] {
  const d = new Date(value)
  return [date.format(d), time.format(d)]
}

function scenarios(item: RunListItem): string {
  return item.scenarios.map((s) => s.replace(/@\d+$/, '').replace(/\.sql$/, '')).join(', ')
}

function length(item: RunListItem): string {
  if (item.mode === 'transactions') return item.transactions != null ? `-t ${item.transactions}` : '—'
  return item.duration_s != null ? `${item.duration_s} с` : '—'
}

function link(item: RunListItem): string {
  return ['queued', 'running', 'finalizing'].includes(item.status) ? `/runs/${item.id}` : `/runs/${item.id}/report`
}
</script>

<template>
  <div class="table-wrap">
    <table class="runs">
      <thead>
        <tr>
          <th class="check"><span class="sr-only">Выбрать для сравнения</span></th>
          <th>#</th>
          <th>Дата</th>
          <th>Профиль</th>
          <th>Сценарии</th>
          <th>-c / -j</th>
          <th>Длительность</th>
          <th class="num">TPS</th>
          <th class="num">Latency, мс</th>
          <th>Динамика</th>
          <th>Статус</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.id" :class="{ selected: selected.includes(item.id) }">
          <td class="check">
            <input
              type="checkbox"
              :checked="selected.includes(item.id)"
              :aria-label="`Сравнить тест #${item.id}`"
              @change="emit('toggle', item.id)"
            />
          </td>
          <td><RouterLink class="id" :to="link(item)">#{{ item.id }}</RouterLink></td>
          <td class="small">{{ when(item.created_at)[0] }}<br />{{ when(item.created_at)[1] }}</td>
          <td class="small">{{ item.profile_name ?? '—' }}</td>
          <td class="mono small" :title="item.scenarios.join(', ')">{{ scenarios(item) }}</td>
          <td class="mono small">{{ item.clients ?? '—' }} / {{ item.threads ?? '—' }}</td>
          <td class="small">{{ length(item) }}</td>
          <td class="num mono">{{ item.tps !== null ? formatNumber(item.tps, 0) : '—' }}</td>
          <td class="num mono">{{ item.latency_avg_ms !== null ? formatLatency(item.latency_avg_ms) : '—' }}</td>
          <td><Sparkline :values="item.sparkline" /></td>
          <td>
            <span class="chip" :class="item.status" :title="item.error ?? undefined">{{ STATUS[item.status] }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.table-wrap {
  overflow-x: auto;
}

.runs {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

th {
  padding: 12px 10px;
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 500;
  text-align: left;
  white-space: nowrap;
}

td {
  padding: 12px 10px;
  border-top: 1px solid var(--color-border);
  vertical-align: middle;
}

tr.selected td {
  background: var(--color-selected);
}

.check {
  width: 36px;
}

.check input {
  width: 16px;
  height: 16px;
  accent-color: var(--color-primary);
}

.id {
  color: var(--color-primary);
  font-family: var(--font-display);
  font-weight: 700;
  text-decoration: none;
}

.small {
  font-size: 12px;
}

.num {
  text-align: right;
  white-space: nowrap;
}

.chip {
  display: inline-block;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  background: var(--color-pill);
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.chip.failed {
  background: var(--color-warning-bg);
  color: var(--color-orange-text);
}

.chip.cancelled {
  background: var(--color-bg);
  color: var(--color-text-muted);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
</style>
