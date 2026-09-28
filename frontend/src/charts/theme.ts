/** ECharts colours from the CSS tokens, recomputed when the theme changes. */
import { useMutationObserver } from '@vueuse/core'
import { ref } from 'vue'

export interface ChartColors {
  text: string
  muted: string
  border: string
  surface: string
  surfaceMuted: string
  tps: string
  latency: string
  cpu: string
  ram: string
  fontBody: string
  fontMono: string
}

function read(): ChartColors {
  const style = getComputedStyle(document.documentElement)
  const v = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return {
    text: v('--color-text', '#14141A'),
    muted: v('--color-text-muted', '#5E6275'),
    border: v('--color-border', '#E1E4F0'),
    surface: v('--color-surface', '#FFFFFF'),
    surfaceMuted: v('--color-bg', '#F5F6FC'),
    tps: v('--color-primary', '#145FF5'),
    latency: v('--color-orange', '#FF5A00'),
    cpu: v('--color-primary', '#145FF5'),
    ram: v('--color-cyan', '#2ED0FF'),
    fontBody: v('--font-body', 'sans-serif'),
    fontMono: v('--font-mono', 'monospace'),
  }
}

export function useChartColors() {
  const colors = ref<ChartColors>(read())
  useMutationObserver(
    document.documentElement,
    () => {
      colors.value = read()
    },
    { attributes: true, attributeFilter: ['data-theme'] },
  )
  return colors
}
