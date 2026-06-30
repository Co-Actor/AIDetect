import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import { authApi } from 'src/services/api';

export interface UserInfo {
  id: string;
  email: string;
  name: string | null;
}

const TOKEN_KEY = 'aidetect_auth_token';

export const useAuthStore = defineStore('auth', () => {
  const router = useRouter();

  const token = ref<string | null>(
    typeof localStorage !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null,
  );
  const user = ref<UserInfo | null>(null);

  const isAuthenticated = computed(() => token.value !== null);

  function setSession(newToken: string, newUser: UserInfo): void {
    token.value = newToken;
    user.value = newUser;
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(TOKEN_KEY, newToken);
    }
  }

  function clearSession(): void {
    token.value = null;
    user.value = null;
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(TOKEN_KEY);
    }
  }

  async function register(email: string, password: string, name?: string): Promise<void> {
    const data = await authApi.register(email, password, name);
    setSession(data.token, data.user);
  }

  async function login(email: string, password: string): Promise<void> {
    const data = await authApi.login(email, password);
    setSession(data.token, data.user);
  }

  async function loginWithGoogle(idToken: string): Promise<void> {
    const data = await authApi.google(idToken);
    setSession(data.token, data.user);
  }

  async function fetchMe(): Promise<void> {
    try {
      const data = await authApi.me();
      user.value = data;
    } catch {
      clearSession();
    }
  }

  async function logout(): Promise<void> {
    clearSession();
    await router.push('/login');
  }

  return {
    token,
    user,
    isAuthenticated,
    register,
    login,
    loginWithGoogle,
    fetchMe,
    logout,
    setSession,
    clearSession,
  };
});
