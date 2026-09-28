<script setup lang="ts">
import { onClickOutside } from '@vueuse/core'
import { ref, useTemplateRef } from 'vue'
import type { BuiltinName, Script } from '@/api/scripts'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { plural } from '@/composables/useFormat'
import { useLoadConfigStore, type ScenarioDraft } from '@/stores/loadConfig'

const store = useLoadConfigStore()

const BUILTIN_TITLES: Record<BuiltinName, string> = {
  'tpcb-like': 'TPC-B',
  'simple-update': 'simple update',
  'select-only': 'select only',
}

const menu = ref<'builtin' | 'script' | null>(null)
const menus = useTemplateRef<HTMLElement>('menus')
onClickOutside(menus, () => (menu.value = null))

function addBuiltin(name: BuiltinName): void {
  store.addBuiltin(name)
  menu.value = null
}

function addScript(from?: Script): void {
  store.addScript(from)
  menu.value = null
}

function subtitle(s: ScenarioDraft): string {
  if (s.kind === 'builtin') return `встроенный · ${BUILTIN_TITLES[s.name]}`
  return s.scriptId === null ? 'свой' : 'свой · из библиотеки'
}

// Drag and drop to reorder; Alt+↑/↓ on the handle does the same from the keyboard.
const dragFrom = ref<number | null>(null)
const dragOver = ref<number | null>(null)

function onDrop(index: number): void {
  if (dragFrom.value !== null) store.move(dragFrom.value, index)
  dragFrom.value = null
  dragOver.value = null
}

function onHandleKey(event: KeyboardEvent, index: number): void {
  if (!event.altKey) return
  if (event.key === 'ArrowUp') store.move(index, index - 1)
  if (event.key === 'ArrowDown') store.move(index, index + 1)
}

function onWeight(uid: string, event: Event): void {
  store.setWeight(uid, Number((event.target as HTMLInputElement).value))
}
</script>

<template>
  <div class="scenarios">
    <header class="head">
      <h2>Сценарии</h2>
      <div ref="menus" class="adders">
        <div class="menu-wrap">
          <AppButton :aria-expanded="menu === 'builtin'" @click="menu = menu === 'builtin' ? null : 'builtin'">
            <AppIcon name="plus" :size="16" /> Встроенный
          </AppButton>
          <ul v-if="menu === 'builtin'" class="menu card" role="menu">
            <li v-for="(title, name) in BUILTIN_TITLES" :key="name">
              <button type="button" role="menuitem" @click="addBuiltin(name)">
                <span class="mono">{{ name }}</span> <span class="muted">{{ title }}</span>
              </button>
            </li>
          </ul>
        </div>
        <div class="menu-wrap">
          <AppButton :aria-expanded="menu === 'script'" @click="menu = menu === 'script' ? null : 'script'">
            <AppIcon name="plus" :size="16" /> Свой скрипт
          </AppButton>
          <ul v-if="menu === 'script'" class="menu card" role="menu">
            <li>
              <button type="button" role="menuitem" @click="addScript()">Новый скрипт</button>
            </li>
            <li v-if="store.library.length" class="menu-caption muted">Из библиотеки</li>
            <li v-for="s in store.library" :key="s.id">
              <button type="button" role="menuitem" class="mono" @click="addScript(s)">{{ s.name }}</button>
            </li>
          </ul>
        </div>
      </div>
    </header>

    <p v-if="store.scenarios.length === 0" class="muted empty">
      Добавьте встроенный сценарий pgbench или свой скрипт.
    </p>
    <ol class="list">
      <li
        v-for="(s, index) in store.scenarios"
        :key="s.uid"
        class="item"
        :class="{ selected: store.selected === s.uid, over: dragOver === index }"
        @click="store.selected = s.uid"
        @dragover.prevent="dragOver = index"
        @dragleave="dragOver = null"
        @drop.prevent="onDrop(index)"
      >
        <span
          class="grip"
          draggable="true"
          tabindex="0"
          role="button"
          :aria-label="`Переместить ${s.name}: Alt+стрелки`"
          @dragstart="dragFrom = index"
          @keydown="onHandleKey($event, index)"
        >⋮⋮</span>
        <AppIcon :name="s.kind === 'builtin' ? 'database' : 'file'" :size="18" class="kind" />
        <div class="title">
          <span class="mono name">{{ s.name }}</span>
          <span class="muted sub">{{ subtitle(s) }}</span>
        </div>
        <span v-if="store.errorCount(s)" class="errors">
          <AppIcon name="alert" :size="12" />
          {{ store.errorCount(s) }} {{ plural(store.errorCount(s), ['ошибка', 'ошибки', 'ошибок']) }}
        </span>
        <label class="weight">
          <span class="muted">вес</span>
          <input
            class="field-input mono"
            type="number"
            min="1"
            max="1000"
            :value="s.weight"
            :aria-label="`Вес ${s.name}`"
            @click.stop
            @change="onWeight(s.uid, $event)"
          />
        </label>
        <span class="share mono">{{ store.share(s) }}%</span>
        <button
          type="button"
          class="remove"
          :aria-label="`Убрать ${s.name}`"
          @click.stop="store.remove(s.uid)"
        >
          <AppIcon name="trash" :size="14" />
        </button>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.adders {
  display: flex;
  gap: 10px;
}

.menu-wrap {
  position: relative;
}

.menu {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  z-index: 20;
  min-width: 240px;
  margin: 0;
  padding: 6px;
  list-style: none;
  border-radius: 14px;
  box-shadow: 0 12px 32px rgb(20 20 26 / 0.14);
}

.menu button {
  display: block;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: none;
  text-align: left;
  cursor: pointer;
}

.menu button:hover {
  background: var(--color-selected);
}

.menu-caption {
  padding: 8px 10px 2px;
  font-size: 11px;
}

.list {
  display: grid;
  gap: 10px;
  margin: 0 0 14px;
  padding: 0;
  list-style: none;
}

.item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border: 1px solid var(--color-border);
  border-radius: 14px;
  cursor: pointer;
  background: var(--color-surface);
}

.item.selected {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 1px var(--color-primary);
}

.item.over {
  border-style: dashed;
}

.grip {
  color: var(--color-text-muted);
  cursor: grab;
  letter-spacing: -3px;
  user-select: none;
}

.kind {
  color: var(--color-primary);
  flex: none;
}

.title {
  display: grid;
  flex: 1;
  min-width: 0;
}

.name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sub {
  font-size: 12px;
}

.errors {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--color-orange-text);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.weight {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.weight input {
  width: 64px;
  height: 36px;
  text-align: center;
  padding: 0 6px;
}

.share {
  width: 40px;
  text-align: right;
  font-size: 12px;
  color: var(--color-text-muted);
}

.remove {
  border: 0;
  background: none;
  color: var(--color-text-muted);
  cursor: pointer;
}

.empty {
  margin: 0 0 12px;
}
</style>
