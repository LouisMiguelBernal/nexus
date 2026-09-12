/**
 * Local API token plumbing for the renderer.
 *
 * The backend protects /api/* with a bearer token (backend/ops/auth.py).
 * Rather than touching the ~50 fetch sites that exist today, `installApiAuth`
 * wraps `window.fetch` once so every request to the API base carries the
 * header. The Phase 4 data layer replaces this with a typed client.
 *
 * Token discovery order: the Electron preload (`window.nexus.apiToken`),
 * a build-time `NEXT_PUBLIC_NEXUS_API_TOKEN` (dev only), then localStorage
 * (`nexus-api-token`, for browser-based development against a token file).
 */

declare global {
  interface Window {
    nexus?: {
      platform?: string;
      isElectron?: boolean;
      apiToken?: string | null;
    };
  }
}

export const TOKEN_STORAGE_KEY = "nexus-api-token";

export function getApiToken(): string | null {
  if (typeof window === "undefined") return null;
  const fromShell = window.nexus?.apiToken;
  if (fromShell) return fromShell;
  const fromEnv = process.env.NEXT_PUBLIC_NEXUS_API_TOKEN;
  if (fromEnv) return fromEnv;
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

let installed = false;

/** Idempotent. Safe to call during module init on the client; a no-op during prerender. */
export function installApiAuth(apiBase: string): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (!url.startsWith(apiBase)) return original(input, init);
    const token = getApiToken();
    if (!token) return original(input, init);
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    if (!headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
    return original(input, { ...init, headers });
  };
}
