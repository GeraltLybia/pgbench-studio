<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError } from '@/api/http'
import AuthLayout from '@/components/layout/AuthLayout.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import FieldInput from '@/components/ui/FieldInput.vue'
import { HOME } from '@/router/guards'
import { useAuthStore } from '@/stores/auth'
import {
  MIN_PASSWORD_LENGTH,
  fieldErrors,
  passwordChangeSchema,
  type FieldErrors,
} from '@/validation/password'

const auth = useAuthStore()
const router = useRouter()

const form = reactive({ current: '', next: '', repeat: '' })
const errors = ref<FieldErrors<'current' | 'next' | 'repeat'>>({})
const failure = ref<string | null>(null)
const submitting = ref(false)

async function submit(): Promise<void> {
  const parsed = passwordChangeSchema.safeParse(form)
  if (!parsed.success) {
    errors.value = fieldErrors(parsed.error)
    return
  }
  errors.value = {}
  failure.value = null
  submitting.value = true
  try {
    await auth.changePassword(parsed.data.current, parsed.data.next)
    await router.replace(HOME)
  } catch (error) {
    if (error instanceof ApiError && error.code === 'wrong_password') {
      errors.value = { current: error.message }
    } else {
      failure.value = error instanceof Error ? error.message : 'Не удалось сменить пароль'
    }
  } finally {
    submitting.value = false
  }
}

async function logout(): Promise<void> {
  await auth.logout()
  await router.replace({ name: 'login' })
}
</script>

<template>
  <AuthLayout>
    <form class="card form" novalidate @submit.prevent="submit">
      <h1 class="title">Смена пароля</h1>
      <p v-if="auth.mustChangePassword" class="muted intro">
        Вы вошли с временным паролем. Задайте свой, чтобы продолжить работу.
      </p>
      <p v-else class="muted intro">Пароль учётной записи {{ auth.user?.username }}.</p>

      <div v-if="failure" class="notice-warning" role="alert">
        <AppIcon name="alert" :size="16" class="notice-icon" />
        <div>{{ failure }}</div>
      </div>

      <FieldInput
        v-model="form.current"
        label="Текущий пароль"
        type="password"
        autocomplete="current-password"
        :error="errors.current"
      />
      <FieldInput
        v-model="form.next"
        label="Новый пароль"
        type="password"
        autocomplete="new-password"
        :error="errors.next"
        :hint="`Не короче ${MIN_PASSWORD_LENGTH} символов`"
      />
      <FieldInput
        v-model="form.repeat"
        label="Повторите новый пароль"
        type="password"
        autocomplete="new-password"
        :error="errors.repeat"
      />

      <AppButton type="submit" variant="primary" block :loading="submitting">
        Сохранить пароль
      </AppButton>
      <div class="links">
        <RouterLink v-if="!auth.mustChangePassword" :to="HOME">Отмена</RouterLink>
        <button type="button" class="link" @click="logout">Выйти</button>
      </div>
    </form>
  </AuthLayout>
</template>

<style scoped>
.form {
  display: grid;
  gap: 18px;
  width: min(366px, 100%);
  padding: 32px;
}

.title {
  font-size: 26px;
}

.intro {
  margin: -12px 0 0;
}

.links {
  display: flex;
  justify-content: center;
  gap: 24px;
  font-size: 13px;
}

.link {
  border: 0;
  background: none;
  color: var(--color-primary);
  cursor: pointer;
  padding: 0;
}
</style>
