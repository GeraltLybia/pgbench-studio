<script setup lang="ts">
import { onMounted } from 'vue'
import { INDICATOR_LABELS, useSystemStore } from '@/stores/system'
import ThemeToggle from './ThemeToggle.vue'

const system = useSystemStore()
onMounted(() => void system.loadReadiness())

// Decorative TPS and latency lines, as on the mockup.
function series(seed: number, base: number, amp: number): string {
  let x = seed
  const points: string[] = []
  for (let i = 0; i <= 90; i++) {
    x = (x * 9301 + 49297) % 233280
    points.push(`${i * 6},${(base + (x / 233280 - 0.5) * amp).toFixed(1)}`)
  }
  return points.join(' ')
}
const tps = series(7, 40, 34)
const latency = series(13, 100, 22)
</script>

<template>
  <div class="auth">
    <section class="hero" aria-hidden="true">
      <div class="brand">pgbench studio</div>
      <h1 class="headline">Нагрузочные тесты PostgreSQL без командной строки</h1>
      <p class="lead">
        Настройка сценариев, запуск с живыми логами и отчёты с графиками — в одном окне.
      </p>
      <svg class="lines" viewBox="0 0 540 140" preserveAspectRatio="none">
        <line x1="0" y1="10" x2="540" y2="10" class="grid" />
        <line x1="0" y1="130" x2="540" y2="130" class="grid" />
        <polyline :points="tps" class="tps" />
        <polyline :points="latency" class="latency" />
      </svg>
      <div class="legend">
        <span><i class="tps-dot" />TPS</span>
        <span><i class="latency-dot" />latency</span>
      </div>
    </section>

    <section class="panel">
      <div class="top"><ThemeToggle /></div>
      <div class="center"><slot /></div>
      <footer class="bottom">
        <span class="status">
          <span class="dot" :class="system.indicator" />
          {{ INDICATOR_LABELS[system.indicator] }}
        </span>
        <span v-if="system.pgbenchMajor" class="mono">pgbench {{ system.pgbenchMajor }}</span>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.auth {
  display: grid;
  grid-template-columns: minmax(360px, 45%) 1fr;
  min-height: 100vh;
}

.hero {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 56px 54px 44px;
  background: var(--color-hero-bg);
  color: var(--color-hero-text);
  overflow: hidden;
}

.brand {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 16px;
}

.headline {
  margin-top: 64px;
  max-width: 440px;
  font-size: 38px;
  line-height: 1.15;
  color: var(--color-hero-text);
}

.lead {
  max-width: 400px;
  margin: 20px 0 0;
  color: var(--color-hero-muted);
  font-size: 16px;
}

.lines {
  width: 100%;
  height: 140px;
  margin: auto 0 0;
  transform: translateX(-54px);
  width: calc(100% + 108px);
}

.lines polyline {
  fill: none;
  stroke-width: 2;
}

.lines .tps {
  stroke: var(--color-cyan);
}

.lines .latency {
  stroke: var(--color-orange);
}

.lines .grid {
  stroke: rgb(255 255 255 / 0.12);
}

.legend {
  display: flex;
  gap: 20px;
  margin-top: 90px;
  font-size: 12px;
  color: var(--color-hero-muted);
}

.legend i {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 8px;
  border-radius: 50%;
  vertical-align: middle;
}

.tps-dot {
  background: var(--color-cyan);
}

.latency-dot {
  background: var(--color-orange);
}

.panel {
  display: flex;
  flex-direction: column;
  padding: 28px 32px;
}

.top {
  align-self: flex-end;
  width: 200px;
}

.center {
  flex: 1;
  display: grid;
  place-items: center;
  padding: 24px 0;
}

.bottom {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--color-text-muted);
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-disabled);
}

.dot.ok {
  background: var(--color-primary);
}

.dot.fail {
  background: var(--color-orange);
}

@media (max-width: 860px) {
  .auth {
    grid-template-columns: 1fr;
  }

  .hero {
    display: none;
  }
}
</style>
