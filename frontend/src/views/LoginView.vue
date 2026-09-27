<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/http'
import AuthLayout from '@/components/layout/AuthLayout.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import FieldInput from '@/components/ui/FieldInput.vue'
import { plural } from '@/composables/useFormat'
import { safeRedirect } from '@/router/guards'
import { useAuthStore } from '@/stores/auth'
import { fieldErrors, loginSchema, type FieldErrors } from '@/validation/password'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const form = reactive({ username: '', password: '' })
const errors = ref<FieldErrors<'username' | 'password'>>({})
const failure = ref<{ title: string; text: string } | null>(null)
const submitting = ref(false)
const credentialsInvalid = computed(() => failure.value !== null)

function describe(error: unknown): { title: string; text: string } {
  if (!(error instanceof ApiError)) {
    return { title: 'Не удалось войти', text: 'Повторите попытку позже.' }
  }
  if (error.code === 'invalid_credentials') {
    const left = Number(error.detail.attempts_left ?? 0)
    const minutes = Number(error.detail.lockout_min ?? 5)
    return {
      title: 'Неверный логин или пароль',
      text: `Осталось ${left} ${plural(left, ['попытка', 'попытки', 'попыток'])}, затем вход будет заблокирован на ${minutes} минут.`,
    }
  }
  if (error.code === 'login_locked') {
    const seconds = Number(error.detail.retry_after_s ?? 0)
    const minutes = Math.max(1, Math.ceil(seconds / 60))
    return {
      title: 'Вход временно заблокирован',
      text: `Слишком много неудачных попыток. Попробуйте через ${minutes} ${plural(minutes, ['минуту', 'минуты', 'минут'])}.`,
    }
  }
  return { title: 'Не удалось войти', text: error.message }
}

async function submit(): Promise<void> {
  const parsed = loginSchema.safeParse(form)
  if (!parsed.success) {
    errors.value = fieldErrors(parsed.error)
    return
  }
  errors.value = {}
  submitting.value = true
  try {
    const me = await auth.login(parsed.data.username, parsed.data.password)
    failure.value = null
    await router.replace(
      me.must_change_password ? { name: 'password' } : safeRedirect(route.query.redirect),
    )
  } catch (error) {
    failure.value = describe(error)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AuthLayout>
    <form class="card login" novalidate @submit.prevent="submit">
      <h1 class="title">Вход</h1>
      <p class="muted intro">Используйте учётную запись, выданную администратором.</p>

      <div v-if="failure" class="notice-warning" role="alert">
        <AppIcon name="alert" :size="16" class="notice-icon" />
        <div>
          <strong>{{ failure.title }}</strong>
          <div class="muted">{{ failure.text }}</div>
        </div>
      </div>

      <FieldInput
        v-model="form.username"
        label="Логин"
        autocomplete="username"
        :invalid="credentialsInvalid"
        :error="errors.username"
      />
      <FieldInput
        v-model="form.password"
        label="Пароль"
        type="password"
        autocomplete="current-password"
        :invalid="credentialsInvalid"
        :error="errors.password"
      />

      <AppButton type="submit" variant="primary" block :loading="submitting">Войти</AppButton>
      <p class="muted footnote">
        Нет доступа или забыли пароль? Обратитесь к администратору, он выдаст временный пароль.
      </p>
    </form>
  </AuthLayout>
</template>

<style scoped>
.login {
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

.footnote {
  margin: 0;
  font-size: 12px;
}
</style>
