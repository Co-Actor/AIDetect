<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { useAuthStore } from 'src/stores/auth';

const route = useRoute();
const authStore = useAuthStore();

const isPublicRoute = computed(() => !!route.meta.public);
const showUserMenu = computed(() => authStore.isAuthenticated && !isPublicRoute.value);

// On reload only the token is persisted, not the user object. Re-fetch it so the
// menu shows the email (and a stale/expired token self-clears via fetchMe's catch).
onMounted(() => {
  if (authStore.isAuthenticated && !authStore.user) {
    void authStore.fetchMe();
  }
});
</script>

<template>
  <q-layout view="hHh lpR fFf">
    <q-header :elevated="false" class="atelier-header">
      <q-toolbar class="atelier-toolbar">
        <div class="row items-center q-gutter-md">
          <span class="brand-mark font-display">v</span>
          <div class="column items-start" style="line-height: 1">
            <span class="brand-title">AIDetect</span>
            <span class="eyebrow brand-tag">Veracity workbench</span>
          </div>
        </div>
        <q-space />
        <span class="eyebrow brand-version">v0.1</span>

        <!-- User menu (authenticated, non-public pages) -->
        <template v-if="showUserMenu">
          <q-btn-dropdown
            flat
            no-caps
            class="user-menu-btn q-ml-md"
            :label="authStore.user?.email ?? ''"
            icon="person"
            dropdown-icon="expand_more"
          >
            <q-list>
              <q-item>
                <q-item-section>
                  <q-item-label class="eyebrow">Signed in as</q-item-label>
                  <q-item-label class="user-email">{{ authStore.user?.email }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-separator />
              <q-item
                clickable
                v-close-popup
                data-testid="logout-btn"
                @click="authStore.logout()"
              >
                <q-item-section avatar>
                  <q-icon name="logout" size="sm" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>Sign out</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-btn-dropdown>
        </template>
      </q-toolbar>
      <div class="atelier-header-rule" />
    </q-header>

    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<style scoped lang="scss">
.atelier-header {
  background: var(--paper);
  color: var(--ink);
}
.atelier-toolbar {
  min-height: 64px;
  padding: 0 28px;
}
.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  font-size: 32px;
  line-height: 1;
  color: var(--accent);
}
.brand-title {
  font-family: var(--font-ui);
  font-weight: 600;
  font-size: 18px;
  letter-spacing: -0.01em;
  color: var(--ink);
}
.brand-tag {
  margin-top: 2px;
}
.brand-version {
  color: var(--ink-mute);
}
.atelier-header-rule {
  height: 1px;
  background: var(--rule);
}
.user-menu-btn {
  font-size: 13px;
  color: var(--ink);
  max-width: 240px;

  :deep(.q-btn__content) {
    gap: 4px;
  }
  :deep(.q-btn-dropdown__arrow) {
    margin-left: 2px;
  }
}
.user-email {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--ink);
}
</style>
