import { defineRouter } from '#q-app/wrappers';
import { createMemoryHistory, createRouter, createWebHistory } from 'vue-router';
import routes from './routes';

const TOKEN_KEY = 'aidetect_auth_token';

export default defineRouter(function () {
  const createHistory = process.env.SERVER ? createMemoryHistory : createWebHistory;

  const Router = createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
    routes,
    history: createHistory(process.env.VUE_ROUTER_BASE),
  });

  Router.beforeEach((to) => {
    // Read directly from localStorage — avoids Pinia init-order issues in the
    // router guard (the guard runs before boot files complete on first load).
    const isAuthenticated =
      typeof localStorage !== 'undefined'
        ? localStorage.getItem(TOKEN_KEY) !== null
        : false;

    if (!to.meta.public && to.meta.requiresAuth && !isAuthenticated) {
      return { path: '/login', query: { redirect: to.fullPath } };
    }
  });

  return Router;
});
