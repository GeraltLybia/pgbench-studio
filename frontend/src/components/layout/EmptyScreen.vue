<script setup lang="ts">
import PageHeader from './PageHeader.vue'

defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <PageHeader :title="title" :subtitle="subtitle" />
  <section class="card empty">
    <p class="muted">Раздел пока пуст.</p>
  </section>
</template>

<style scoped>
.empty {
  display: grid;
  place-items: center;
  min-height: 240px;
}
</style>
