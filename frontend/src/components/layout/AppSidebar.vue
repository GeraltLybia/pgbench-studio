<script setup lang="ts">
import { computed } from 'vue'
import AppIcon, { type IconName } from '@/components/ui/AppIcon.vue'
import { useAuthStore } from '@/stores/auth'
import SystemStatus from './SystemStatus.vue'
import ThemeToggle from './ThemeToggle.vue'
import UserMenu from './UserMenu.vue'

interface NavItem {
  label: string
  icon: IconName
  to?: string
  step?: number
  /** Shown instead of a link while the screen has nothing to open. */
  hint?: string
}

const auth = useAuthStore()

const steps: NavItem[] = [
  { label: 'Подключение', icon: 'plug', to: '/connect', step: 1 },
  { label: 'Нагрузка', icon: 'sliders', to: '/load', step: 2 },
  { label: 'Выполнение', icon: 'activity', step: 3, hint: 'Нет активного запуска' },
  { label: 'Отчёт', icon: 'chart', step: 4, hint: 'Нет завершённых запусков' },
]

const secondary = computed<NavItem[]>(() => [
  { label: 'История запусков', icon: 'clock', to: '/history' },
  ...(auth.can('users.manage')
    ? [{ label: 'Пользователи', icon: 'users' as const, to: '/admin/users' }]
    : []),
])
</script>

<template>
  <aside class="sidebar">
    <RouterLink to="/connect" class="logo">pgbench studio</RouterLink>

    <nav aria-label="Основное меню">
      <ul>
        <li v-for="item in steps" :key="item.label">
          <RouterLink v-if="item.to" :to="item.to" class="nav-item" active-class="active">
            <AppIcon :name="item.icon" />
            <span class="label">{{ item.label }}</span>
            <span class="step">{{ item.step }}</span>
          </RouterLink>
          <span v-else class="nav-item disabled" aria-disabled="true" :title="item.hint">
            <AppIcon :name="item.icon" />
            <span class="label">{{ item.label }}</span>
            <span class="step">{{ item.step }}</span>
          </span>
        </li>
      </ul>
      <hr />
      <ul>
        <li v-for="item in secondary" :key="item.label">
          <RouterLink :to="item.to!" class="nav-item" active-class="active">
            <AppIcon :name="item.icon" />
            <span class="label">{{ item.label }}</span>
          </RouterLink>
        </li>
      </ul>
    </nav>

    <div class="bottom">
      <SystemStatus />
      <UserMenu />
      <ThemeToggle />
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding: 22px 12px 16px;
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
}

.logo {
  margin: 0 8px 22px;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 15px;
  color: var(--color-text);
  text-decoration: none;
}

ul {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 4px;
}

hr {
  margin: 14px 12px;
  border: 0;
  border-top: 1px solid var(--color-border);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 40px;
  padding: 0 10px;
  white-space: nowrap;
  border-radius: var(--radius-field);
  color: var(--color-text);
  text-decoration: none;
  font-weight: 500;
}

.nav-item:hover:not(.disabled) {
  background: var(--color-selected);
}

.nav-item.active {
  background: var(--color-pill);
  color: var(--color-primary);
  font-weight: 600;
}

.nav-item.disabled {
  color: var(--color-text-muted);
  opacity: 0.6;
  cursor: default;
}

.label {
  flex: 1;
}

.step {
  font-size: 12px;
  color: var(--color-text-muted);
}

.active .step {
  color: var(--color-primary);
}

.bottom {
  display: grid;
  gap: 10px;
  margin-top: auto;
}
</style>
