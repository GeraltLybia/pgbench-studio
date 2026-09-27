<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    type?: 'button' | 'submit'
    disabled?: boolean
    loading?: boolean
    block?: boolean
  }>(),
  { variant: 'secondary', type: 'button', disabled: false, loading: false, block: false },
)
</script>

<template>
  <button
    :type="type"
    class="btn"
    :class="[`btn-${variant}`, { 'btn-block': block }]"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
  >
    <slot />
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: var(--control-height);
  padding: 0 20px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition:
    background 0.15s,
    border-color 0.15s,
    opacity 0.15s;
}

.btn:disabled {
  cursor: not-allowed;
}

.btn-block {
  width: 100%;
}

.btn-primary {
  background: var(--color-primary);
  color: var(--color-on-primary);
}

.btn-primary:disabled {
  background: var(--color-disabled);
  color: var(--color-surface);
}

.btn-secondary {
  background: var(--color-surface);
  border-color: var(--color-border);
  color: var(--color-text);
}

.btn-secondary:hover:not(:disabled) {
  border-color: var(--color-primary);
}

.btn-ghost {
  background: transparent;
  color: var(--color-primary);
  padding: 0 8px;
}

.btn-danger {
  background: var(--color-surface);
  border-color: var(--color-orange);
  color: var(--color-orange-text);
}

.btn-secondary:disabled,
.btn-ghost:disabled,
.btn-danger:disabled {
  opacity: 0.5;
}
</style>
