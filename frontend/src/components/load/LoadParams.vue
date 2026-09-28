<script setup lang="ts">
import { computed } from 'vue'
import FieldInput from '@/components/ui/FieldInput.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import SegmentedControl, { type SegmentOption } from '@/components/ui/SegmentedControl.vue'
import { useRunPlan } from '@/composables/useRunPlan'
import { useLoadConfigStore } from '@/stores/loadConfig'

const store = useLoadConfigStore()
const { limitFindings } = useRunPlan()

const modes: SegmentOption<'duration' | 'transactions'>[] = [
  { value: 'duration', label: 'По времени · -T' },
  { value: 'transactions', label: 'По транзакциям · -t' },
]
const protocols: SegmentOption<'simple' | 'extended' | 'prepared'>[] = [
  { value: 'simple', label: 'simple' },
  { value: 'extended', label: 'extended' },
  { value: 'prepared', label: 'prepared' },
]

/** Schema error first, then a limit finding for the same field. */
function fieldMessage(field: string): { text: string; level: 'error' | 'warning' } | null {
  const schema = store.paramErrors[field as keyof typeof store.paramErrors]
  if (schema) return { text: schema, level: 'error' }
  const finding = limitFindings.value.find((f) => f.field === field)
  return finding ? { text: finding.message, level: finding.level } : null
}

const messages = computed(() => ({
  duration_s: fieldMessage('duration_s'),
  transactions: fieldMessage('transactions'),
  clients: fieldMessage('clients'),
  threads: fieldMessage('threads'),
  rate_tps: fieldMessage('rate_tps'),
  latency_limit_ms: fieldMessage('latency_limit_ms'),
  sampling_rate: fieldMessage('sampling_rate'),
}))

function addVariable(): void {
  store.variables.push({ name: '', value: '' })
}
</script>

<template>
  <section class="card params" aria-labelledby="params-title">
    <h2 id="params-title">Параметры нагрузки</h2>

    <div>
      <span class="field-label">Режим завершения</span>
      <SegmentedControl v-model="store.params.mode" :options="modes" label="Режим завершения" />
      <p class="muted note">
        <template v-if="store.params.mode === 'duration'">
          В режиме по времени прогресс-бар показывает точное время окончания
        </template>
        <template v-else>В режиме по транзакциям прогресс и время окончания — оценка</template>
      </p>
    </div>

    <div class="row3">
      <FieldInput
        v-if="store.params.mode === 'duration'"
        v-model="store.params.duration_s"
        label="Длительность"
        suffix="сек"
        mono
        inputmode="numeric"
        :error="messages.duration_s?.level === 'error' ? messages.duration_s.text : null"
      />
      <FieldInput
        v-else
        v-model="store.params.transactions"
        label="Транзакций · -t"
        mono
        inputmode="numeric"
        :error="messages.transactions?.level === 'error' ? messages.transactions.text : null"
      />
      <FieldInput
        v-model="store.params.clients"
        label="Клиенты · -c"
        mono
        inputmode="numeric"
        :error="messages.clients?.level === 'error' ? messages.clients.text : null"
      />
      <FieldInput
        v-model="store.params.threads"
        label="Потоки · -j"
        mono
        inputmode="numeric"
        :error="messages.threads?.level === 'error' ? messages.threads.text : null"
      />
    </div>
    <template v-for="key in ['duration_s', 'clients'] as const" :key="key">
      <p v-if="messages[key]?.level === 'warning'" class="warn">
        <AppIcon name="alert" :size="14" /> {{ messages[key]!.text }} — потребуется подтверждение
      </p>
    </template>

    <div>
      <span class="field-label">Протокол · -M</span>
      <SegmentedControl v-model="store.params.protocol" :options="protocols" label="Протокол" />
    </div>

    <div class="row2">
      <FieldInput
        v-model="store.params.rate_tps"
        label="Ограничение TPS · -R"
        mono
        inputmode="numeric"
        hint="Пусто — без ограничения"
        :error="messages.rate_tps?.text"
      />
      <FieldInput
        v-model="store.params.latency_limit_ms"
        label="Latency limit"
        mono
        suffix="мс"
        inputmode="numeric"
        hint="Медленнее — считать пропуском"
        :error="messages.latency_limit_ms?.text"
      />
    </div>

    <details class="more">
      <summary>Дополнительно: vacuum, переменные -D, подробный лог для перцентилей</summary>
      <div class="more-body">
        <label class="check">
          <input v-model="store.params.vacuum" type="checkbox" />
          VACUUM таблиц pgbench перед тестом (без него — <code>-n</code>)
        </label>

        <div>
          <span class="field-label">Переменные · -D</span>
          <div v-for="(v, i) in store.variables" :key="i" class="var-row">
            <input v-model="v.name" class="field-input mono" placeholder="имя" aria-label="Имя переменной" />
            <span class="muted">=</span>
            <input v-model="v.value" class="field-input mono" placeholder="значение" aria-label="Значение переменной" />
            <button type="button" class="icon-btn" aria-label="Удалить переменную" @click="store.variables.splice(i, 1)">
              <AppIcon name="trash" :size="14" />
            </button>
            <p v-if="store.variableErrors[i]" class="warn var-error">{{ store.variableErrors[i] }}</p>
          </div>
          <button type="button" class="add" @click="addVariable">+ Переменная</button>
        </div>

        <label class="check">
          <input v-model="store.params.detailed_log" type="checkbox" />
          Подробный лог каждой транзакции — гистограмма и p50 / p95 / p99
        </label>
        <FieldInput
          v-if="store.params.detailed_log"
          v-model="store.params.sampling_rate"
          label="Доля транзакций в логе · --sampling-rate"
          mono
          hint="От 0 до 1; пусто — все транзакции"
          :error="messages.sampling_rate?.text"
        />
      </div>
    </details>
  </section>
</template>

<style scoped>
.params {
  display: grid;
  gap: 18px;
  align-content: start;
}

.note {
  margin: 8px 0 0;
  font-size: 12px;
}

.row3 {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.row2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.warn {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: -8px 0 0;
  color: var(--color-orange-text);
  font-size: 12px;
}

.more {
  border-top: 1px solid var(--color-border);
  padding-top: 14px;
}

.more summary {
  cursor: pointer;
  color: var(--color-primary);
  font-weight: 600;
  font-size: 13px;
}

.more-body {
  display: grid;
  gap: 14px;
  margin-top: 14px;
}

.check {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 13px;
}

.check input {
  margin-top: 3px;
  accent-color: var(--color-primary);
}

.var-row {
  display: grid;
  grid-template-columns: 1fr auto 1fr auto;
  gap: 6px;
  align-items: center;
  margin-bottom: 6px;
}

.var-row .field-input {
  height: 36px;
}

.var-error {
  grid-column: 1 / -1;
  margin: 0;
}

.icon-btn {
  border: 0;
  background: none;
  color: var(--color-text-muted);
  cursor: pointer;
}

.add {
  border: 0;
  background: none;
  color: var(--color-primary);
  cursor: pointer;
  padding: 0;
  font-weight: 600;
}
</style>
