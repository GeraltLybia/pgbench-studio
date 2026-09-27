<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { formatDateTime, formatInt, formatMs, formatTime, isToday } from '@/composables/useFormat'
import { useProfilesStore } from '@/stores/profiles'

const store = useProfilesStore()
const result = computed(() => store.result)

const checkedAt = computed(() => {
  const at = result.value?.checked_at
  if (!at) return ''
  return isToday(at) ? `Проверено сегодня в ${formatTime(at)}` : `Проверено ${formatDateTime(at)}`
})

/** «16.4 (Debian 16.4-1.pgdg120+1)» -> «16.4» */
function shortVersion(version: string): string {
  return version.split(' ')[0] ?? version
}
</script>

<template>
  <section
    class="card check"
    :class="{ ok: result?.ok === true, fail: result?.ok === false }"
    aria-live="polite"
    aria-labelledby="check-title"
  >
    <template v-if="result?.ok === true">
      <header class="head">
        <span class="badge ok-badge"><AppIcon name="check" :size="20" /></span>
        <div>
          <h2 id="check-title">Соединение установлено</h2>
          <p class="muted when">{{ checkedAt }}</p>
        </div>
      </header>
      <dl class="facts">
        <div>
          <dt>Сервер</dt>
          <dd>PostgreSQL {{ shortVersion(result.server_version) }}</dd>
        </div>
        <div>
          <dt>pgbench на агенте</dt>
          <dd>
            {{ result.pgbench_version ?? '—' }} ·
            {{ result.warnings.length ? 'есть предупреждение' : 'совместим' }}
          </dd>
        </div>
        <div>
          <dt>Время отклика</dt>
          <dd>{{ formatMs(result.response_ms) }}</dd>
        </div>
        <div>
          <dt>max_connections</dt>
          <dd>{{ result.max_connections }} (свободно {{ result.free_connections }})</dd>
        </div>
        <div>
          <dt>Таблицы pgbench_*</dt>
          <dd>{{ result.pgbench_tables ? `найдены · scale ≈ ${result.scale}` : 'не найдены' }}</dd>
        </div>
        <div v-if="result.pgbench_tables">
          <dt>pgbench_accounts</dt>
          <dd>{{ formatInt(result.accounts_rows) }} строк</dd>
        </div>
      </dl>
      <div v-for="warning in result.warnings" :key="warning" class="notice-warning">
        <AppIcon name="alert" :size="16" class="notice-icon" />
        <div>{{ warning }} Переход к нагрузке не блокируется.</div>
      </div>
      <p v-if="!result.pgbench_tables" class="muted note">
        Таблиц pgbench нет — инициализируйте данные ниже, чтобы запускать встроенные сценарии.
      </p>
    </template>

    <template v-else-if="result?.ok === false">
      <header class="head">
        <span class="badge fail-badge"><AppIcon name="alert" :size="20" /></span>
        <div>
          <h2 id="check-title">Не удалось подключиться</h2>
          <p class="muted when">{{ checkedAt }}</p>
        </div>
      </header>
      <div class="reason">
        <div class="reason-head">
          <strong>{{ result.message }}</strong>
          <code class="code">{{ result.code }}</code>
        </div>
        <p>{{ result.hint }}</p>
      </div>
      <details class="raw">
        <summary>Текст ошибки PostgreSQL</summary>
        <pre>{{ result.raw }}</pre>
      </details>
      <p class="muted locked">
        <AppIcon name="lock" :size="12" />
        Настройка нагрузки откроется после успешной проверки соединения
      </p>
    </template>

    <template v-else>
      <header class="head">
        <span class="badge idle-badge"><AppIcon name="plug" :size="20" /></span>
        <div>
          <h2 id="check-title">{{ store.checking ? 'Проверяем соединение…' : 'Соединение не проверено' }}</h2>
          <p class="muted when">
            Проверьте соединение с текущими параметрами — без этого нагрузка недоступна.
          </p>
        </div>
      </header>
    </template>
  </section>
</template>

<style scoped>
.check {
  display: grid;
  gap: 16px;
}

.check.fail {
  border-color: var(--color-orange);
}

.head {
  display: flex;
  align-items: center;
  gap: 14px;
}

.head h2 {
  font-size: 16px;
}

.when {
  margin: 2px 0 0;
  font-size: 12px;
}

.badge {
  flex: none;
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  color: #fff;
}

.ok-badge {
  background: var(--color-primary);
  color: var(--color-on-primary);
}

.fail-badge {
  background: var(--color-orange);
}

.idle-badge {
  background: var(--color-pill);
  color: var(--color-primary);
}

.facts {
  margin: 0;
  display: grid;
}

.facts > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-border);
  font-size: 13px;
}

.facts dt {
  color: var(--color-text-muted);
}

.facts dd {
  margin: 0;
  font-family: var(--font-mono);
  text-align: right;
}

.reason {
  padding: 14px 16px;
  border: 1px solid var(--color-warning-border);
  border-radius: var(--radius-field);
  background: var(--color-warning-bg);
  font-size: 13px;
}

.reason-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.reason p {
  margin: 6px 0 0;
}

.code {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-orange-text);
}

.raw {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-field);
  padding: 10px 14px;
}

.raw summary {
  cursor: pointer;
  color: var(--color-primary);
  font-weight: 600;
  font-size: 13px;
}

.raw pre {
  margin: 10px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono);
  font-size: 12px;
}

.locked,
.note {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--color-border);
}
</style>
