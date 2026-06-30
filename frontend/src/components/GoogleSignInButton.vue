<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useQuasar } from 'quasar';
import { useAuthStore } from 'src/stores/auth';
import { useRouter } from 'vue-router';

const $q = useQuasar();
const authStore = useAuthStore();
const router = useRouter();

const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
const show = ref(!!clientId);
const containerRef = ref<HTMLDivElement | null>(null);

// Minimal type declaration for Google Identity Services.
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
          }): void;
          renderButton(
            parent: HTMLElement,
            options: {
              theme?: string;
              size?: string;
              width?: number;
              text?: string;
            },
          ): void;
        };
      };
    };
  }
}

function initGoogle(): void {
  if (!clientId || !window.google || !containerRef.value) return;

  window.google.accounts.id.initialize({
    client_id: clientId,
    callback: async (response) => {
      try {
        await authStore.loginWithGoogle(response.credential);
        const redirect = (router.currentRoute.value.query.redirect as string) || '/';
        await router.push(redirect);
      } catch (err) {
        $q.notify({
          message: err instanceof Error ? err.message : 'Google sign-in failed',
          icon: 'error_outline',
          color: 'negative',
        });
      }
    },
  });

  window.google.accounts.id.renderButton(containerRef.value, {
    theme: 'outline',
    size: 'large',
    width: 320,
    text: 'continue_with',
  });
}

onMounted(() => {
  if (!clientId) return;

  if (window.google) {
    initGoogle();
    return;
  }

  const script = document.createElement('script');
  script.src = 'https://accounts.google.com/gsi/client';
  script.async = true;
  script.defer = true;
  script.onload = () => initGoogle();
  script.onerror = () => {
    $q.notify({
      message: 'Could not load Google Sign-In. Please try email/password.',
      icon: 'warning',
      color: 'warning',
    });
    show.value = false;
  };
  document.head.appendChild(script);
});
</script>

<template>
  <div v-if="show" class="google-signin-wrap">
    <div ref="containerRef" class="google-btn-container"></div>
  </div>
</template>

<style scoped lang="scss">
.google-signin-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  margin-top: 8px;
}
.google-btn-container {
  min-height: 44px;
}
</style>
