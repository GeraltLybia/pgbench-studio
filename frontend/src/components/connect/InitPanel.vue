<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ApiError } from '@/api/http'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import ConfirmByTyping from '@/components/ui/ConfirmByTyping.vue'
import FieldInput from '@/components/ui/FieldInput.vue'
import { formatBytes, formatDuration } from '@/composables/useFormat'
import { useAuthStore } from '@/stores/auth'
import { useProfilesStore } from '@/stores/profiles'
import { useSystemStore } from '@/stores/system'
import { LARGE_INIT_BYTES, estimateInitBytes, initSchema, type InitForm } from '@/validation/init'
import { fieldErrors, type FieldErrors } from '@/validation/password'

const store = useProfilesStore()
const auth = useAuthStore()
const system = useSystemStore()

const form = reactive<InitForm>({ scale: '100', fillfactor: '100', foreign_keys: true, unlogged: false })
const errors = ref<FieldErrors<keyof InitForm>>({})
const confirming = ref(false)
const largeConfirmed = ref(false)
const starting = ref(false)
const failure = ref<string | null>(null)

const maxScale = computed(() => system.info?.limits.max_scale ?? 5000)
const parsed = computed(() => initSchema(maxScale.value).safeParse(form))
const estimate = computed(() =>
  parsed.value.success ? estimateInitBytes(parsed.value.data.scale, parsed.value.data.fillfactor) : null,
)
const large = computed(() => estimate.value !== null && estimate.value > LARGE_INIT_BYTES)
const dbname = computed(() => store.active?.dbname ?? store.form.dbname)

/** Initialisation needs a saved profile (the backend reads its password) and a passed check. */
const blockedReason = computed(() => {
  if (!auth.can('connection.test')) return 'Инициализация доступна ролям «Редактор» и «Администратор».'
  if (!store.active) return 'Сохраните профиль, чтобы инициализировать данные.'
  if (!store.connected) return 'Сначала успешно проверьте соединение.'
  if (store.initRunning) return 'Инициализация уже идёт.'
  return null
})

const run = computed(() => store.initRun)
const progress = computed(() => run.value?.progress ?? null)
const lastLines = computed(() => run.value?.log_tail.slice(-4) ?? [])

function open(): void {
  failure.value = null
  const result = initSchema(maxScale.value).safeParse(form)
  if (!result.success) {
    errors.value = fieldErrors(result.error)
    return
  }
  errors.value = {}
  if (large.value && !largeConfirmed.value) {
    failure.value = 'Оценка объёма больше 50 ГБ: отметьте подтверждение ниже.'
    return
  }
  confirming.value = true
}

async function start(): Promise<void> {
  const result = initSchema(maxScale.value).safeParse(form)
  if (!result.success) return
  starting.value = true
  try {
    await store.startInit({
      ...result.data,
      confirm_dbname: dbname.value,
      confirm_large: largeConfirmed.value,
    })
    confirming.value = false
  } catch (e) {
    confirming.value = false
    failure.value = e instanceof ApiError ? e.message : 'Не удалось запустить инициализацию'
  } finally {
    starting.value = false
  }
}
</script>

<template>
  <section class="card init" aria-labelledby="init-title">
    <header class="head">
      <h2 id="init-title">Инициализация данных</h2>
      <span class="pill mono">pgbench -i</span>
    </header>

    <div class="row">
      <div>
        <FieldInput
          v-model="form.scale"
          label="Scale factor (-s)"
          mono
          inputmode="numeric"
          :error="errors.scale"
          :disabled="store.initRunning"
        />
        <p v-if="estimate !== null && !errors.scale" class="muted estimate">
          ≈ {{ formatBytes(estimate) }} данных
        </p>
      </div>
      <FieldInput
        v-model="form.fillfactor"
        label="Fillfactor"
        mono
        suffix="%"
        inputmode="numeric"
        :error="errors.fillfactor"
        :disabled="store.initRunning"
      />
    </div>

    <div class="checks">
      <label><input v-model="form.foreign_keys" type="checkbox" :disabled="store.initRunning" /> Внешние ключи</label>
      <label><input v-model="form.unlogged" type="checkbox" :disabled="store.initRunning" /> Unlogged-таблицы</label>
    </div>

    <label v-if="large" class="large">
      <input v-model="largeConfirmed" type="checkbox" />
      Понимаю, что будет создано больше 50 ГБ данных
    </label>

    <div class="notice-warning">
      <AppIcon name="alert" :size="16" class="notice-icon" />
      <div>
        Удалит и пересоздаст таблицы <strong class="mono">pgbench_*</strong> в базе
        <strong>{{ dbname || '…' }}</strong>. Перед запуском попросим ввести имя базы для
        подтверждения.
      </div>
    </div>

    <div v-if="run" class="progress" :class="run.status" aria-live="polite">
      <div class="progress-head">
        <strong>
          <template v-if="store.initRunning">{{ progress?.phase ?? 'Запуск…' }}</template>
          <template v-else-if="run.status === 'completed'">Данные инициализированы</template>
          <template v-else>Инициализация не удалась</template>
        </strong>
        <span v-if="store.initRunning && progress?.pct != null" class="mono">
          {{ progress.pct }}%<template v-if="progress.remaining_s != null">
            · осталось {{ formatDuration(progress.remaining_s) }}</template>
        </span>
      </div>
      <div
        v-if="store.initRunning"
        class="bar"
        role="progressbar"
        :aria-valuenow="progress?.pct ?? 0"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <span :style="{ width: `${progress?.pct ?? 0}%` }" />
      </div>
      <p v-if="run.error" class="run-error">{{ run.error }}</p>
      <pre v-if="lastLines.length" class="log">{{ lastLines.map((l) => l.line).join('\n') }}</pre>
      <AppButton v-if="!store.initRunning" variant="ghost" @click="store.dismissInit()">Скрыть</AppButton>
    </div>

    <p v-if="failure" class="failure" role="alert">{{ failure }}</p>
    <p v-if="blockedReason && !store.initRunning" class="muted blocked">{{ blockedReason }}</p>

    <AppButton block :disabled="blockedReason !== null" :loading="starting" @click="open">
      <AppIcon name="database" :size="16" /> Инициализировать…
    </AppButton>

    <ConfirmByTyping
      v-if="confirming"
      title="Инициализировать данные?"
      :expected="dbname"
      confirm-label="Удалить и пересоздать"
      :busy="starting"
      @confirm="start"
      @cancel="confirming = false"
    >
      Таблицы <code>pgbench_*</code> в базе <strong>{{ dbname }}</strong> будут удалены и созданы
      заново со scale {{ form.scale }}.
    </ConfirmByTyping>
  </section>
</template>

<style scoped>
.init {
  display: grid;
  gap: 16px;
}

.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.head h2 {
  font-size: 16px;
}

.pill {
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  background: var(--color-pill);
  color: var(--color-primary-deep);
  font-size: 12px;
}

.row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.estimate {
  margin: 6px 0 0;
  font-size: 12px;
}

.checks {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}

.checks label,
.large {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.checks input,
.large input {
  width: 16px;
  height: 16px;
  accent-color: var(--color-primary);
}

.progress {
  display: grid;
  gap: 8px;
  padding: 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-field);
  font-size: 13px;
}

.progress.failed {
  border-color: var(--color-orange);
}

.progress-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.progress-head span {
  white-space: nowrap;
}

.bar {
  height: 8px;
  border-radius: var(--radius-pill);
  background: var(--color-pill);
  overflow: hidden;
}

.bar span {
  display: block;
  height: 100%;
  background: var(--color-primary);
  transition: width 0.4s;
}

.log {
  margin: 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--color-code-bg);
  color: var(--color-code-text);
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
}

.run-error,
.failure {
  margin: 0;
  color: var(--color-orange-text);
  font-size: 13px;
}

.blocked {
  margin: 0;
  font-size: 12px;
}
</style>
