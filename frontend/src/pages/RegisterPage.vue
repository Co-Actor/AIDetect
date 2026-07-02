<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useQuasar } from 'quasar';
import { useAuthStore } from 'src/stores/auth';
import { authApi } from 'src/services/api';
import GoogleSignInButton from 'src/components/GoogleSignInButton.vue';

const $q = useQuasar();
const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();

// Invite token from query string (?invite=<token>)
const inviteToken = ref<string | undefined>(
  typeof route.query.invite === 'string' ? route.query.invite : undefined,
);

// State machine: 'loading' | 'no-invite' | 'valid' | 'invalid'
type PageState = 'loading' | 'no-invite' | 'valid' | 'invalid';
const pageState = ref<PageState>(inviteToken.value ? 'loading' : 'no-invite');

// Prefilled email from invitation lookup
const inviteEmail = ref('');

const password = ref('');
const loading = ref(false);

onMounted(async () => {
  if (!inviteToken.value) return; // stays 'no-invite'
  try {
    const res = await authApi.invitation(inviteToken.value);
    if (res.valid) {
      inviteEmail.value = res.email ?? '';
      pageState.value = 'valid';
    } else {
      pageState.value = 'invalid';
    }
  } catch {
    pageState.value = 'invalid';
  }
});

async function handleRegister(): Promise<void> {
  if (pageState.value !== 'valid') return;
  loading.value = true;
  try {
    await authStore.register(inviteEmail.value.trim(), password.value, undefined, inviteToken.value);
    const redirect = (route.query.redirect as string) || '/';
    await router.push(redirect);
  } catch (err) {
    $q.notify({
      message: err instanceof Error ? err.message : 'Registration failed',
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

          <!-- Loading invitation -->
          <div v-if="pageState === 'loading'" class="flex flex-center q-py-xl">
            <q-spinner-dots size="32px" color="primary" />
          </div>

          <!-- No invite token: invite-only notice -->
          <template v-else-if="pageState === 'no-invite'">
            <h2 class="auth-heading">Registration is invite-only</h2>
            <p data-testid="register-invite-only" class="invite-notice eyebrow">
              To get access, open a shared result link and request an invite. Once you receive an
              invitation email, follow the link inside to create your account.
            </p>

            <div class="auth-divider">
              <span class="eyebrow">or sign in with Google</span>
            </div>

            <GoogleSignInButton />

            <p class="auth-switch eyebrow">
              Already have an account?
              <router-link to="/login" class="auth-link">Sign in</router-link>
            </p>
          </template>

          <!-- Invalid / expired invite -->
          <template v-else-if="pageState === 'invalid'">
            <h2 class="auth-heading">Invalid invitation</h2>
            <p data-testid="register-invite-invalid" class="invite-notice eyebrow">
              This invitation link is invalid or has expired. Please request a new invite from a
              shared result page.
            </p>
            <p class="auth-switch eyebrow">
              Already have an account?
              <router-link to="/login" class="auth-link">Sign in</router-link>
            </p>
          </template>

          <!-- Valid invite: show the form with prefilled, disabled email -->
          <template v-else-if="pageState === 'valid'">
            <h2 class="auth-heading">Create account</h2>

            <q-form class="auth-form" @submit.prevent="handleRegister">
              <div class="q-mb-md">
                <div class="eyebrow q-mb-xs">Email</div>
                <q-input
                  data-testid="register-email"
                  :model-value="inviteEmail"
                  type="email"
                  outlined
                  dense
                  readonly
                  disable
                  autocomplete="email"
                />
              </div>

              <div class="q-mb-lg">
                <div class="eyebrow q-mb-xs">Password</div>
                <q-input
                  data-testid="register-password"
                  v-model="password"
                  type="password"
                  outlined
                  dense
                  autocomplete="new-password"
                  placeholder="••••••••"
                  :rules="[(v: string) => v.length >= 8 || 'Minimum 8 characters']"
                />
              </div>

              <q-btn
                data-testid="register-submit"
                type="submit"
                label="Create account"
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
              Already have an account?
              <router-link to="/login" class="auth-link">Sign in</router-link>
            </p>
          </template>
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
.invite-notice {
  color: var(--ink-soft);
  line-height: 1.6;
  margin: 0 0 20px;
}
</style>
