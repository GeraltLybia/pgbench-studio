<script setup lang="ts">
import { watchDebounced } from '@vueuse/core'
import { computed, onMounted, ref } from 'vue'
import CommandPreview from '@/components/load/CommandPreview.vue'
import LoadParams from '@/components/load/LoadParams.vue'
import PreRunSummary from '@/components/load/PreRunSummary.vue'
import ScenarioList from '@/components/load/ScenarioList.vue'
import ScriptEditor from '@/components/load/ScriptEditor.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import { LINT_DELAY_MS } from '@/editor/lint'
import { useLoadConfigStore } from '@/stores/loadConfig'
import { useSystemStore } from '@/stores/system'

const store = useLoadConfigStore()
const system = useSystemStore()
const summaryOpen = ref(false)
const loadError = ref<string | null>(null)

onMounted(async () => {
  if (!system.info) void system.loadInfo().catch(() => undefined)
  if (!store.selected) {
    store.selected = store.scenarios.find((s) => s.kind === 'script')?.uid ?? store.scenarios[0]?.uid ?? null
  }
  try {
    await store.loadLibrary()
  } catch {
    loadError.value = 'Не удалось загрузить библиотеку сценариев'
  }
  void store.validateAll()
})

// Scripts that are not in the editor are checked too: the start button needs all of them.
watchDebounced(
  () => [store.context, store.scenarios.map((s) => (s.kind === 'script' ? s.body : s.name))],
  () => void store.validateAll(),
  { debounce: LINT_DELAY_MS, deep: true },
)

const selected = computed(() => store.selectedScenario)
const builtinBody = computed(() => {
  const s = selected.value
  return s?.kind === 'builtin' ? (store.builtins.find((b) => b.name === s.name)?.body ?? '') : ''
})
</script>

<template>
  <PageHeader
    title="Настройка нагрузки"
    subtitle="Шаг 2 из 4 · параметры pgbench и сценарии со взвешенным смешиванием"
  />
  <p v-if="loadError" class="notice-warning" role="alert">{{ loadError }}</p>

  <div class="layout">
    <LoadParams />
    <section class="card scenarios-card">
      <ScenarioList />
      <ScriptEditor v-if="selected?.kind === 'script'" :uid="selected.uid" />
      <div v-else-if="selected?.kind === 'builtin'" class="builtin">
        <header class="builtin-head">
          <span class="mono">{{ selected.name }}</span>
          <span class="muted">встроенный сценарий pgbench, только чтение</span>
        </header>
        <pre class="mono">{{ builtinBody || 'Загрузка…' }}</pre>
      </div>
    </section>
  </div>

  <CommandPreview class="command" @launch="summaryOpen = true" />
  <PreRunSummary v-if="summaryOpen" @close="summaryOpen = false" />
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: minmax(300px, 0.8fr) minmax(0, 1.5fr);
  gap: 20px;
  align-items: start;
}

.scenarios-card {
  min-width: 0;
}

.builtin {
  border: 1px solid var(--color-border);
  border-radius: 16px;
  overflow: hidden;
}

.builtin-head {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border);
  font-size: 13px;
}

.builtin pre {
  margin: 0;
  padding: 14px;
  font-size: 13px;
  line-height: 1.75;
  white-space: pre-wrap;
}

.command {
  margin-top: 20px;
}

@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
