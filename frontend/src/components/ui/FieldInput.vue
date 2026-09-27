<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import AppIcon from './AppIcon.vue'

const props = withDefaults(
  defineProps<{
    label: string
    type?: 'text' | 'password'
    autocomplete?: string
    invalid?: boolean
    error?: string | null
    hint?: string
    disabled?: boolean
  }>(),
  { type: 'text', autocomplete: 'off', invalid: false, error: null, hint: '', disabled: false },
)
const model = defineModel<string>({ required: true })

const id = useId()
const revealed = ref(false)
const inputType = computed(() =>
  props.type === 'password' && !revealed.value ? 'password' : 'text',
)
</script>

<template>
  <div class="field">
    <label :for="id" class="field-label">{{ label }}</label>
    <div class="field-row">
      <input
        :id="id"
        v-model="model"
        class="field-input"
        :class="{ invalid: invalid || !!error }"
        :type="inputType"
        :autocomplete="autocomplete"
        :disabled="disabled"
        :aria-invalid="invalid || !!error"
        :aria-describedby="error ? `${id}-error` : undefined"
      />
      <button
        v-if="type === 'password'"
        type="button"
        class="reveal"
        :aria-label="revealed ? 'Скрыть пароль' : 'Показать пароль'"
        :aria-pressed="revealed"
        @click="revealed = !revealed"
      >
        <AppIcon :name="revealed ? 'eyeOff' : 'eye'" />
      </button>
    </div>
    <p v-if="error" :id="`${id}-error`" class="field-error">{{ error }}</p>
    <p v-else-if="hint" class="field-hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.field-row {
  display: flex;
  gap: 8px;
}

.reveal {
  flex: none;
  width: var(--control-height);
  height: var(--control-height);
  display: grid;
  place-items: center;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-field);
  background: var(--color-surface);
  color: var(--color-text-muted);
  cursor: pointer;
}

.field-error {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--color-orange-text);
}

.field-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>
