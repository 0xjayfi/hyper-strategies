import { API_BASE_URL } from '../lib/constants';

const MAX_RETRIES = 2;
const BACKOFF_DELAYS = [1000, 3000]; // 1s, 3s
const MAX_RETRY_AFTER_MS = 10_000; // cap Retry-After at 10s for UX
const RETRYABLE_STATUSES = new Set([429, 503]);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getRetryDelay(response: Response, attempt: number): number {
  const retryAfter = response.headers.get('Retry-After');
  if (retryAfter) {
    const seconds = Number(retryAfter);
    if (!Number.isNaN(seconds) && seconds > 0) {
      return Math.min(seconds * 1000, MAX_RETRY_AFTER_MS);
    }
  }
  return BACKOFF_DELAYS[attempt] ?? BACKOFF_DELAYS[BACKOFF_DELAYS.length - 1];
}

class ApiClient {
  baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  async get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
    const url = new URL(path, this.baseUrl || window.location.origin);
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          url.searchParams.set(key, String(value));
        }
      });
    }

    let lastError: ApiError | undefined;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      const response = await fetch(url.toString());

      if (response.ok) {
        return response.json();
      }

      const error = await response.json().catch(() => ({ detail: response.statusText }));
      lastError = new ApiError(response.status, error.detail || response.statusText);

      // Only retry on 429 / 503, and only if we have retries left
      if (!RETRYABLE_STATUSES.has(response.status) || attempt === MAX_RETRIES) {
        throw lastError;
      }

      const delay = getRetryDelay(response, attempt);
      await sleep(delay);
    }

    // Unreachable, but satisfies TypeScript
    throw lastError!;
  }
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export const apiClient = new ApiClient();
