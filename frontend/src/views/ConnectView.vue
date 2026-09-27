<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ConnectionCheck from '@/components/connect/ConnectionCheck.vue'
import InitPanel from '@/components/connect/InitPanel.vue'
import ProfileForm from '@/components/connect/ProfileForm.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import { useAuthStore } from '@/stores/auth'
import { useProfilesStore } from '@/stores/profiles'
import { useSystemStore } from '@/stores/system'

const store = useProfilesStore()
const auth = useAuthStore()
const system = useSystemStore()
const loadError = ref<string | null>(null)

onMounted(async () => {
  if (!system.info) void system.loadInfo().catch(() => undefined)
  try {
    await store.bootstrap(auth.can('connection.test'))
  } catch {
    loadError.value = 'Не удалось загрузить профили подключения'
  }
})
</script>

<template>
  <PageHeader
    title="Подключение к базе"
    subtitle="Шаг 1 из 4 · куда подаём нагрузку и в каком состоянии данные"
  />
  <p v-if="loadError" class="notice-warning" role="alert">{{ loadError }}</p>
  <div class="layout">
    <ProfileForm />
    <div class="side">
      <ConnectionCheck />
      <InitPanel />
    </div>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1.75fr) minmax(300px, 1fr);
  gap: 20px;
  align-items: start;
}

.side {
  display: grid;
  gap: 20px;
}

@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
