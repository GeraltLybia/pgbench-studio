import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import ThemeToggle from '@/components/layout/ThemeToggle.vue'
import { THEME_STORAGE_KEY } from '@/composables/useTheme'

function mockPreferredScheme(dark: boolean): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: dark && query.includes('dark'),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      onchange: null,
      dispatchEvent: vi.fn(),
    })),
  )
}

beforeEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
})

describe('theme', () => {
  it('follows prefers-color-scheme until the user chooses', async () => {
    mockPreferredScheme(true)
    const wrapper = mount(ThemeToggle)
    await nextTick()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(wrapper.get('[aria-checked="true"]').text()).toContain('Тёмная')
  })

  it('remembers the chosen theme', async () => {
    mockPreferredScheme(false)
    const wrapper = mount(ThemeToggle)
    await nextTick()
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    const dark = wrapper.findAll('[role="radio"]').find((b) => b.text().includes('Тёмная'))!
    await dark.trigger('click')
    await nextTick()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  })
})
