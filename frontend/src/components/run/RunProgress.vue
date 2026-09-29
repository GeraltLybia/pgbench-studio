<script setup lang="ts">
import { computed } from 'vue'
import { formatLeft, formatTime } from '@/composables/useFormat'
import { useCountdown } from '@/composables/useCountdown'
import type { ProgressEvent, RunInfo } from '@/types/events'

const props = defineProps<{
  info: RunInfo | null
  last: ProgressEvent | null
  lastAt: number | null
  finished: boolean
}>()

const eta = computed(() => props.last?.eta_s ?? null)
const lastAt = computed(() => props.lastAt)
const { remaining, endsAt } = useCountdown(eta, lastAt)

const estimated = computed(() => props.info?.mode === 'transactions')
const pct = computed(() => (props.finished ? 100 : Math.floor(props.last?.pct ?? 0)))

const elapsedText = computed(() => {
  const info = props.info
  const t = Math.round(props.last?.t ?? 0)
  if (info?.mode === 'duration' && info.duration_s) return `${t} с из ${info.duration_s} с`
  if (info?.mode === 'transactions') return `${t} с · ${info.transactions} транзакций на клиента`
  return `${t} с`
})

const chips = computed(() => {
  const i = props.info
  if (!i) return []
  const scenarios = (i.scenarios ?? []).map((s) => `${s.name}@${s.weight}`).join(' + ')
  return [
    `-c ${i.clients} · -j ${i.threads}`,
    i.mode === 'duration' ? `-T ${i.duration_s}` : `-t ${i.transactions}`,
    `-M ${i.protocol}`,
    i.rate_tps ? `-R ${i.rate_tps}` : null,
    scenarios || null,
    i.started_at ? `старт ${formatTime(i.started_at)}` : null,
  ].filter(Boolean) as string[]
})
</script>

<template>
  <section class="card progress" aria-label="Прогресс теста">
    <div class="top">
      <div class="left">
        <span class="pct">{{ pct }}%</span>
        <span class="muted">{{ elapsedText }}</span>
      </div>
      <div v-if="!finished && remaining !== null" class="right">
        <strong>Осталось {{ formatLeft(remaining) }}</strong>
        <span class="muted">
          окончание {{ estimated ? '≈' : '≈' }} {{ endsAt ? formatTime(endsAt) : '—' }}
          <template v-if="estimated"> · оценка</template>
        </span>
      </div>
    </div>
    <div
      class="bar"
      role="progressbar"
      :aria-valuenow="pct"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-label="estimated ? 'Прогресс, оценка' : 'Прогресс'"
    >
      <span :style="{ width: `${pct}%` }" />
    </div>
    <ul class="chips">
      <li v-for="chip in chips" :key="chip">{{ chip }}</li>
    </ul>
  </section>
</template>

<style scoped>
.progress {
  display: grid;
  gap: 16px;
}

.top {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
}

.left {
  display: flex;
  align-items: baseline;
  gap: 14px;
}

.pct {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 44px;
  color: var(--color-primary);
  line-height: 1;
}

.right {
  display: grid;
  text-align: right;
  font-size: 13px;
}

.bar {
  height: 10px;
  border-radius: var(--radius-pill);
  background: var(--color-pill);
  overflow: hidden;
}

.bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-primary);
  transition: width 0.8s linear;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.chips li {
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  background: var(--color-pill);
  color: var(--color-primary-deep);
  font-size: 12px;
}
</style>
