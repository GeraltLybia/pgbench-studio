<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '@/components/ui/AppIcon.vue'

const props = defineProps<{ text: string; truncated: boolean }>()
const copied = ref(false)

async function copy(): Promise<void> {
  await navigator.clipboard.writeText(props.text)
  copied.value = true
  window.setTimeout(() => (copied.value = false), 2000)
}
</script>

<template>
  <section class="card raw" aria-labelledby="raw-title">
    <header class="head">
      <h2 id="raw-title">Сырой вывод pgbench</h2>
      <button v-if="text" type="button" class="copy" @click="copy">
        <AppIcon :name="copied ? 'check' : 'copy'" :size="14" />
        {{ copied ? 'Скопировано' : 'Скопировать' }}
      </button>
    </header>
    <pre v-if="text" class="output mono">{{ text }}</pre>
    <p v-else class="muted empty">pgbench ничего не вывел в stdout.</p>
    <p v-if="truncated" class="muted note">Показано начало вывода; полный файл — в «Экспорт».</p>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.copy {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 0;
  background: none;
  color: var(--color-primary);
  font: inherit;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
}

.output {
  margin: 16px 0 0;
  padding: 20px;
  max-height: 480px;
  overflow: auto;
  border-radius: 16px;
  background: var(--color-code-bg);
  color: var(--color-code-text);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre;
}

.note,
.empty {
  margin: 12px 0 0;
  font-size: 12px;
}
</style>
