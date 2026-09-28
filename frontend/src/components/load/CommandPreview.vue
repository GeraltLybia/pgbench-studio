<script setup lang="ts">
import { refDebounced } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { ApiError } from '@/api/http'
import { runsApi, type CommandPreview } from '@/api/runs'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { useRunPlan } from '@/composables/useRunPlan'
import { useAuthStore } from '@/stores/auth'
import { useLoadConfigStore } from '@/stores/loadConfig'
import { useProfilesStore } from '@/stores/profiles'

const emit = defineEmits<{ launch: [] }>()

const store = useLoadConfigStore()
const profiles = useProfilesStore()
const auth = useAuthStore()
const { blockedReason } = useRunPlan()

const preview = ref<CommandPreview | null>(null)
const previewError = ref<string | null>(null)
const copied = ref(false)

const request = computed(() =>
  store.config && profiles.active ? { ...store.config, profile_id: profiles.active.id } : null,
)
const debounced = refDebounced(request, 300)

watch(
  debounced,
  async (config) => {
    if (!config || !auth.can('runs.start')) return
    try {
      preview.value = await runsApi.preview(config)
      previewError.value = null
    } catch (e) {
      previewError.value = e instanceof ApiError ? e.message : 'Не удалось собрать команду'
    }
  },
  { immediate: true, deep: true },
)

// Flags the agent always adds; shown dimmed as on the mockup.
const AUTO = /^(-P|-r|-l|--log-prefix=.*|--aggregate-interval=.*|--sampling-rate=.*)$/

function quote(arg: string): string {
  return /^[A-Za-z0-9_@%+=:,./-]+$/.test(arg) ? arg : `'${arg.replaceAll("'", "'\\''")}'`
}

const parts = computed(() => {
  const argv = preview.value?.argv ?? []
  const out: { text: string; auto: boolean }[] = []
  argv.forEach((arg, i) => {
    const prev = argv[i - 1]
    const auto = AUTO.test(arg) || (prev === '-P' && /^\d+$/.test(arg))
    out.push({ text: i === 0 ? 'pgbench' : quote(arg), auto })
  })
  return out
})

const envLine = computed(() =>
  preview.value
    ? Object.entries(preview.value.env)
        .map(([k, v]) => `${k}=${k === 'PGPASSWORD' ? v : quote(v)}`)
        .join(' ')
    : '',
)

async function copy(): Promise<void> {
  if (!preview.value) return
  await navigator.clipboard.writeText(preview.value.command)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}

const reason = computed(() => blockedReason.value ?? previewError.value)
</script>

<template>
  <section class="command" aria-labelledby="command-title">
    <div class="text">
      <h2 id="command-title" class="caption">Итоговая команда</h2>
      <p v-if="preview" class="argv mono">
        <span v-for="(p, i) in parts" :key="i" :class="{ auto: p.auto }">{{ (i ? ' ' : '') + p.text }}</span>
      </p>
      <p v-else class="argv mono auto">pgbench …</p>
      <p v-if="preview" class="env mono" title="Параметры подключения передаются через окружение">
        {{ envLine }}
      </p>
    </div>
    <button type="button" class="copy" :disabled="!preview" :aria-label="copied ? 'Скопировано' : 'Скопировать команду'" @click="copy">
      <AppIcon :name="copied ? 'check' : 'copy'" :size="16" />
    </button>
    <div class="launch">
      <AppButton variant="primary" :disabled="reason !== null || !auth.can('runs.start')" @click="emit('launch')">
        <AppIcon name="play" :size="14" /> Запустить тест
      </AppButton>
      <p v-if="reason" class="reason">{{ reason }}</p>
    </div>
  </section>
</template>

<style scoped>
.command {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 20px;
  padding: 20px 24px;
  border-radius: var(--radius-card);
  background: var(--color-code-bg);
  color: var(--color-code-text);
}

.caption {
  margin: 0 0 8px;
  font-family: var(--font-body);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-code-muted);
}

.argv {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  word-break: break-word;
}

.auto {
  color: var(--color-code-muted);
}

.env {
  margin: 6px 0 0;
  font-size: 11px;
  color: var(--color-code-muted);
  word-break: break-all;
}

.copy {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: 1px solid rgb(255 255 255 / 0.2);
  border-radius: 10px;
  background: transparent;
  color: var(--color-code-text);
  cursor: pointer;
}

.launch {
  display: grid;
  justify-items: center;
  gap: 6px;
  max-width: 240px;
}

.reason {
  margin: 0;
  color: #ffb48a;
  font-size: 12px;
  text-align: center;
}

@media (max-width: 900px) {
  .command {
    grid-template-columns: 1fr auto;
  }

  .launch {
    grid-column: 1 / -1;
    justify-items: stretch;
    max-width: none;
  }
}
</style>
