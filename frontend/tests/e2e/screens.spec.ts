/**
 * Screenshots of every screen in both themes, for checking against the mockups and for the
 * README. Not part of the e2e run: only with SCREENSHOTS=<directory>, e.g.
 *   SCREENSHOTS=../docs/screenshots E2E_ADMIN_PASSWORD=… pnpm e2e screens
 * Needs a profile for the test database on the stack (the flow spec creates one).
 */
import { expect, test, type Page } from '@playwright/test'
import { env } from './env'
import { waitForReport } from './helpers'

const dir = process.env.SCREENSHOTS
test.skip(!dir, 'set SCREENSHOTS=<directory> to take screenshots')
test.describe.configure({ mode: 'serial' })

/** Window-sized shots: the sidebar is sticky, so a full-page shot would cut it off. */
async function shot(page: Page, theme: string, name: string): Promise<void> {
  // Charts are canvas: give ECharts a moment after the last data arrives.
  await page.waitForTimeout(600)
  await page.screenshot({ path: `${dir}/${theme}-${name}.png` })
}

for (const theme of ['light', 'dark'] as const) {
  test(`экраны · ${theme}`, async ({ browser }) => {
    const context = await browser.newContext({ colorScheme: theme, viewport: { width: 1440, height: 1000 } })
    await context.addInitScript((value) => localStorage.setItem('pgbs-theme', value), theme)
    const page = await context.newPage()

    await page.goto('/login')
    await expect(page.getByRole('button', { name: 'Войти' })).toBeVisible()
    await shot(page, theme, '01-login')

    await page.getByLabel('Логин').fill(env.adminUser)
    await page.getByLabel('Пароль', { exact: true }).fill(env.adminPassword)
    await page.getByRole('button', { name: 'Войти' }).click()
    await expect(page).toHaveURL(/\/connect$/)
    // A fresh browser has no active profile: take the first one for the test database.
    const profile = page.getByLabel('Профиль')
    const option = profile.locator('option', { hasText: env.dbHost }).first()
    await profile.selectOption((await option.getAttribute('value')) ?? '')
    await page.getByRole('button', { name: 'Проверить соединение' }).click()
    await expect(page.getByRole('heading', { name: 'Соединение установлено' })).toBeVisible({ timeout: 30_000 })
    await shot(page, theme, '02-connect')

    await page.getByRole('button', { name: 'Далее: нагрузка' }).click()
    await page.getByLabel('Длительность').fill('30')
    await page.getByLabel('Клиенты · -c').fill('8')
    await page.getByLabel('Потоки · -j').fill('2')
    await page.getByRole('button', { name: 'Свой скрипт' }).click()
    await page.getByRole('menuitem', { name: 'Новый скрипт' }).click()
    await expect(page.locator('.cm-content')).toBeVisible()
    await page.waitForTimeout(800) // validation markers
    await shot(page, theme, '03-load')

    await page.getByRole('button', { name: 'Запустить тест' }).click()
    await page.getByRole('dialog', { name: 'Сводка перед запуском' }).getByRole('button', { name: 'Запустить' }).click()
    await expect(page).toHaveURL(/\/runs\/\d+$/)
    await page.waitForTimeout(14_000)
    await shot(page, theme, '04-run')
    const run = await waitForReport(page, 30)
    await expect(page.getByRole('heading', { name: `Отчёт · тест #${run}` })).toBeVisible()
    await shot(page, theme, '05-report')

    await page.goto(`/history?with=${run}`)
    await page.locator('tbody input[type="checkbox"]').nth(1).check()
    await expect(page.locator('.compare .overlay')).toBeVisible()
    await page.locator('.compare').scrollIntoViewIfNeeded()
    await shot(page, theme, '06-history')

    await page.getByRole('button', { name: 'Открыть полное сравнение' }).click()
    await expect(page.getByRole('heading', { name: 'Метрики' })).toBeVisible()
    await shot(page, theme, '07-compare')

    await page.goto('/admin/users')
    await expect(page.getByRole('heading', { name: 'Новый пользователь' })).toBeVisible()
    await shot(page, theme, '08-users')
    await context.close()
  })
}
