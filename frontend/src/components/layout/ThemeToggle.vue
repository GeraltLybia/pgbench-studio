<script setup lang="ts">
import SegmentedControl, { type SegmentOption } from '@/components/ui/SegmentedControl.vue'
import { useTheme, type Theme } from '@/composables/useTheme'

const { theme } = useTheme()
const options: SegmentOption<Theme>[] = [
  { value: 'light', label: 'Светлая', icon: 'sun' },
  { value: 'dark', label: 'Тёмная', icon: 'moon' },
]
</script>

<template>
  <SegmentedControl v-model="theme" :options="options" label="Тема оформления" size="sm" />
</template>
