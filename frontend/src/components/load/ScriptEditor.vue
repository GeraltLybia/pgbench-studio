<script setup lang="ts">
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { bracketMatching } from '@codemirror/language'
import { forceLinting, lintGutter } from '@codemirror/lint'
import { EditorState } from '@codemirror/state'
import {
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
} from '@codemirror/view'
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { ApiError } from '@/api/http'
import { runsApi, type DryRunResult } from '@/api/runs'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { plural } from '@/composables/useFormat'
import { pgbenchLinter } from '@/editor/lint'
import { editorTheme, pgbenchLanguage } from '@/editor/pgbenchLanguage'
import { useAuthStore } from '@/stores/auth'
import { useLoadConfigStore, type ScriptDraft } from '@/stores/loadConfig'
import { useProfilesStore } from '@/stores/profiles'
import { SCRIPT_NAME } from '@/validation/runConfig'

const props = defineProps<{ uid: string }>()

const store = useLoadConfigStore()
const profiles = useProfilesStore()
const auth = useAuthStore()
const host = useTemplateRef<HTMLDivElement>('host')
let view: EditorView | null = null

const scenario = computed(
  () => store.scenarios.find((s) => s.uid === props.uid && s.kind === 'script') as ScriptDraft | undefined,
)
const check = computed(() => (scenario.value ? store.checkOf(scenario.value) : null))
const counts = computed(() => {
  const d = check.value?.diagnostics ?? []
  return {
    errors: d.filter((x) => x.severity === 'error').length,
    danger: d.filter((x) => x.severity === 'danger').length,
    warnings: d.filter((x) => x.severity === 'warning').length,
    metaErrors: d.filter((x) => x.severity === 'error' && x.message.includes('\\')).length,
  }
})
const nameError = computed(() =>
  scenario.value && !SCRIPT_NAME.test(scenario.value.name)
    ? 'Латиница, цифры, точка, дефис, подчёркивание; до 64 символов'
    : null,
)

function createState(doc: string): EditorState {
  return EditorState.create({
    doc,
    extensions: [
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightActiveLine(),
      history(),
      bracketMatching(),
      keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
      pgbenchLanguage(),
      lintGutter(),
      pgbenchLinter(async (text) => {
        const result = await store.validate(props.uid)
        return result && result.body === text ? result.diagnostics : null
      }),
      editorTheme,
      EditorView.updateListener.of((update) => {
        if (update.docChanged && scenario.value) scenario.value.body = update.state.doc.toString()
      }),
      EditorView.contentAttributes.of({ 'aria-label': 'Текст сценария pgbench' }),
    ],
  })
}

onMounted(() => {
  view = new EditorView({ state: createState(scenario.value?.body ?? ''), parent: host.value! })
})

onBeforeUnmount(() => view?.destroy())

// Another scenario selected: new document and undo history.
watch(
  () => props.uid,
  () => {
    view?.setState(createState(scenario.value?.body ?? ''))
    dry.value = null
  },
)

// External change of the text (e.g. a restored draft).
watch(
  () => scenario.value?.body,
  (body) => {
    if (view && body !== undefined && body !== view.state.doc.toString()) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: body } })
    }
  },
)

// Server version or -D names changed: re-lint without an edit.
watch(
  () => store.context,
  () => view && forceLinting(view),
)

// --- library -------------------------------------------------------------------------------

const saving = ref(false)
const saveError = ref<string | null>(null)

async function save(): Promise<void> {
  saveError.value = null
  saving.value = true
  try {
    await store.saveToLibrary(props.uid)
  } catch (e) {
    saveError.value = e instanceof ApiError ? e.message : 'Не удалось сохранить сценарий'
  } finally {
    saving.value = false
  }
}

// --- dry run -------------------------------------------------------------------------------

const dry = ref<DryRunResult | null>(null)
const dryError = ref<string | null>(null)
const dryRunning = ref(false)

const canDry = computed(
  () =>
    auth.can('runs.start') &&
    profiles.connected &&
    profiles.active !== null &&
    counts.value.errors === 0 &&
    check.value !== null &&
    !nameError.value,
)

async function runDry(): Promise<void> {
  if (!scenario.value || !profiles.active) return
  dryError.value = null
  dry.value = null
  const request = {
    profile_id: profiles.active.id,
    protocol: store.parsedParams.success ? store.parsedParams.data.protocol : 'simple',
    variables: store.variables.map((v) => ({ name: v.name, value: v.value })),
    scenario: { kind: 'script' as const, name: scenario.value.name, body: scenario.value.body, weight: 1 },
    confirmed_rules: [] as string[],
  }
  const dangerous = (check.value?.diagnostics ?? []).filter((d) => d.severity === 'danger')
  if (dangerous.length > 0) {
    const list = dangerous.map((d) => `• строка ${d.line}: ${d.message}`).join('\n')
    if (!window.confirm(`Пробный прогон выполнит опасные конструкции по-настоящему:\n${list}\n\nПродолжить?`)) {
      return
    }
    request.confirmed_rules = dangerous.map((d) => `sql.${d.rule ?? 'syntax'}@${request.scenario.name}:${d.line}`)
  }
  dryRunning.value = true
  try {
    dry.value = await runsApi.dry(request)
  } catch (e) {
    dryError.value = e instanceof ApiError ? e.message : 'Пробный прогон не удался'
  } finally {
    dryRunning.value = false
  }
}
</script>

<template>
  <section v-if="scenario" class="editor-card" aria-label="Редактор сценария">
    <header class="head">
      <label class="name">
        <span class="visually-hidden">Имя файла сценария</span>
        <input
          v-model="scenario.name"
          class="name-input mono"
          :class="{ invalid: nameError }"
          :title="nameError ?? undefined"
          spellcheck="false"
        />
      </label>
      <span v-if="store.isModified(scenario)" class="pill">изменён</span>
      <span v-else-if="scenario.scriptId === null" class="pill muted-pill">не в библиотеке</span>
      <span class="vars muted">
        <template v-if="check?.variablesUsed.length">
          Переменные:
          <span v-for="v in check.variablesUsed" :key="v" class="mono var">:{{ v }}</span>
        </template>
      </span>
      <AppButton
        v-if="auth.can('scripts.edit') && (store.isModified(scenario) || scenario.scriptId === null)"
        variant="ghost"
        :loading="saving"
        :disabled="!!nameError"
        @click="save"
      >
        Сохранить в библиотеку
      </AppButton>
    </header>
    <p v-if="nameError || saveError" class="error">{{ nameError ?? saveError }}</p>

    <div ref="host" class="cm-host" />

    <footer class="foot">
      <div class="status" aria-live="polite">
        <template v-if="!check">
          <span class="muted">Проверяем…</span>
        </template>
        <template v-else>
          <span v-if="counts.errors" class="bad">
            <AppIcon name="alert" :size="14" />
            {{ counts.errors }} {{ plural(counts.errors, ['ошибка', 'ошибки', 'ошибок']) }}
          </span>
          <span v-if="counts.danger" class="bad">
            {{ counts.danger }} {{ plural(counts.danger, ['опасная конструкция', 'опасные конструкции', 'опасных конструкций']) }}
          </span>
          <span v-if="counts.warnings" class="muted">
            {{ counts.warnings }} {{ plural(counts.warnings, ['предупреждение', 'предупреждения', 'предупреждений']) }}
          </span>
          <span class="muted">
            · {{ counts.metaErrors ? 'ошибки в мета-командах' : 'мета-команды в порядке' }} · проверено
            парсером PostgreSQL{{ store.serverMajor ? ` ${store.serverMajor}` : '' }}
          </span>
        </template>
      </div>
      <AppButton
        :disabled="!canDry"
        :loading="dryRunning"
        title="Запросы выполняются по-настоящему: -c 1 -t 1 -n"
        @click="runDry"
      >
        <AppIcon name="play" :size="14" /> Пробный прогон · -t 1
      </AppButton>
    </footer>

    <div v-if="dry || dryError" class="dry" :class="{ ok: dry?.ok, fail: dryError || dry?.ok === false }">
      <div class="dry-head">
        <strong>
          <template v-if="dryError">Пробный прогон не запущен</template>
          <template v-else-if="dry?.timed_out">Пробный прогон превысил таймаут</template>
          <template v-else-if="dry?.ok">Пробный прогон прошёл · {{ Math.round(dry.duration_ms) }} мс</template>
          <template v-else>Пробный прогон завершился с ошибкой (код {{ dry?.exit_code }})</template>
        </strong>
        <button type="button" class="link" @click="dry = null; dryError = null">Скрыть</button>
      </div>
      <p v-if="dryError">{{ dryError }}</p>
      <pre v-else class="out">{{ [dry?.stderr, dry?.stdout].filter(Boolean).join('\n').trim() }}</pre>
    </div>
  </section>
</template>

<style scoped>
.editor-card {
  border: 1px solid var(--color-border);
  border-radius: 16px;
  overflow: hidden;
  background: var(--color-surface);
}

.head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border);
  flex-wrap: wrap;
}

.name-input {
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  padding: 4px 6px;
  font-weight: 600;
  font-size: 13px;
  width: 180px;
}

.name-input:hover,
.name-input:focus {
  border-color: var(--color-border);
  outline: none;
}

.name-input.invalid {
  border-color: var(--color-orange);
}

.pill {
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  background: var(--color-pill);
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 600;
}

.muted-pill {
  color: var(--color-text-muted);
}

.vars {
  margin-left: auto;
  font-size: 12px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.var {
  color: var(--color-var);
}

.cm-host {
  min-height: 220px;
  max-height: 420px;
  overflow: auto;
}

.cm-host :deep(.cm-editor) {
  min-height: 220px;
}

.foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-top: 1px solid var(--color-border);
  flex-wrap: wrap;
}

.status {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
}

.bad {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--color-orange-text);
  font-weight: 600;
}

.error {
  margin: 0;
  padding: 6px 14px;
  color: var(--color-orange-text);
  font-size: 12px;
}

.dry {
  padding: 12px 14px;
  border-top: 1px solid var(--color-border);
  font-size: 13px;
}

.dry.fail .dry-head strong {
  color: var(--color-orange-text);
}

.dry-head {
  display: flex;
  justify-content: space-between;
}

.out {
  margin: 8px 0 0;
  max-height: 180px;
  overflow: auto;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--color-code-bg);
  color: var(--color-code-text);
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: pre-wrap;
}

.link {
  border: 0;
  background: none;
  color: var(--color-primary);
  cursor: pointer;
}
</style>
