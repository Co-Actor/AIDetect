import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('src/layouts/MainLayout.vue'),
    children: [
      {
        path: '',
        name: 'workbench',
        component: () => import('src/pages/WorkbenchPage.vue'),
      },
      // Legacy deep links — same component, just hint which tab to open via query.
      {
        path: 'detect',
        name: 'detect',
        component: () => import('src/pages/WorkbenchPage.vue'),
      },
      {
        path: 'rewrite',
        name: 'rewrite',
        component: () => import('src/pages/WorkbenchPage.vue'),
      },
    ],
  },
  {
    path: '/:catchAll(.*)*',
    name: 'error-not-found',
    component: () => import('src/pages/ErrorNotFound.vue'),
  },
];

export default routes;
