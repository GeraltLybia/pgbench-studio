import { createRouter, createWebHistory, type Router } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { HOME, resolveNavigation } from './guards'

export const routes = [
  { path: '/', redirect: HOME },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, bare: true, title: 'Вход' },
  },
  {
    path: '/password',
    name: 'password',
    component: () => import('@/views/ChangePasswordView.vue'),
    meta: { bare: true, title: 'Смена пароля' },
  },
  {
    path: '/admin/users',
    name: 'users',
    component: () => import('@/views/UsersView.vue'),
    meta: { role: 'admin' as const, title: 'Пользователи' },
  },
  {
    path: '/connect',
    name: 'connect',
    component: () => import('@/views/ConnectView.vue'),
    meta: { title: 'Подключение' },
  },
  {
    path: '/load',
    name: 'load',
    component: () => import('@/views/LoadView.vue'),
    meta: { title: 'Нагрузка' },
  },
  {
    path: '/runs/:id',
    name: 'run',
    component: () => import('@/views/RunView.vue'),
    meta: { title: 'Выполнение' },
  },
  {
    path: '/runs/:id/report',
    name: 'report',
    component: () => import('@/views/ReportView.vue'),
    meta: { title: 'Отчёт' },
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('@/views/HistoryView.vue'),
    meta: { title: 'История запусков' },
  },
  {
    path: '/compare',
    name: 'compare',
    component: () => import('@/views/CompareView.vue'),
    meta: { title: 'Сравнение' },
  },
  { path: '/:pathMatch(.*)*', redirect: HOME },
]

export function createAppRouter(): Router {
  const router = createRouter({ history: createWebHistory(), routes })

  router.beforeEach((to) => {
    const auth = useAuthStore()
    return resolveNavigation(to, {
      loaded: auth.loaded,
      get role() {
        return auth.role
      },
      get mustChangePassword() {
        return auth.mustChangePassword
      },
      ensureLoaded: async () => {
        await auth.fetchMe()
      },
    })
  })

  router.afterEach((to) => {
    document.title = to.meta.title ? `${to.meta.title} · pgbench studio` : 'pgbench studio'
  })

  return router
}
