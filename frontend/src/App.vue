<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import { useTheme } from '@/composables/useTheme'

const route = useRoute()
const bare = computed(() => route.meta.bare === true)
useTheme()
</script>

<template>
  <RouterView v-if="bare" />
  <div v-else class="shell">
    <AppSidebar />
    <main class="shell-main">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: 208px minmax(0, 1fr);
  min-height: 100vh;
}

.shell-main {
  padding: 28px 32px 48px;
  min-width: 0;
}
</style>
