<script setup lang="ts">
import { useScroll } from '@vueuse/core'
import { computed, nextTick, ref, useTemplateRef, watch } from 'vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import type { LogEvent } from '@/types/events'
import { filterLog, isError, isProgress, type LogFilter } from './logFilter'

const props = defineProps<{ lines: LogEvent[]; runId: number }>()

// Fixed-height rows: only the visible window of up to 5000 lines is rendered.
const ROW = 20
const VIEW_ROWS = 18
const OVERSCAN = 10

const filter = ref<LogFilter>('all')
const autoscroll = ref(true)
const box = useTemplateRef<HTMLElement>('box')
const { y } = useScroll(box)

const visible = computed(() => filterLog(props.lines, filter.value))
const first = computed(() => Math.max(Math.floor(y.value / ROW) - OVERSCAN, 0))
const slice = computed(() => visible.value.slice(first.value, first.value + VIEW_ROWS + OVERSCAN * 2))

const FILTERS: { value: LogFilter; label: string }[] = [
  { value: 'all', label: 'Все' },
  { value: 'progress', label: 'Прогресс' },
  { value: 'errors', label: 'Ошибки' },
]

async function toBottom(): Promise<void> {
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
}

watch(
  () => [visible.value.length, filter.value],
  () => {
    if (autoscroll.value) void toBottom()
  },
  { immediate: true },
)

function download(): void {
  const text = props.lines.map((l) => l.line).join('\n') + '\n'
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `pgbench-run-${props.runId}.log`
  a.click()
  URL.revokeObjectURL(url)
}

function kind(line: LogEvent): string {
  if (isError(line)) return 'err'
  if (isProgress(line)) return 'prog'
  return ''
}
</script>

<template>
  <section class="console" aria-labelledby="log-title">
    <header class="head">
      <h2 id="log-title">Живые логи</h2>
      <div class="filters" role="tablist" aria-label="Фильтр логов">
        <button
          v-for="f in FILTERS"
          :key="f.value"
          type="button"
          role="tab"
          :aria-selected="filter === f.value"
          :class="{ active: filter === f.value }"
          @click="filter = f.value"
        >
          {{ f.label }}
        </button>
      </div>
      <label class="auto">
        <input v-model="autoscroll" type="checkbox" @change="autoscroll && toBottom()" />
        Автопрокрутка
      </label>
      <button type="button" class="dl" aria-label="Скачать лог" title="Скачать лог" @click="download">
        <AppIcon name="download" :size="16" />
      </button>
    </header>
    <div ref="box" class="box mono" tabindex="0" aria-live="off" :aria-label="`Лог запуска, строк: ${visible.length}`">
      <div :style="{ height: `${visible.length * ROW}px`, position: 'relative' }">
        <div
          v-for="(line, i) in slice"
          :key="first + i"
          class="row"
          :class="kind(line)"
          :style="{ top: `${(first + i) * ROW}px` }"
        >
          {{ line.line }}
        </div>
      </div>
      <p v-if="!visible.length" class="empty">{{ filter === 'errors' ? 'Ошибок нет' : 'Ждём вывод pgbench…' }}</p>
    </div>
  </section>
</template>

<style scoped>
.console {
  border-radius: var(--radius-card);
  background: var(--color-code-bg);
  color: var(--color-code-text);
  padding: 18px 20px;
}

.head {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.head h2 {
  font-size: 15px;
  color: var(--color-code-text);
}

.filters {
  display: flex;
  gap: 4px;
}

.filters button {
  border: 0;
  padding: 5px 12px;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--color-code-muted);
  cursor: pointer;
  font-size: 12px;
}

.filters button.active {
  background: rgb(255 255 255 / 0.12);
  color: var(--color-code-text);
}

.auto {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-code-muted);
}

.auto input {
  accent-color: var(--color-cyan);
}

.dl {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 1px solid rgb(255 255 255 / 0.2);
  border-radius: 8px;
  background: transparent;
  color: var(--color-code-text);
  cursor: pointer;
}

.box {
  position: relative;
  height: 360px;
  overflow: auto;
  font-size: 12px;
}

.row {
  position: absolute;
  left: 0;
  right: 0;
  height: 20px;
  line-height: 20px;
  white-space: pre;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row.prog {
  color: var(--color-code-text);
}

.row.err {
  color: #ffb48a;
}

.empty {
  margin: 0;
  color: var(--color-code-muted);
}
</style>
