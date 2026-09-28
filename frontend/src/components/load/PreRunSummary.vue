<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError } from '@/api/http'
import type { Finding } from '@/api/runs'
import { runsApi } from '@/api/runs'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { useRunPlan, type PlanItem } from '@/composables/useRunPlan'
import { useActiveRunStore } from '@/stores/activeRun'
import { useLoadConfigStore } from '@/stores/loadConfig'
import { useProfilesStore } from '@/stores/profiles'

const emit = defineEmits<{ close: [] }>()

const store = useLoadConfigStore()
const profiles = useProfilesStore()
const router = useRouter()
const activeRun = useActiveRunStore()
const { toConfirm, attention } = useRunPlan()

/** Items the server asked for that the form did not know about (e.g. fresh connection facts). */
const extra = ref<PlanItem[]>([])
const confirmed = reactive<Record<string, boolean>>({})
const starting = ref(false)
const error = ref<string | null>(null)

const items = computed(() => {
  const known = new Set(toConfirm.value.map((i) => i.ruleId))
  return [...toConfirm.value, ...extra.value.filter((i) => !known.has(i.ruleId))]
})
const allConfirmed = computed(() => items.value.every((i) => confirmed[i.ruleId]))

const check = computed(() => (profiles.result?.ok === true ? profiles.result : null))
const params = computed(() => (store.parsedParams.success ? store.parsedParams.data : null))

const loadLines = computed(() => {
  const p = params.value
  if (!p) return []
  return [
    p.mode === 'duration' ? `-T ${p.duration_s} с` : `-t ${p.transactions} на клиента`,
    `-c ${p.clients} · -j ${p.threads}`,
    `-M ${p.protocol}`,
    p.rate_tps !== null ? `-R ${p.rate_tps} TPS` : 'без ограничения TPS',
    p.latency_limit_ms !== null ? `latency limit ${p.latency_limit_ms} мс` : null,
    p.vacuum ? 'VACUUM перед тестом' : 'без VACUUM (-n)',
    p.detailed_log ? 'подробный лог' : null,
  ].filter(Boolean) as string[]
})

function label(level: PlanItem['level']): string {
  return level === 'danger' ? 'Опасно' : 'Предупреждение'
}

function fromFinding(f: Finding): PlanItem {
  return {
    ruleId: f.rule_id,
    level: f.level,
    message: f.message,
    scenario: f.scenario ?? undefined,
    line: f.line ?? undefined,
  }
}

async function start(): Promise<void> {
  if (!store.config || !profiles.active) return
  error.value = null
  starting.value = true
  try {
    const { run_id } = await runsApi.start({
      ...store.config,
      profile_id: profiles.active.id,
      confirmed_rules: items.value.map((i) => i.ruleId),
    })
    activeRun.set(run_id)
    emit('close')
    await router.push(`/runs/${run_id}`)
  } catch (e) {
    if (e instanceof ApiError && e.code === 'confirmation_required') {
      const findings = (e.detail.findings as Finding[] | undefined) ?? []
      const missing = new Set((e.detail.missing as string[] | undefined) ?? [])
      extra.value = findings.filter((f) => missing.has(f.rule_id)).map(fromFinding)
      error.value = 'Сервер нашёл ещё пункты, которые нужно подтвердить'
    } else {
      error.value = e instanceof ApiError ? e.message : 'Не удалось запустить тест'
    }
  } finally {
    starting.value = false
  }
}
</script>

<template>
  <div class="backdrop" @click.self="emit('close')" @keydown.esc="emit('close')">
    <section class="dialog card" role="dialog" aria-modal="true" aria-labelledby="summary-title">
      <h2 id="summary-title">Сводка перед запуском</h2>

      <dl class="grid">
        <div>
          <dt>База и сервер</dt>
          <dd>
            <strong>{{ profiles.active?.name }}</strong>
            <span class="muted mono">
              {{ profiles.active?.host }}:{{ profiles.active?.port }}/{{ profiles.active?.dbname }}
            </span>
            <span v-if="check" class="muted">PostgreSQL {{ check.server_version.split(' ')[0] }}</span>
          </dd>
        </div>
        <div>
          <dt>Нагрузка</dt>
          <dd><span v-for="line in loadLines" :key="line" class="mono">{{ line }}</span></dd>
        </div>
        <div>
          <dt>Сценарии</dt>
          <dd>
            <span v-for="s in store.scenarios" :key="s.uid" class="mono">
              {{ s.name }} @{{ s.weight }} · {{ store.share(s) }}%
            </span>
          </dd>
        </div>
      </dl>

      <div v-if="items.length" class="confirm">
        <h3>Нужно подтвердить</h3>
        <label v-for="item in items" :key="item.ruleId" class="item">
          <input v-model="confirmed[item.ruleId]" type="checkbox" />
          <span>
            <strong :class="item.level">{{ label(item.level) }}</strong>
            <template v-if="item.scenario"> · <span class="mono">{{ item.scenario }}:{{ item.line }}</span></template>
            — {{ item.message }}
          </span>
        </label>
        <p class="muted small">Подтверждения сохранятся в запуске вместе с вашим логином.</p>
      </div>

      <div v-if="attention.length" class="attention">
        <h3>Внимание</h3>
        <p v-for="item in attention" :key="item.ruleId" class="small">
          <span class="mono">{{ item.scenario }}:{{ item.line }}</span> — {{ item.message }}
        </p>
      </div>

      <p v-if="!items.length && !attention.length" class="muted">
        Предупреждений нет — можно запускать.
      </p>

      <p v-if="error" class="error" role="alert"><AppIcon name="alert" :size="14" /> {{ error }}</p>

      <div class="actions">
        <AppButton @click="emit('close')">Отмена</AppButton>
        <AppButton variant="primary" :disabled="!allConfirmed" :loading="starting" @click="start">
          <AppIcon name="play" :size="14" /> Запустить
        </AppButton>
      </div>
    </section>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgb(13 16 32 / 0.45);
}

.dialog {
  display: grid;
  gap: 18px;
  width: min(640px, 100%);
  max-height: calc(100vh - 32px);
  overflow: auto;
}

h3 {
  margin: 0 0 8px;
  font-size: 14px;
}

.grid {
  display: grid;
  gap: 12px;
  margin: 0;
}

.grid > div {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-border);
}

dt {
  color: var(--color-text-muted);
  font-size: 13px;
}

dd {
  margin: 0;
  display: grid;
  gap: 2px;
  font-size: 13px;
}

.confirm {
  padding: 14px 16px;
  border: 1px solid var(--color-warning-border);
  border-radius: var(--radius-field);
  background: var(--color-warning-bg);
}

.item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-bottom: 8px;
  font-size: 13px;
}

.item input {
  margin-top: 3px;
  accent-color: var(--color-orange);
}

.danger,
.warning {
  color: var(--color-orange-text);
}

.small {
  margin: 4px 0 0;
  font-size: 12px;
}

.error {
  margin: 0;
  display: flex;
  gap: 6px;
  align-items: center;
  color: var(--color-orange-text);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}
</style>
