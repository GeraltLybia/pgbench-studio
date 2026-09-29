<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <header class="page-header">
    <div>
      <div class="title-row">
        <h1>{{ title }}</h1>
        <!-- Status next to the title, as on the mockups («выполняется», «завершён»). -->
        <slot name="badge" />
      </div>
      <p v-if="subtitle" class="muted subtitle">{{ subtitle }}</p>
    </div>
    <div class="actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
}

.page-header > div:first-child {
  flex: 1 1 320px;
  min-width: 0;
}

.title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.subtitle {
  margin: 6px 0 0;
}

.actions {
  flex: 0 1 auto;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 12px;
}
</style>
