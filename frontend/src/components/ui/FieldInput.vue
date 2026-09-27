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
    readonly?: boolean
    placeholder?: string
    suffix?: string
    inputmode?: 'text' | 'numeric'
    mono?: boolean
  }>(),
  {
    type: 'text',
    autocomplete: 'off',
    invalid: false,
    error: null,
    hint: '',
    disabled: false,
    readonly: false,
    placeholder: undefined,
    suffix: undefined,
    inputmode: 'text',
    mono: false,
  },
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
      <div class="input-wrap">
        <input
          :id="id"
          v-model="model"
          class="field-input"
          :class="{ invalid: invalid || !!error, mono, 'has-suffix': !!suffix }"
          :type="inputType"
          :autocomplete="autocomplete"
          :disabled="disabled"
          :readonly="readonly"
          :placeholder="placeholder"
          :inputmode="inputmode"
          :aria-invalid="invalid || !!error"
          :aria-describedby="error ? `${id}-error` : hint || $slots.hint ? `${id}-hint` : undefined"
        />
        <span v-if="suffix" class="suffix" aria-hidden="true">{{ suffix }}</span>
      </div>
      <button
        v-if="type === 'password' && !readonly"
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
    <p v-else-if="hint || $slots.hint" :id="`${id}-hint`" class="field-hint">
      <slot name="hint">{{ hint }}</slot>
    </p>
  </div>
</template>

<style scoped>
.field-row {
  display: flex;
  gap: 8px;
}

.input-wrap {
  position: relative;
  flex: 1;
}

.field-input.mono {
  font-family: var(--font-mono);
}

.field-input.has-suffix {
  padding-right: 48px;
}

.suffix {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
  font-size: 13px;
  pointer-events: none;
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
