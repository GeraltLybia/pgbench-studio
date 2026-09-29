/**
 * Сквозной сценарий этапа 6: подключение → инициализация → 30-секундный тест → отчёт →
 * второй тест → сравнение (editor), затем то же глазами viewer.
 */
import { expect, test, type Page } from '@playwright/test'
import { env } from './env'
import { adminApi, createUser, firstLogin, waitForReport } from './helpers'

test.describe.configure({ mode: 'serial' })

let editorPage: Page
let firstRun = 0
let secondRun = 0

test.beforeAll(async ({ browser, baseURL }) => {
  const api = await adminApi(baseURL!)
  const editor = await createUser(api, 'editor')
  await api.dispose()
  editorPage = await browser.newPage()
  await firstLogin(editorPage, editor.username, editor.temporary)
})

test.afterAll(async () => {
  await editorPage?.close()
})

test('подключение и инициализация данных', async () => {
  const page = editorPage
  await page.goto('/connect')
  await expect(page.getByRole('heading', { name: 'Подключение к базе' })).toBeVisible()

  const profile = page.getByLabel('Профиль')
  if (await profile.isEnabled()) await profile.selectOption('new')
  await page.getByLabel('Хост').fill(env.dbHost)
  await page.getByLabel('Порт').fill(env.dbPort)
  await page.getByLabel('База данных').fill(env.dbName)
  await page.getByLabel('Пользователь').fill(env.dbUser)
  await page.getByLabel('Пароль', { exact: true }).fill(env.dbPassword)

  // Saved first: initialisation belongs to a saved profile.
  await page.getByRole('button', { name: 'Сохранить профиль' }).click()
  await page.getByRole('button', { name: 'Проверить соединение' }).click()
  await expect(page.getByRole('heading', { name: 'Соединение установлено' })).toBeVisible()

  await page.getByLabel('Scale factor (-s)').fill('1')
  await page.getByRole('button', { name: 'Инициализировать…' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel(`Введите ${env.dbName}, чтобы подтвердить`).fill(env.dbName)
  await dialog.getByRole('button', { name: 'Удалить и пересоздать' }).click()
  await expect(page.getByText('Данные инициализированы')).toBeVisible({ timeout: 120_000 })

  await page.getByRole('button', { name: 'Проверить соединение' }).click()
  await expect(page.getByText(/найдены · scale ≈ 1/)).toBeVisible()
  await page.getByRole('button', { name: 'Далее: нагрузка' }).click()
  await expect(page).toHaveURL(/\/load$/)
})

test('30-секундный тест и отчёт', async () => {
  const page = editorPage
  await page.getByLabel('Длительность').fill('30')
  await page.getByLabel('Клиенты · -c').fill('4')
  await page.getByLabel('Потоки · -j').fill('2')
  await expect(page.getByText(/-c 4 -j 2 -T 30/)).toBeVisible()

  await page.getByRole('button', { name: 'Запустить тест' }).click()
  const summary = page.getByRole('dialog', { name: 'Сводка перед запуском' })
  await summary.getByRole('button', { name: 'Запустить' }).click()

  // Live screen: progress arrives every second, then the report opens by itself.
  await expect(page.getByRole('progressbar')).toBeVisible()
  firstRun = await waitForReport(page, 30)

  await expect(page.getByRole('heading', { name: `Отчёт · тест #${firstRun}` })).toBeVisible()
  const tps = page.locator('.kpi').first()
  await expect(tps).toContainText(/\d/)
  const raw = await page.locator('.output').innerText()
  const printed = /tps = ([\d.]+) \(without initial connection time\)/.exec(raw)
  expect(printed).not.toBeNull()
  // The tile keeps pgbench's exact number in its tooltip.
  await expect(tps).toHaveAttribute('title', `tps = ${printed![1]}`)
  await expect(page.getByRole('heading', { name: 'Latency по запросам сценариев' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Ресурсы агента нагрузки' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Параметры запуска' })).toBeVisible()
})

test('«Повторить» и второй тест', async () => {
  const page = editorPage
  await page.getByRole('button', { name: 'Повторить' }).click()
  await expect(page).toHaveURL(/\/load$/)
  await expect(page.getByLabel('Клиенты · -c')).toHaveValue('4')
  await page.getByLabel('Длительность').fill('10')
  await page.getByRole('button', { name: 'Запустить тест' }).click()
  await page.getByRole('dialog', { name: 'Сводка перед запуском' }).getByRole('button', { name: 'Запустить' }).click()
  secondRun = await waitForReport(page, 10)
})

test('история и сравнение двух запусков', async () => {
  const page = editorPage
  await page.goto('/history')
  await page.getByLabel(`Сравнить тест #${firstRun}`, { exact: true }).check()
  await page.getByLabel(`Сравнить тест #${secondRun}`, { exact: true }).check()

  const panel = page.locator('.compare')
  await expect(panel.getByRole('heading', { name: `Сравнение: #${secondRun} против #${firstRun}` })).toBeVisible()
  await expect(panel).toContainText(/Длительность -T, с: 10 → 30/)
  await panel.getByRole('button', { name: 'Открыть полное сравнение' }).click()

  await expect(page).toHaveURL(new RegExp(`/compare\\?a=${secondRun}&b=${firstRun}$`))
  const metrics = page.getByRole('table').first()
  await expect(metrics.getByRole('row', { name: /TPS/ })).toContainText(/[+−±]\d/)
  await expect(page.getByRole('heading', { name: 'Отличия в параметрах' })).toBeVisible()
})

test('viewer видит историю и отчёты, но не может запускать', async ({ browser, baseURL }) => {
  const api = await adminApi(baseURL!)
  const viewer = await createUser(api, 'viewer')
  await api.dispose()
  const page = await browser.newPage()
  await firstLogin(page, viewer.username, viewer.temporary)

  await page.goto('/history')
  await expect(page.getByRole('link', { name: `#${firstRun}`, exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Новый тест' })).toHaveCount(0)

  await page.goto(`/runs/${firstRun}/report`)
  await expect(page.getByRole('heading', { name: `Отчёт · тест #${firstRun}` })).toBeVisible()
  await expect(page.getByRole('button', { name: /Сравнить с/ })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Повторить' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Удалить запуск' })).toHaveCount(0)

  // The UI only hides buttons; the backend refuses on its own.
  const start = await page.request.post('/api/runs', { data: { profile_id: 1, duration_s: 10, scenarios: [{ kind: 'builtin', name: 'select-only' }] } })
  expect(start.status()).toBe(403)
  const remove = await page.request.delete(`/api/runs/${firstRun}`)
  expect(remove.status()).toBe(403)
  await page.close()
})
