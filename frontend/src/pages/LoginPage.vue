<script setup lang="ts">
import { ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useQuasar } from 'quasar';
import { useAuthStore } from 'src/stores/auth';
import GoogleSignInButton from 'src/components/GoogleSignInButton.vue';

const $q = useQuasar();
const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();

const email = ref('');
const password = ref('');
const loading = ref(false);

async function handleLogin(): Promise<void> {
  loading.value = true;
  try {
    await authStore.login(email.value.trim(), password.value);
    const redirect = (route.query.redirect as string) || '/';
    await router.push(redirect);
  } catch (err) {
    $q.notify({
      message: err instanceof Error ? err.message : 'Login failed',
      icon: 'error_outline',
      color: 'negative',
    });
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <q-layout view="hHh lpr fFf">
    <q-page-container>
      <q-page class="auth-page flex flex-center">
        <div class="auth-card">
          <div class="auth-brand q-mb-lg">
            <span class="brand-mark font-display">v</span>
            <span class="brand-title">AIDetect</span>
          </div>

          <h2 class="auth-heading">Sign in</h2>

          <q-form class="auth-form" @submit.prevent="handleLogin">
            <div class="q-mb-md">
              <div class="eyebrow q-mb-xs">Email</div>
              <q-input
                v-model="email"
                type="email"
                outlined
                dense
                autocomplete="email"
                placeholder="you@example.com"
                :rules="[(v: string) => !!v || 'Email is required']"
              />
            </div>

            <div class="q-mb-lg">
              <div class="eyebrow q-mb-xs">Password</div>
              <q-input
                v-model="password"
                type="password"
                outlined
                dense
                autocomplete="current-password"
                placeholder="••••••••"
                :rules="[(v: string) => !!v || 'Password is required']"
              />
            </div>

            <q-btn
              data-testid="login-submit"
              type="submit"
              label="Sign in"
              unelevated
              no-caps
              class="bg-primary text-white full-width"
              :loading="loading"
            >
              <template #loading><q-spinner-dots /></template>
            </q-btn>
          </q-form>

          <div class="auth-divider">
            <span class="eyebrow">or</span>
          </div>

          <GoogleSignInButton />

          <p class="auth-switch eyebrow">
            Don't have an account?
            <router-link to="/register" class="auth-link">Register</router-link>
          </p>
        </div>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<style scoped lang="scss">
.auth-page {
  background: var(--paper);
  min-height: 100vh;
  padding: 24px;
}
.auth-card {
  width: 100%;
  max-width: 400px;
  padding: 48px 40px;
  border: 1px solid var(--rule);
  border-radius: 8px;
  background: var(--paper);
}
.auth-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-mark {
  font-size: 28px;
  color: var(--accent);
  line-height: 1;
}
.brand-title {
  font-family: var(--font-ui);
  font-weight: 600;
  font-size: 18px;
  letter-spacing: -0.01em;
  color: var(--ink);
}
.auth-heading {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 400;
  letter-spacing: -0.03em;
  color: var(--ink);
  margin: 0 0 28px;
  line-height: 1.1;
}
.auth-form {
  display: flex;
  flex-direction: column;
}
.auth-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 20px 0 12px;
  color: var(--ink-mute);

  &::before,
  &::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--rule);
  }
}
.auth-switch {
  margin-top: 20px;
  text-align: center;
  color: var(--ink-mute);
}
.auth-link {
  color: var(--accent);
  text-decoration: none;
  font-weight: 500;

  &:hover { text-decoration: underline; }
}
</style>
