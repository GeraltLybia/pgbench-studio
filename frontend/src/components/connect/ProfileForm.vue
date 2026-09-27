<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError } from '@/api/http'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import FieldInput from '@/components/ui/FieldInput.vue'
import SegmentedControl, { type SegmentOption } from '@/components/ui/SegmentedControl.vue'
import { useAuthStore } from '@/stores/auth'
import { useProfilesStore } from '@/stores/profiles'
import { SSL_MODES } from '@/validation/profile'
import ProfileSelect from './ProfileSelect.vue'

const store = useProfilesStore()
const auth = useAuthStore()
const router = useRouter()

const canEdit = computed(() => auth.can('profiles.edit'))
const canTest = computed(() => auth.can('connection.test'))
const error = ref<string | null>(null)
const savedNote = ref(false)

const sslOptions: SegmentOption<(typeof SSL_MODES)[number]>[] = SSL_MODES.map((m) => ({
  value: m,
  label: m,
}))

const passwordPlaceholder = computed(() =>
  store.active?.has_password && !store.form.password ? 'пароль сохранён' : undefined,
)

function onSelect(id: number | null): void {
  error.value = null
  savedNote.value = false
  store.select(id)
}

async function check(): Promise<void> {
  error.value = null
  try {
    await store.runCheck()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось выполнить проверку'
  }
}

async function save(): Promise<void> {
  error.value = null
  savedNote.value = false
  try {
    if (await store.save()) savedNote.value = true
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось сохранить профиль'
  }
}

async function remove(): Promise<void> {
  if (!store.active) return
  if (!window.confirm(`Удалить профиль «${store.active.name}»?`)) return
  error.value = null
  try {
    await store.remove()
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось удалить профиль'
  }
}
</script>

<template>
  <section class="card form-card" aria-labelledby="conn-title">
    <header class="head">
      <h2 id="conn-title">Параметры подключения</h2>
      <ProfileSelect
        :profiles="store.profiles"
        :model-value="store.activeId"
        :can-create="canEdit"
        @update:model-value="onSelect"
      />
    </header>

    <form class="grid" novalidate @submit.prevent="check">
      <div class="span-3">
        <FieldInput
          v-model="store.form.host"
          label="Хост"
          mono
          :readonly="!canEdit"
          :error="store.errors.host"
        />
      </div>
      <FieldInput
        v-model="store.form.port"
        label="Порт"
        mono
        inputmode="numeric"
        :readonly="!canEdit"
        :error="store.errors.port"
      />
      <div class="span-2">
        <FieldInput
          v-model="store.form.dbname"
          label="База данных"
          mono
          :readonly="!canEdit"
          :error="store.errors.dbname"
        />
      </div>
      <div class="span-2">
        <FieldInput
          v-model="store.form.user"
          label="Пользователь"
          mono
          :readonly="!canEdit"
          :invalid="store.result?.ok === false && store.result.code === 'auth_failed'"
          :error="store.errors.user"
        />
      </div>
      <div class="span-4">
        <FieldInput
          v-if="canEdit"
          v-model="store.form.password"
          label="Пароль"
          type="password"
          autocomplete="new-password"
          :placeholder="passwordPlaceholder"
          :invalid="store.result?.ok === false && store.result.code === 'auth_failed'"
          :error="store.errors.password"
        >
          <template #hint>
            <AppIcon name="lock" :size="12" />
            Передаётся в pgbench через PGPASSWORD, не попадает в командную строку и логи
          </template>
        </FieldInput>
        <p v-else class="muted viewer-note">
          <AppIcon name="lock" :size="12" />
          Пароль {{ store.active?.has_password ? 'сохранён' : 'не сохранён' }} и не показывается
        </p>
      </div>
      <div class="span-4">
        <span class="field-label">SSL mode</span>
        <SegmentedControl
          v-if="canEdit"
          v-model="store.form.sslmode"
          :options="sslOptions"
          label="SSL mode"
        />
        <div v-else class="mono readonly-value">{{ store.form.sslmode }}</div>
      </div>
      <div class="span-2">
        <FieldInput
          v-model="store.form.app_name"
          label="application_name"
          mono
          :readonly="!canEdit"
          :error="store.errors.app_name"
          hint="Чтобы найти сессии теста в pg_stat_activity"
        />
      </div>
      <div class="span-2">
        <FieldInput
          v-model="store.form.connect_timeout_s"
          label="Таймаут подключения"
          mono
          suffix="сек"
          inputmode="numeric"
          :readonly="!canEdit"
          :error="store.errors.connect_timeout_s"
        />
      </div>

      <p v-if="error" class="span-4 error" role="alert">{{ error }}</p>

      <div class="span-4 actions">
        <AppButton v-if="canTest" type="submit" :loading="store.checking">
          <AppIcon name="refresh" :size="16" /> Проверить соединение
        </AppButton>
        <AppButton v-if="canEdit" variant="ghost" :loading="store.saving" @click="save">
          Сохранить профиль
        </AppButton>
        <span v-if="savedNote" class="muted saved" role="status">Сохранено</span>
        <AppButton v-if="canEdit && store.active" variant="ghost" class="danger-link" @click="remove">
          Удалить
        </AppButton>
        <AppButton
          variant="primary"
          class="next"
          :disabled="!store.connected"
          :title="store.connected ? undefined : 'Сначала успешно проверьте соединение'"
          @click="router.push('/load')"
        >
          Далее: нагрузка
        </AppButton>
      </div>
      <p v-if="!canTest" class="span-4 muted">
        Проверка соединения и переход к нагрузке доступны ролям «Редактор» и «Администратор».
      </p>
    </form>
  </section>
</template>

<style scoped>
.form-card {
  display: grid;
  gap: 20px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.span-2 {
  grid-column: span 2;
}

.span-3 {
  grid-column: span 3;
}

.span-4 {
  grid-column: span 4;
}

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.next {
  margin-left: auto;
}

.saved {
  font-size: 13px;
}

.danger-link {
  color: var(--color-orange-text);
}

.error {
  margin: 0;
  color: var(--color-orange-text);
}

.viewer-note,
.readonly-value {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: var(--control-height);
}

:deep(.field-hint) {
  display: flex;
  align-items: center;
  gap: 6px;
}

@media (max-width: 720px) {
  .grid > * {
    grid-column: span 4;
  }
}
</style>
