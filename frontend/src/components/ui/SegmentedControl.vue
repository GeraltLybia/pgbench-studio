<script setup lang="ts" generic="T extends string">
import AppIcon, { type IconName } from './AppIcon.vue'

export interface SegmentOption<V extends string> {
  value: V
  label: string
  icon?: IconName
}

defineProps<{ options: SegmentOption<T>[]; label: string; size?: 'md' | 'sm' }>()
const model = defineModel<T>({ required: true })
</script>

<template>
  <div class="segmented" :class="size ?? 'md'" role="radiogroup" :aria-label="label">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      role="radio"
      class="segment"
      :class="{ active: model === option.value }"
      :aria-checked="model === option.value"
      @click="model = option.value"
    >
      <AppIcon v-if="option.icon" :name="option.icon" :size="14" />
      {{ option.label }}
    </button>
  </div>
</template>

<style scoped>
.segmented {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: var(--color-pill);
  border-radius: var(--radius-field);
}

.segment {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 12px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.sm .segment {
  height: 30px;
  font-size: 12px;
}

.segment.active {
  background: var(--color-surface);
  color: var(--color-primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgb(20 20 26 / 0.06);
}

:global([data-theme='dark']) .segment.active {
  background: var(--color-bg);
}
</style>
