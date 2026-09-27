import { useColorMode } from '@vueuse/core'
import { computed } from 'vue'

export type Theme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'pgbs-theme'

/**
 * Theme from prefers-color-scheme until the user picks one; the choice is remembered.
 * Sets data-theme on <html>, which switches the tokens in tokens.css.
 */
export function useTheme() {
  const mode = useColorMode({
    attribute: 'data-theme',
    storageKey: THEME_STORAGE_KEY,
    initialValue: 'auto',
    disableTransition: false,
  })

  const theme = computed<Theme>({
    get: () => (mode.state.value === 'dark' ? 'dark' : 'light'),
    set: (value) => {
      mode.value = value
    },
  })

  return { theme }
}
