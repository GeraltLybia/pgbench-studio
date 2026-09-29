<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError } from '@/api/http'
import { runsApi, type Compare } from '@/api/runs'
import { diffText, diffTone, metricValue } from '@/components/history/compare'
import OverlayChart from '@/components/history/OverlayChart.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import { formatDateTime } from '@/composables/useFormat'

const route = useRoute()
const a = Number(route.query.a)
const b = Number(route.query.b)
const valid = Number.isInteger(a) && Number.isInteger(b) && a > 0 && b > 0 && a !== b

const data = ref<Compare | null>(null)
const error = ref<string | null>(valid ? null : 'Выберите два разных запуска в истории')

if (valid) {
  runsApi
    .compare(a, b)
    .then((result) => (data.value = result))
    .catch((e: unknown) => (error.value = e instanceof ApiError ? e.message : 'Не удалось сравнить запуски'))
}

const hasLatency = computed(
  () => !!data.value && [...data.value.a.series, ...data.value.b.series].some((p) => p.lat_avg_ms !== null),
)

function runLine(side: 'a' | 'b'): string {
  const run = data.value?.[side].run
  if (!run) return ''
  const profile = (run.config.profile_name as string | undefined) ?? '—'
  return `${profile} · ${formatDateTime(run.started_at ?? run.created_at)}`
}
</script>

<template>
  <PageHeader :title="valid ? `Сравнение: #${a} против #${b}` : 'Сравнение'" subtitle="Разница — в процентах от второго запуска">
    <template #actions>
      <RouterLink class="back" to="/history">← История</RouterLink>
    </template>
  </PageHeader>

  <p v-if="error" class="notice-warning" role="alert">{{ error }}</p>
  <div v-else-if="!data" class="card muted loading">Загружаем сравнение…</div>

  <template v-else>
    <div class="pair">
      <section class="card side">
        <RouterLink class="id a" :to="`/runs/${a}/report`">#{{ a }}</RouterLink>
        <p class="muted">{{ runLine('a') }}</p>
        <p v-if="data.a.run.note" class="note">{{ data.a.run.note }}</p>
      </section>
      <section class="card side">
        <RouterLink class="id b" :to="`/runs/${b}/report`">#{{ b }}</RouterLink>
        <p class="muted">{{ runLine('b') }}</p>
        <p v-if="data.b.run.note" class="note">{{ data.b.run.note }}</p>
      </section>
    </div>

    <section class="card" aria-labelledby="metrics-title">
      <h2 id="metrics-title">Метрики</h2>
      <table class="grid">
        <thead>
          <tr>
            <th />
            <th class="a">#{{ a }}</th>
            <th class="b">#{{ b }}</th>
            <th>Разница</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in data.metrics" :key="m.key">
            <td class="muted">{{ m.label }}</td>
            <td class="mono">{{ metricValue(m, m.a) }}</td>
            <td class="mono">{{ metricValue(m, m.b) }}</td>
            <td class="mono diff" :class="diffTone(m)">{{ diffText(m.diff_pct) || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="card" aria-labelledby="tps-overlay">
      <header class="head">
        <h2 id="tps-overlay">Пропускная способность, TPS</h2>
        <div class="legend muted"><span><i class="line a-bg" />#{{ a }}</span><span><i class="line b-bg" />#{{ b }}</span></div>
      </header>
      <OverlayChart :a="data.a.series" :b="data.b.series" :label-a="`#${a}`" :label-b="`#${b}`" :height="260" />
    </section>

    <section v-if="hasLatency" class="card" aria-labelledby="lat-overlay">
      <header class="head">
        <h2 id="lat-overlay">Latency avg, мс</h2>
        <div class="legend muted"><span><i class="line a-bg" />#{{ a }}</span><span><i class="line b-bg" />#{{ b }}</span></div>
      </header>
      <OverlayChart
        :a="data.a.series"
        :b="data.b.series"
        :label-a="`#${a}`"
        :label-b="`#${b}`"
        metric="lat_avg_ms"
        :height="240"
      />
    </section>

    <section class="card" aria-labelledby="params-title">
      <h2 id="params-title">Отличия в параметрах</h2>
      <p v-if="!data.params.length" class="muted">Параметры запуска совпадают.</p>
      <table v-else class="grid">
        <thead>
          <tr>
            <th />
            <th class="a">#{{ a }}</th>
            <th class="b">#{{ b }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in data.params" :key="p.key">
            <td class="muted">{{ p.label }}</td>
            <td v-if="p.key.startsWith('body:')" class="mono" colspan="2">тексты сценария отличаются</td>
            <template v-else>
              <td class="mono">{{ p.a ?? '—' }}</td>
              <td class="mono">{{ p.b ?? '—' }}</td>
            </template>
          </tr>
        </tbody>
      </table>
    </section>
  </template>
</template>

<style scoped>
.back {
  align-self: center;
  color: var(--color-primary);
  font-weight: 600;
  text-decoration: none;
}

.loading {
  padding: 40px;
  text-align: center;
}

.pair {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
  margin-bottom: 20px;
}

.card + .card,
.pair + .card {
  margin-top: 20px;
}

.side p {
  margin: 6px 0 0;
  font-size: 13px;
}

.id {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  text-decoration: none;
}

.a {
  color: var(--color-primary);
}

.b {
  color: var(--color-orange-text);
}

.note {
  font-style: italic;
}

.grid {
  width: 100%;
  margin-top: 12px;
  border-collapse: collapse;
  font-size: 13px;
}

.grid th,
.grid td {
  padding: 10px 8px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
}

.grid tr:last-child td {
  border-bottom: 0;
}

.diff.good {
  color: var(--color-primary);
  font-weight: 600;
}

.diff.bad {
  color: var(--color-orange-text);
  font-weight: 600;
}

.head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
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

.a-bg {
  background: var(--color-primary);
}

.b-bg {
  background: var(--color-orange);
}

@media (max-width: 800px) {
  .pair {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
