<script setup lang="ts">
import { watchDebounced } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/http'
import { runsApi, type RunListItem } from '@/api/runs'
import CompareOverlay from '@/components/history/CompareOverlay.vue'
import RunsTable from '@/components/history/RunsTable.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { useAuthStore } from '@/stores/auth'
import { useProfilesStore } from '@/stores/profiles'

const PAGE = 20
const PERIODS = [
  { days: 7, label: 'Последние 7 дней' },
  { days: 30, label: 'Последние 30 дней' },
  { days: 90, label: 'Последние 90 дней' },
  { days: null, label: 'За всё время' },
] as const

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const profiles = useProfilesStore()
if (!profiles.loaded) void profiles.load().catch(() => undefined)

const q = ref('')
const profileId = ref<number | null>(null)
const days = ref<number | null>(30)
const items = ref<RunListItem[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref<string | null>(null)

// «Сравнить с…» from a report opens the history with that run already ticked.
const preselected = Number(route.query.with)
const selected = ref<number[]>(Number.isInteger(preselected) && preselected > 0 ? [preselected] : [])

let request = 0
async function load(append = false): Promise<void> {
  const id = ++request
  loading.value = true
  error.value = null
  try {
    const page = await runsApi.list({
      q: q.value,
      profile_id: profileId.value,
      days: days.value,
      limit: PAGE,
      offset: append ? items.value.length : 0,
    })
    if (id !== request) return
    items.value = append ? [...items.value, ...page.items] : page.items
    total.value = page.total
  } catch (e) {
    if (id === request) error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить историю'
  } finally {
    if (id === request) loading.value = false
  }
}

void load()
watch([profileId, days], () => void load())
watchDebounced(q, () => void load(), { debounce: 300 })

/** At most two: ticking a third one replaces the earliest pick. */
function toggle(id: number): void {
  const list = selected.value
  if (list.includes(id)) selected.value = list.filter((x) => x !== id)
  else selected.value = [...list, id].slice(-2)
}

// Older run on the right, as on the mockup (#128 против #127).
const pair = computed(() => {
  if (selected.value.length !== 2) return null
  const [x, y] = selected.value as [number, number]
  return x > y ? { a: x, b: y } : { a: y, b: x }
})
</script>

<template>
  <PageHeader title="История запусков" subtitle="Все тесты с параметрами и результатами · выберите два для сравнения">
    <template #actions>
      <AppButton v-if="auth.can('runs.start')" variant="primary" @click="router.push('/load')">
        <AppIcon name="plus" :size="14" /> Новый тест
      </AppButton>
    </template>
  </PageHeader>

  <section class="card list">
    <div class="filters">
      <input
        v-model="q"
        class="search"
        type="search"
        placeholder="Поиск по сценарию, профилю, номеру"
        aria-label="Поиск запусков"
      />
      <label class="chip-select">
        <span class="sr-only">Профиль</span>
        <select v-model="profileId" aria-label="Профиль">
          <option :value="null">Профиль: все</option>
          <option v-for="p in profiles.profiles" :key="p.id" :value="p.id">Профиль: {{ p.name }}</option>
        </select>
      </label>
      <label class="chip-select">
        <span class="sr-only">Период</span>
        <select v-model="days" aria-label="Период">
          <option v-for="p in PERIODS" :key="p.label" :value="p.days">{{ p.label }}</option>
        </select>
      </label>
    </div>

    <p v-if="error" class="notice-warning" role="alert">{{ error }}</p>
    <p v-else-if="!items.length && !loading" class="muted empty">
      {{ q || profileId !== null || days !== null ? 'Ничего не найдено — измените поиск или фильтры.' : 'Запусков пока нет.' }}
    </p>
    <RunsTable v-if="items.length" :items="items" :selected="selected" @toggle="toggle" />
    <div v-if="items.length < total" class="more">
      <AppButton :loading="loading" @click="load(true)">Показать ещё · {{ total - items.length }}</AppButton>
    </div>
  </section>

  <CompareOverlay v-if="pair" :a="pair.a" :b="pair.b" />
  <p v-else-if="selected.length === 1" class="muted hint">Отметьте ещё один запуск, чтобы сравнить с #{{ selected[0] }}.</p>
</template>

<style scoped>
.list {
  margin-bottom: 20px;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.search {
  flex: 0 1 340px;
  height: var(--control-height);
  padding: 0 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-field);
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
}

.chip-select select {
  appearance: none;
  padding: 6px 14px;
  border: 0;
  border-radius: var(--radius-pill);
  background: var(--color-pill);
  color: var(--color-primary);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.empty {
  padding: 24px 0;
}

.more {
  display: flex;
  justify-content: center;
  padding-top: 16px;
}

.hint {
  text-align: center;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
</style>
