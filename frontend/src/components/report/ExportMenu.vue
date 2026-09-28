<script setup lang="ts">
import { onClickOutside } from '@vueuse/core'
import { ref, useTemplateRef } from 'vue'
import { runsApi, type RunFile } from '@/api/runs'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { formatBytes } from '@/composables/useFormat'

const props = defineProps<{ runId: number; files: RunFile[] }>()
const open = ref(false)
const root = useTemplateRef<HTMLElement>('root')
onClickOutside(root, () => (open.value = false))

const TITLES: Record<string, string> = {
  'stdout.log': 'stdout — итог pgbench',
  'stderr.log': 'stderr — прогресс и ошибки',
}

function title(name: string): string {
  if (TITLES[name]) return TITLES[name]
  if (name.startsWith('pgbench_log.')) return `лог -l · ${name}`
  return `сценарий · ${name}`
}
</script>

<template>
  <div ref="root" class="export">
    <AppButton :disabled="!props.files.length" :aria-expanded="open" aria-haspopup="menu" @click="open = !open">
      <AppIcon name="download" :size="14" /> Экспорт
    </AppButton>
    <ul v-if="open" class="menu card" role="menu">
      <li v-for="file in props.files" :key="file.name" role="none">
        <a role="menuitem" :href="runsApi.fileUrl(props.runId, file.name)" download @click="open = false">
          <span>{{ title(file.name) }}</span>
          <span class="muted size">{{ formatBytes(file.size_bytes) }}</span>
        </a>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.export {
  position: relative;
}

.menu {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  z-index: 20;
  min-width: 320px;
  max-height: 360px;
  overflow: auto;
  margin: 0;
  padding: 8px;
  list-style: none;
  border-radius: 16px;
  box-shadow: 0 12px 32px rgb(0 0 0 / 12%);
}

.menu a {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 12px;
  border-radius: 10px;
  color: var(--color-text);
  font-size: 13px;
  text-decoration: none;
}

.menu a:hover,
.menu a:focus-visible {
  background: var(--color-selected);
}

.size {
  font-size: 12px;
  white-space: nowrap;
}
</style>
