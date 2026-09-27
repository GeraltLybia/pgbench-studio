import '@fontsource/golos-text/400.css'
import '@fontsource/golos-text/500.css'
import '@fontsource/golos-text/600.css'
import '@fontsource/golos-text/700.css'
import '@fontsource/unbounded/600.css'
import '@fontsource/unbounded/700.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import './styles/tokens.css'
import './styles/base.css'

import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { onForbidden, onUnauthorized } from './api/http'
import { createAppRouter } from './router'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
const pinia = createPinia()
const router = createAppRouter()
app.use(pinia)
app.use(router)

onUnauthorized(() => {
  useAuthStore().clear()
  const current = router.currentRoute.value
  if (!current.meta.public) {
    void router.push({ name: 'login', query: { redirect: current.fullPath } })
  }
})

onForbidden((error) => {
  if (error.code === 'password_change_required') void router.push({ name: 'password' })
})

app.mount('#app')
