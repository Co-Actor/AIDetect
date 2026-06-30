import axios from 'axios';
import type { AxiosInstance } from 'axios';
import type { DetectionRequest, DetectionResult, Mode } from 'src/types/detection';
import type { RewriteRequest, RewriteResponse } from 'src/types/rewrite';
import type { UserInfo } from 'src/stores/auth';

const TOKEN_KEY = 'aidetect_auth_token';

// Single-domain by default: when VITE_API_BASE_URL is unset/empty, production builds
// use a relative base ('') so requests hit /v1/* on the same origin (proxied to the
// backend by the ingress). Local dev falls back to the standalone backend port.
const resolvedBaseUrl =
  import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://localhost:8010' : '');

const apiClient: AxiosInstance = axios.create({
  baseURL: resolvedBaseUrl,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
});

// Public endpoints that must NOT trigger a redirect on 401.
const PUBLIC_URL_PATTERNS = [
  /^\/v1\/share\/[^/]+$/, // GET /v1/share/{token}
  /^\/v1\/share\/[^/]+\/trial/, // POST /v1/share/{token}/trial
  /^\/v1\/auth\//, // all auth endpoints
];

function isPublicUrl(url: string): boolean {
  return PUBLIC_URL_PATTERNS.some((re) => re.test(url));
}

apiClient.interceptors.request.use((config) => {
  // Read token directly from localStorage to avoid Pinia init-order issues.
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null;
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`);
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const status: number | undefined = error?.response?.status;
    const requestUrl: string = error?.config?.url ?? '';

    if (status === 401 && !isPublicUrl(requestUrl)) {
      if (typeof localStorage !== 'undefined') {
        localStorage.removeItem(TOKEN_KEY);
      }
      // Hard redirect so the router guard picks up the cleared state.
      window.location.href = '/login';
      return new Promise(() => undefined); // swallow — redirect is happening
    }

    const data: unknown = error?.response?.data;
    let message = 'An unknown error occurred';
    if (data && typeof data === 'object' && 'detail' in data) {
      const detail = (data as { detail: unknown }).detail;
      if (typeof detail === 'string') message = detail;
      else if (Array.isArray(detail)) message = JSON.stringify(detail);
    } else if (error instanceof Error) {
      message = error.message;
    }
    return Promise.reject(new Error(message));
  },
);

// ── Auth ────────────────────────────────────────────────────────────────────

export interface AuthResponse {
  token: string;
  user: UserInfo;
}

export const authApi = {
  register(email: string, password: string, name?: string): Promise<AuthResponse> {
    return apiClient
      .post<AuthResponse>('/v1/auth/register', { email, password, name })
      .then((r) => r.data);
  },
  login(email: string, password: string): Promise<AuthResponse> {
    return apiClient.post<AuthResponse>('/v1/auth/login', { email, password }).then((r) => r.data);
  },
  google(id_token: string): Promise<AuthResponse> {
    return apiClient.post<AuthResponse>('/v1/auth/google', { id_token }).then((r) => r.data);
  },
  me(): Promise<UserInfo> {
    return apiClient.get<UserInfo>('/v1/auth/me').then((r) => r.data);
  },
};

// ── Detection ───────────────────────────────────────────────────────────────

export const detectionApi = {
  analyze(request: DetectionRequest): Promise<DetectionResult> {
    const payload: DetectionRequest = {
      mode: 'balanced',
      ...request,
      options: {
        include_evidence: true,
        include_signals: true,
        include_rubric_scores: true,
        ...(request.options ?? {}),
      },
    };
    return apiClient.post<DetectionResult>('/v1/detections', payload).then((res) => res.data);
  },
};

// ── Rewrite ─────────────────────────────────────────────────────────────────

export const rewriteApi = {
  rewrite(request: RewriteRequest): Promise<RewriteResponse> {
    const payload: RewriteRequest = {
      mode: 'balanced',
      ...request,
      options: {
        max_iterations: 2,
        target_ai_probability: 0.3,
        ...(request.options ?? {}),
      },
    };
    return apiClient
      .post<RewriteResponse>('/v1/rewrite', payload, { timeout: 90_000 })
      .then((res) => res.data);
  },
};

// ── Share ───────────────────────────────────────────────────────────────────

export interface ShareCreateRequest {
  input_text: string;
  mode?: Mode;
}

export interface ShareCreateResponse {
  token: string;
  url: string;
  trial_limit: number;
  trial_used: number;
}

export interface ShareGetResponse {
  token: string;
  result: DetectionResult;
  input_text: string;
  trial_used: number;
  trial_limit: number;
  active: boolean;
}

export interface ShareTrialRequest {
  text: string;
  mode?: string;
}

export interface ShareTrialResponse {
  result: DetectionResult;
  trial_used: number;
  trial_limit: number;
  remaining: number;
  active: boolean;
}

export const shareApi = {
  create(payload: ShareCreateRequest): Promise<ShareCreateResponse> {
    return apiClient.post<ShareCreateResponse>('/v1/share', payload).then((r) => r.data);
  },
  get(token: string): Promise<ShareGetResponse> {
    return apiClient.get<ShareGetResponse>(`/v1/share/${token}`).then((r) => r.data);
  },
  trial(token: string, payload: ShareTrialRequest): Promise<ShareTrialResponse> {
    return apiClient
      .post<ShareTrialResponse>(`/v1/share/${token}/trial`, payload)
      .then((r) => r.data);
  },
};

export default apiClient;
