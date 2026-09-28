<script setup lang="ts">
defineProps<{ label: string; value: string; unit?: string; note?: string; tone?: 'default' | 'accent' | 'warn' }>()
</script>

<template>
  <div class="kpi card">
    <span class="label muted">{{ label }}</span>
    <span class="value" :class="tone ?? 'default'">
      {{ value }}<small v-if="unit" class="unit">{{ unit }}</small>
    </span>
    <span v-if="note" class="note muted">{{ note }}</span>
  </div>
</template>

<style scoped>
.kpi {
  display: grid;
  gap: 6px;
  padding: 18px 20px;
  border-radius: 20px;
}

.label,
.note {
  font-size: 12px;
}

.value {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 28px;
  line-height: 1.1;
}

.value.accent {
  color: var(--color-primary);
}

.value.warn {
  color: var(--color-orange-text);
}

.unit {
  margin-left: 6px;
  font-family: var(--font-body);
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted);
}
</style>
