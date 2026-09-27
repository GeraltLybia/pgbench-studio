<script setup lang="ts">
import { computed } from 'vue'
import { useProfilesStore } from '@/stores/profiles'

const store = useProfilesStore()

const state = computed(() => {
  if (store.result?.ok === true) return 'ok'
  if (store.result?.ok === false) return 'fail'
  return 'unknown'
})

const version = computed(() => {
  const r = store.result
  if (r?.ok === true) return `PostgreSQL ${r.server_version.split(' ')[0]}`
  if (r?.ok === false) return 'нет соединения'
  return 'не проверено'
})
</script>

<template>
  <RouterLink v-if="store.active" to="/connect" class="conn" :title="`Текущее подключение: ${store.active.name}`">
    <span class="muted caption">Текущее подключение</span>
    <span class="name"><span class="dot" :class="state" aria-hidden="true" />{{ store.active.name }}</span>
    <span class="mono muted version">{{ version }}</span>
  </RouterLink>
</template>

<style scoped>
.conn {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: 16px;
  background: var(--color-surface-muted);
  color: var(--color-text);
  text-decoration: none;
}

.caption {
  font-size: 11px;
}

.name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 13px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.version {
  font-size: 11px;
}

.dot {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-disabled);
}

.dot.ok {
  background: var(--color-primary);
}

.dot.fail {
  background: var(--color-orange);
}
</style>
