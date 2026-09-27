<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId, useTemplateRef } from 'vue'
import AppButton from './AppButton.vue'

const props = defineProps<{
  title: string
  expected: string
  confirmLabel: string
  busy?: boolean
}>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()

const id = useId()
const typed = ref('')
const input = useTemplateRef<HTMLInputElement>('input')
const matches = computed(() => typed.value === props.expected)

onMounted(() => void nextTick(() => input.value?.focus()))

function submit(): void {
  if (matches.value && !props.busy) emit('confirm')
}
</script>

<template>
  <div class="backdrop" @click.self="emit('cancel')" @keydown.esc="emit('cancel')">
    <form
      class="dialog card"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="`${id}-title`"
      @submit.prevent="submit"
    >
      <h2 :id="`${id}-title`">{{ title }}</h2>
      <div class="body"><slot /></div>
      <label :for="id" class="field-label">
        Введите <code>{{ expected }}</code>, чтобы подтвердить
      </label>
      <input
        :id="id"
        ref="input"
        v-model="typed"
        class="field-input mono"
        :aria-label="`Введите ${expected}, чтобы подтвердить`"
        autocomplete="off"
        spellcheck="false"
      />
      <div class="actions">
        <AppButton @click="emit('cancel')">Отмена</AppButton>
        <AppButton type="submit" variant="primary" :disabled="!matches" :loading="busy">
          {{ confirmLabel }}
        </AppButton>
      </div>
    </form>
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
  gap: 14px;
  width: min(460px, 100%);
}

.body {
  color: var(--color-text-muted);
}

.mono {
  font-family: var(--font-mono);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}
</style>
