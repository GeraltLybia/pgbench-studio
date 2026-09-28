<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError } from '@/api/http'
import { runsApi, type Compare } from '@/api/runs'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { diffText, diffTone, metricValue } from './compare'
import OverlayChart from './OverlayChart.vue'

const props = defineProps<{ a: number; b: number }>()

const data = ref<Compare | null>(null)
const error = ref<string | null>(null)

watch(
  () => [props.a, props.b],
  async ([a, b]) => {
    data.value = null
    error.value = null
    try {
      const result = await runsApi.compare(a!, b!)
      if (props.a === a && props.b === b) data.value = result
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : 'Не удалось сравнить запуски'
    }
  },
  { immediate: true },
)

const rows = computed(() => (data.value?.metrics ?? []).filter((m) => m.key === 'tps' || m.key === 'latency_avg_ms'))

const differences = computed(() => {
  const d = data.value
  if (!d) return ''
  const params = d.params.map((p) => (p.key.startsWith('body:') ? `${p.label.toLowerCase()} отличается` : `${p.label}: ${p.a ?? '—'} → ${p.b ?? '—'}`))
  const parts = [params.length ? params.join('; ') : 'параметры запуска совпадают']
  const notes = [d.a.run.note && `#${props.a}: ${d.a.run.note}`, d.b.run.note && `#${props.b}: ${d.b.run.note}`].filter(Boolean)
  if (notes.length) parts.push(notes.join('; '))
  return parts.join(' · ')
})
</script>

<template>
  <section class="card compare" aria-labelledby="compare-title">
    <header class="head">
      <h2 id="compare-title">Сравнение: #{{ a }} против #{{ b }}</h2>
      <RouterLink v-slot="{ navigate }" :to="`/compare?a=${a}&b=${b}`" custom>
        <AppButton variant="primary" @click="navigate"><AppIcon name="chart" :size="14" /> Открыть полное сравнение</AppButton>
      </RouterLink>
    </header>
    <p v-if="error" class="notice-warning" role="alert">{{ error }}</p>
    <p v-else-if="!data" class="muted">Загружаем…</p>
    <div v-else class="body">
      <OverlayChart :a="data.a.series" :b="data.b.series" :label-a="`#${a}`" :label-b="`#${b}`" />
      <table class="metrics">
        <thead>
          <tr>
            <th />
            <th class="a">#{{ a }}</th>
            <th class="b">#{{ b }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in rows" :key="m.key">
            <td class="muted">{{ m.label }}</td>
            <td class="mono">
              {{ metricValue(m, m.a) }}
              <span v-if="m.diff_pct !== null" class="diff" :class="diffTone(m)">{{ diffText(m.diff_pct) }}</span>
            </td>
            <td class="mono">{{ metricValue(m, m.b) }}</td>
          </tr>
          <tr>
            <td class="muted">Отличия</td>
            <td colspan="2" class="differences">{{ differences }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
}

.body {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(280px, 1fr);
  gap: 24px;
  align-items: center;
}

.metrics {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.metrics th,
.metrics td {
  padding: 10px 8px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
}

.metrics tr:last-child td {
  border-bottom: 0;
}

.a {
  color: var(--color-primary);
}

.b {
  color: var(--color-orange-text);
}

.diff {
  margin-left: 6px;
  font-weight: 600;
}

.diff.good {
  color: var(--color-primary);
}

.diff.bad {
  color: var(--color-orange-text);
}

.differences {
  font-size: 12px;
}

@media (max-width: 900px) {
  .body {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
