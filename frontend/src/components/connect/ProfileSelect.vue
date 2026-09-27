<script setup lang="ts">
import { computed, useId } from 'vue'
import type { Profile } from '@/api/profiles'

const props = defineProps<{ profiles: Profile[]; modelValue: number | null; canCreate: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: number | null] }>()
const id = useId()

const value = computed({
  get: () => (props.modelValue === null ? 'new' : String(props.modelValue)),
  set: (v: string) => emit('update:modelValue', v === 'new' ? null : Number(v)),
})
</script>

<template>
  <div class="profile-select">
    <label :for="id" class="muted">Профиль</label>
    <select :id="id" v-model="value" class="field-input">
      <option v-for="p in profiles" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
      <option v-if="canCreate || modelValue === null" value="new">Новый профиль</option>
    </select>
  </div>
</template>

<style scoped>
.profile-select {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}

select {
  width: auto;
  min-width: 170px;
  height: 36px;
}
</style>
