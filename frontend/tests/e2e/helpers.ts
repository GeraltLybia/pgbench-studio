import { expect, request, type APIRequestContext, type Page } from '@playwright/test'
import { env } from './env'

/** An API client logged in as the bootstrap admin (only for setting up users). */
export async function adminApi(baseURL: string): Promise<APIRequestContext> {
  const api = await request.newContext({ baseURL })
  const resp = await api.post('/api/auth/login', {
    data: { username: env.adminUser, password: env.adminPassword },
  })
  expect(resp.status(), await resp.text()).toBe(200)
  return api
}

/** A new user with a server-issued temporary password (shown once, as in the UI). */
export async function createUser(
  api: APIRequestContext,
  role: 'viewer' | 'editor',
): Promise<{ username: string; temporary: string }> {
  const username = `e2e-${role}-${Date.now().toString(36)}`
  const resp = await api.post('/api/users', { data: { username, role } })
  expect(resp.status(), await resp.text()).toBe(201)
  const body = (await resp.json()) as { temporary_password: string }
  return { username, temporary: body.temporary_password }
}

/** First login with a temporary password: the app requires a new one before anything else. */
export async function firstLogin(page: Page, username: string, temporary: string): Promise<string> {
  const password = `E2e-${Date.now().toString(36)}-pass`
  await page.goto('/login')
  await page.getByLabel('Логин').fill(username)
  await page.getByLabel('Пароль', { exact: true }).fill(temporary)
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page).toHaveURL(/\/password$/)
  await page.getByLabel('Текущий пароль').fill(temporary)
  await page.getByLabel('Новый пароль', { exact: true }).fill(password)
  await page.getByLabel('Повторите новый пароль').fill(password)
  await page.getByRole('button', { name: 'Сохранить пароль' }).click()
  await expect(page).not.toHaveURL(/\/password$/)
  return password
}

/** Waits for a run started from the load screen to finish and open its report. */
export async function waitForReport(page: Page, seconds: number): Promise<number> {
  await expect(page).toHaveURL(/\/runs\/\d+$/)
  const id = Number(/\/runs\/(\d+)/.exec(page.url())![1])
  await expect(page.getByText('выполняется')).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/runs/${id}/report$`), { timeout: (seconds + 60) * 1000 })
  return id
}
