<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ApiError } from '@/api/http'
import { usersApi, type User } from '@/api/users'
import { ROLE_LABELS, type Role } from '@/auth/permissions'
import PageHeader from '@/components/layout/PageHeader.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { formatDateTime, formatTime } from '@/composables/useFormat'
import { useAuthStore } from '@/stores/auth'
import { usernameSchema } from '@/validation/password'

const ROLES: Role[] = ['viewer', 'editor', 'admin']

const auth = useAuthStore()
const users = ref<User[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const busyId = ref<number | null>(null)
const issued = ref<{ username: string; password: string; reason: string } | null>(null)
const copied = ref(false)

const draft = reactive<{ username: string; role: Role }>({ username: '', role: 'viewer' })
const draftError = ref<string | null>(null)
const creating = ref(false)

function message(e: unknown): string {
  return e instanceof ApiError || e instanceof Error ? e.message : 'Неизвестная ошибка'
}

async function load(): Promise<void> {
  loading.value = true
  try {
    users.value = await usersApi.list()
    error.value = null
  } catch (e) {
    error.value = message(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function replace(user: User): void {
  users.value = users.value.map((u) => (u.id === user.id ? user : u))
}

async function create(): Promise<void> {
  const parsed = usernameSchema.safeParse(draft.username.trim())
  if (!parsed.success) {
    draftError.value = parsed.error.issues[0]?.message ?? 'Некорректный логин'
    return
  }
  draftError.value = null
  creating.value = true
  try {
    const result = await usersApi.create({ username: parsed.data, role: draft.role })
    users.value = [...users.value, result.user].sort((a, b) => a.username.localeCompare(b.username))
    showPassword(result.user.username, result.temporary_password, 'создан')
    draft.username = ''
    draft.role = 'viewer'
  } catch (e) {
    draftError.value = message(e)
  } finally {
    creating.value = false
  }
}

async function update(user: User, patch: { role?: Role; disabled?: boolean }): Promise<void> {
  busyId.value = user.id
  error.value = null
  try {
    replace(await usersApi.update(user.id, patch))
  } catch (e) {
    error.value = message(e)
    await load()
  } finally {
    busyId.value = null
  }
}

async function resetPassword(user: User): Promise<void> {
  if (!window.confirm(`Сбросить пароль пользователя ${user.username}? Его текущие сессии завершатся.`)) {
    return
  }
  busyId.value = user.id
  error.value = null
  try {
    const result = await usersApi.resetPassword(user.id)
    replace(result.user)
    showPassword(user.username, result.temporary_password, 'сброшен пароль')
  } catch (e) {
    error.value = message(e)
  } finally {
    busyId.value = null
  }
}

function showPassword(username: string, password: string, reason: string): void {
  issued.value = { username, password, reason }
  copied.value = false
}

async function copyPassword(): Promise<void> {
  if (!issued.value) return
  await navigator.clipboard.writeText(issued.value.password)
  copied.value = true
}

function isLocked(user: User): boolean {
  return user.locked_until !== null && new Date(user.locked_until) > new Date()
}

function onRoleChange(user: User, event: Event): void {
  void update(user, { role: (event.target as HTMLSelectElement).value as Role })
}
</script>

<template>
  <PageHeader title="Пользователи" subtitle="Учётные записи, роли и доступ к pgbench studio" />

  <div v-if="issued" class="card issued" role="status">
    <div>
      <strong>{{ issued.username }}: {{ issued.reason }}.</strong>
      <span class="muted">
        Передайте временный пароль пользователю — он показывается один раз, при входе система
        попросит его сменить.
      </span>
    </div>
    <div class="secret">
      <code>{{ issued.password }}</code>
      <AppButton @click="copyPassword">
        <AppIcon :name="copied ? 'check' : 'copy'" :size="16" />
        {{ copied ? 'Скопирован' : 'Скопировать' }}
      </AppButton>
      <AppButton variant="ghost" @click="issued = null">Скрыть</AppButton>
    </div>
  </div>

  <section class="card create">
    <h2>Новый пользователь</h2>
    <form class="create-form" novalidate @submit.prevent="create">
      <label class="grow">
        <span class="field-label">Логин</span>
        <input
          v-model="draft.username"
          aria-label="Логин"
          class="field-input"
          :class="{ invalid: draftError }"
          autocomplete="off"
        />
      </label>
      <label>
        <span class="field-label">Роль</span>
        <select v-model="draft.role" class="field-input">
          <option v-for="role in ROLES" :key="role" :value="role">{{ ROLE_LABELS[role] }}</option>
        </select>
      </label>
      <AppButton type="submit" variant="primary" :loading="creating">
        <AppIcon name="plus" :size="16" /> Создать
      </AppButton>
    </form>
    <p v-if="draftError" class="error">{{ draftError }}</p>
  </section>

  <section class="card">
    <div v-if="error" class="notice-warning" role="alert">
      <AppIcon name="alert" :size="16" class="notice-icon" />
      <div>{{ error }}</div>
    </div>
    <p v-if="loading && !users.length" class="muted">Загрузка…</p>
    <div v-else class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>Логин</th>
            <th>Роль</th>
            <th>Статус</th>
            <th>Последний вход</th>
            <th class="actions-col"><span class="visually-hidden">Действия</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id" :class="{ disabled: user.disabled }">
            <td>
              <span class="name">{{ user.username }}</span>
              <span v-if="user.id === auth.user?.id" class="muted you">это вы</span>
            </td>
            <td>
              <select
                class="field-input role-select"
                :value="user.role"
                :disabled="busyId === user.id || user.id === auth.user?.id"
                :aria-label="`Роль ${user.username}`"
                @change="onRoleChange(user, $event)"
              >
                <option v-for="role in ROLES" :key="role" :value="role">
                  {{ ROLE_LABELS[role] }}
                </option>
              </select>
            </td>
            <td>
              <span v-if="user.disabled" class="chip chip-warn">заблокирован</span>
              <span v-else-if="isLocked(user)" class="chip chip-warn">
                вход закрыт до {{ formatTime(user.locked_until) }}
              </span>
              <span v-else-if="user.must_change_password" class="chip">временный пароль</span>
              <span v-else class="chip">активен</span>
            </td>
            <td class="login-cell">
              {{ formatDateTime(user.last_login_at) }}
              <span v-if="user.last_login_ip" class="muted mono ip">{{ user.last_login_ip }}</span>
            </td>
            <td class="actions">
              <AppButton
                variant="ghost"
                :disabled="busyId === user.id"
                @click="resetPassword(user)"
              >
                Сбросить пароль
              </AppButton>
              <AppButton
                v-if="user.id !== auth.user?.id"
                variant="ghost"
                :disabled="busyId === user.id"
                @click="update(user, { disabled: !user.disabled })"
              >
                {{ user.disabled ? 'Разблокировать' : 'Заблокировать' }}
              </AppButton>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.card + .card {
  margin-top: 20px;
}

.issued {
  display: grid;
  gap: 12px;
  border-color: var(--color-primary);
}

.issued span {
  display: block;
  margin-top: 4px;
}

.secret {
  display: flex;
  align-items: center;
  gap: 12px;
}

.secret code {
  padding: 10px 14px;
  border-radius: var(--radius-field);
  background: var(--color-code-bg);
  color: var(--color-code-text);
  font-size: 15px;
  letter-spacing: 0.04em;
}

.create h2 {
  margin-bottom: 16px;
}

.create-form {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.grow {
  flex: 1 1 240px;
}

.create-form select {
  min-width: 180px;
}

.error {
  margin: 8px 0 0;
  color: var(--color-orange-text);
  font-size: 12px;
}

.table-wrap {
  overflow-x: auto;
}

.table {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
}

.table th {
  padding: 10px 12px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
  border-bottom: 1px solid var(--color-border);
}

.table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
  vertical-align: middle;
}

.table tr.disabled .name {
  color: var(--color-text-muted);
}

.name {
  font-weight: 600;
}

.you {
  margin-left: 8px;
  font-size: 12px;
}

.role-select {
  height: 36px;
  width: 170px;
}

.chip {
  display: inline-block;
  white-space: nowrap;
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  background: var(--color-pill);
  color: var(--color-primary-deep);
  font-size: 12px;
  font-weight: 600;
}

.chip-warn {
  background: var(--color-warning-bg);
  color: var(--color-orange-text);
}

.ip {
  display: block;
  font-size: 12px;
}

.actions {
  text-align: right;
  white-space: nowrap;
}
</style>
