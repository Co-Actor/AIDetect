import type { RouteRecordRaw } from 'vue-router';

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean;
    requiresAuth?: boolean;
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('src/layouts/MainLayout.vue'),
    children: [
      {
        path: '',
        name: 'workbench',
        component: () => import('src/pages/WorkbenchPage.vue'),
        meta: { requiresAuth: true },
      },
      // Legacy deep links — same component, just hint which tab to open via query.
      {
        path: 'detect',
        name: 'detect',
        component: () => import('src/pages/WorkbenchPage.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: 'rewrite',
        name: 'rewrite',
        component: () => import('src/pages/WorkbenchPage.vue'),
        meta: { requiresAuth: true },
      },
    ],
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('src/pages/LoginPage.vue'),
    meta: { public: true },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('src/pages/RegisterPage.vue'),
    meta: { public: true },
  },
  {
    path: '/r/:token',
    name: 'shared-result',
    component: () => import('src/pages/SharedResultPage.vue'),
    meta: { public: true },
  },
  {
    path: '/:catchAll(.*)*',
    name: 'error-not-found',
    component: () => import('src/pages/ErrorNotFound.vue'),
  },
];

export default routes;
