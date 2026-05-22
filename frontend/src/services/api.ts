import axios from 'axios';
import type { AxiosInstance } from 'axios';
import type { DetectionRequest, DetectionResult } from 'src/types/detection';
import type { RewriteRequest, RewriteResponse } from 'src/types/rewrite';

const API_KEY_STORAGE_KEY = 'aidetect_api_key';

function bootstrapApiKey(): void {
  if (typeof localStorage === 'undefined') return;
  const stored = localStorage.getItem(API_KEY_STORAGE_KEY);
  if (stored) return;
  const fallback = import.meta.env.VITE_DEFAULT_API_KEY;
  if (fallback) {
    localStorage.setItem(API_KEY_STORAGE_KEY, fallback);
  }
}

bootstrapApiKey();

export function getApiKey(): string | null {
  if (typeof localStorage === 'undefined') return null;
  return localStorage.getItem(API_KEY_STORAGE_KEY);
}

export function setApiKey(value: string | null): void {
  if (typeof localStorage === 'undefined') return;
  if (value) localStorage.setItem(API_KEY_STORAGE_KEY, value);
  else localStorage.removeItem(API_KEY_STORAGE_KEY);
}

const apiClient: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8010',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
});

apiClient.interceptors.request.use((config) => {
  const apiKey = getApiKey();
  if (apiKey) {
    config.headers.set('X-API-Key', apiKey);
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
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
    return apiClient
      .post<DetectionResult>('/v1/detections', payload)
      .then((res) => res.data);
  },
};

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

export default apiClient;
