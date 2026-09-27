<script setup lang="ts">
import { useRouter } from 'vue-router'
import AppIcon from '@/components/ui/AppIcon.vue'
import { ROLE_LABELS } from '@/auth/permissions'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

async function logout(): Promise<void> {
  await auth.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <div v-if="auth.user" class="user">
    <div class="who">
      <div class="name">{{ auth.user.username }}</div>
      <div class="muted role">{{ ROLE_LABELS[auth.user.role] }}</div>
    </div>
    <RouterLink to="/password" class="icon-btn" title="Сменить пароль" aria-label="Сменить пароль">
      <AppIcon name="key" :size="16" />
    </RouterLink>
    <button type="button" class="icon-btn" title="Выйти" aria-label="Выйти" @click="logout">
      <AppIcon name="logout" :size="16" />
    </button>
  </div>
</template>

<style scoped>
.user {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: 16px;
  background: var(--color-surface-muted);
}

.who {
  flex: 1;
  min-width: 0;
}

.name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
}

.role {
  font-size: 12px;
}

.icon-btn {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.icon-btn:hover {
  background: var(--color-pill);
  color: var(--color-primary);
}
</style>
