<script setup lang="ts">
import { computed } from 'vue'
import type { Statement } from '@/api/runs'
import { formatInt, formatNumber, plural } from '@/composables/useFormat'

const props = defineProps<{ statements: Statement[] }>()

// Meta-commands (\set, \if …) run in the client and take microseconds: only SQL is shown.
const rows = computed(() => props.statements.filter((s) => !s.sql.startsWith('\\')))
const scripts = computed(() => [...new Set(rows.value.map((r) => r.script))])
const max = computed(() => Math.max(...rows.value.map((r) => r.latency_ms), 0))

const PALETTE = ['var(--color-primary)', 'var(--color-cyan)', 'var(--color-orange)', 'var(--color-yellow)', 'var(--color-primary-deep)']

function color(script: string): string {
  return PALETTE[scripts.value.indexOf(script) % PALETTE.length]!
}

function width(latency: number): string {
  return `${max.value > 0 ? Math.max((latency / max.value) * 100, 1) : 0}%`
}

function oneLine(sql: string): string {
  return sql.replace(/\s+/g, ' ').trim()
}
</script>

<template>
  <section class="card statements" aria-labelledby="statements-title">
    <header class="head">
      <h2 id="statements-title">Latency по запросам сценариев</h2>
      <span class="muted note">из ключа -r</span>
    </header>
    <p v-if="!rows.length" class="muted empty">pgbench не вывел таблицу -r.</p>
    <ul v-else class="rows">
      <li v-for="row in rows" :key="`${row.script}-${row.idx}`" class="row">
        <span class="script muted" :title="row.script">{{ row.script }}</span>
        <span class="sql mono" :title="row.sql">{{ oneLine(row.sql) }}</span>
        <span class="track" aria-hidden="true">
          <span class="fill" :style="{ width: width(row.latency_ms), background: color(row.script) }" />
        </span>
        <span class="value mono">
          {{ formatNumber(row.latency_ms, 3) }} мс
          <small v-if="row.failures" class="failures">
            {{ formatInt(row.failures) }} {{ plural(row.failures, ['ошибка', 'ошибки', 'ошибок']) }}
          </small>
        </span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 16px;
}

.note {
  font-size: 12px;
}

.rows {
  display: grid;
  gap: 10px;
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
}

.row {
  display: grid;
  grid-template-columns: minmax(80px, 110px) minmax(0, 1.4fr) minmax(0, 1fr) 112px;
  align-items: center;
  gap: 16px;
  font-size: 13px;
}

.script,
.sql {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.sql {
  font-size: 12px;
}

.track {
  height: 10px;
  border-radius: var(--radius-pill);
  background: var(--color-pill);
  overflow: hidden;
}

.fill {
  display: block;
  height: 100%;
  border-radius: var(--radius-pill);
}

.value {
  min-width: 72px;
  font-size: 12px;
  text-align: right;
  white-space: nowrap;
}

.failures {
  display: block;
  color: var(--color-orange-text);
}

.empty {
  margin: 16px 0 0;
}

@media (max-width: 700px) {
  .row {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .track {
    grid-column: 1 / -1;
  }
}
</style>
