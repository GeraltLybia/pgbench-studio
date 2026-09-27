<script setup lang="ts">
import { onClickOutside, useIntervalFn } from '@vueuse/core'
import { onMounted, ref, useTemplateRef } from 'vue'
import { formatTime } from '@/composables/useFormat'
import { INDICATOR_LABELS, useSystemStore } from '@/stores/system'

const HEALTH_POLL_MS = 30_000

const system = useSystemStore()
const open = ref(false)
const root = useTemplateRef<HTMLElement>('root')
onClickOutside(root, () => (open.value = false))

onMounted(() => void system.loadHealth())
useIntervalFn(() => void system.loadHealth(), HEALTH_POLL_MS)

async function toggle(): Promise<void> {
  open.value = !open.value
  if (open.value) await system.loadHealth()
}
</script>

<template>
  <div ref="root" class="status">
    <button
      type="button"
      class="status-button"
      :aria-expanded="open"
      aria-controls="system-checks"
      @click="toggle"
    >
      <span class="dot" :class="system.indicator" aria-hidden="true" />
      <span>{{ INDICATOR_LABELS[system.indicator] }}</span>
    </button>
    <div v-if="open" id="system-checks" class="popover card" role="dialog" aria-label="Проверки системы">
      <p v-if="system.healthError" class="muted">Не удалось получить состояние системы</p>
      <template v-else-if="system.health">
        <p class="checked muted">Проверено в {{ formatTime(system.health.checked_at) }}</p>
        <ul>
          <li v-for="check in system.health.checks" :key="check.name">
            <span class="dot" :class="check.status" aria-hidden="true" />
            <div class="check-body">
              <div class="check-title">
                {{ check.title }}
                <span v-if="!check.required" class="optional">необязательная</span>
              </div>
              <div class="muted check-message">
                {{ check.message }}
                <span v-if="check.value" class="mono"> · {{ check.value }}</span>
                <span v-if="check.threshold" class="mono"> · порог {{ check.threshold }}</span>
              </div>
            </div>
          </li>
        </ul>
      </template>
      <p v-else class="muted">Загрузка…</p>
    </div>
  </div>
</template>

<style scoped>
.status {
  position: relative;
}

.status-button {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: var(--radius-field);
  background: transparent;
  color: var(--color-text-muted);
  font-size: 13px;
  cursor: pointer;
  text-align: left;
}

.status-button:hover {
  background: var(--color-pill);
}

.dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-disabled);
}

.dot.ok {
  background: var(--color-primary);
}

.dot.warning {
  background: var(--color-yellow);
}

.dot.fail {
  background: var(--color-orange);
}

.popover {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  z-index: 20;
  width: 360px;
  padding: 16px;
  border-radius: 16px;
  box-shadow: 0 12px 32px rgb(20 20 26 / 0.14);
}

.checked {
  margin: 0 0 10px;
  font-size: 12px;
}

ul {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

li {
  display: flex;
  gap: 10px;
  align-items: baseline;
}

.check-title {
  font-weight: 600;
}

.optional {
  margin-left: 6px;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-text-muted);
}

.check-message {
  font-size: 12px;
}
</style>
